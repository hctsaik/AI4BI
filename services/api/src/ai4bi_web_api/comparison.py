"""Scoped KPI period queries; no renderer or mutable source dependency."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from datetime import date, timedelta
import copy

from ai4bi.analysis.executor import _qualified, _quote, _require_column
from ai4bi.query_spec import DimensionRef
from .errors import AppError
from .filters import GroupedExecutor, ScopedExecutor, PersistentFilter, PersistentFilterGroup, FilterExpression, predicates
from .kpi import finite, number_label

DAYS = {"week": 7, "month": 30, "quarter": 90, "year": 365}


def validate_comparison(query, style, contracts):
    extra = style.extra
    period = extra.get("compare_period")
    if period is None or period == "":
        return None
    mode = extra.get("compare_mode", "trailing")
    policy = extra.get("compare_filter_policy", "replace")
    block = extra.get("compare_date_block", query.primary_block_id)
    column = extra.get("compare_date_column")
    if not all(isinstance(value, str) for value in (period, mode, policy, block, column)):
        raise AppError("INVALID_COMPARISON", "期間、模式、日期欄位與篩選策略須為有效文字。")
    contract = contracts.get(block)
    field = next((c for c in contract.columns if c.name == column), None) if contract else None
    if (period not in DAYS or mode not in ("trailing", "calendar") or (mode == "calendar" and period == "week")
            or policy not in ("keep", "replace") or block not in query.all_block_ids or field is None
            or field.data_type.lower() not in ("date", "datetime", "timestamp")):
        raise AppError("INVALID_COMPARISON", "期間比較需要有效日期欄位、視窗與篩選策略。")
    if query.dimensions or len(query.metrics) != 1 or style.extra.get("postprocess"):
        raise AppError("INVALID_COMPARISON", "期間比較限單一未分組指標，請先移除分組、多指標或後處理。")
    return {"period": period, "mode": mode, "filter_policy": policy, "block_id": block, "column_name": column}


def windows(anchor, period, mode):
    if mode == "trailing":
        start = anchor - timedelta(days=DAYS[period]-1)
        return (start, anchor+timedelta(days=1)), (start-timedelta(days=DAYS[period]), start)
    from ai4bi.analysis.time_intelligence import _calendar_window
    current_start, current_end, previous_start, previous_end = _calendar_window(anchor, period)
    return (current_start, current_end+timedelta(days=1)), (previous_start, previous_end+timedelta(days=1))


class ComparisonExecutor(GroupedExecutor):
    """Pinned-core extension for explicit UTC date boundaries and scalar anchor."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._comparison = ContextVar("comparison_window", default=None)
        self._daily = ContextVar("daily_series", default=None)
        self._exact_metric = ContextVar("exact_metric_output", default=None)

    @contextmanager
    def exact_metric_output(self, alias):
        """Keep SQL numeric text intact through the pinned core's .df() fetch."""
        token = self._exact_metric.set(alias)
        try:
            yield
        finally:
            self._exact_metric.reset(token)

    @contextmanager
    def daily_series(self, block, column):
        token = self._daily.set((block, column))
        try:
            yield
        finally:
            self._daily.reset(token)

    @contextmanager
    def comparison_window(self, block, column, window=None):
        token = self._comparison.set((block, column, window))
        try:
            yield
        finally:
            self._comparison.reset(token)

    def _comparison_day(self, contracts):
        block, column, _ = self._comparison.get()
        _require_column(contracts, block, column)
        return f"CAST(CAST({_qualified(block, column)} AS TIMESTAMPTZ) AT TIME ZONE 'UTC' AS DATE)"

    def _build_dimension_expr(self, dimension, contracts):
        daily = self._daily.get()
        if daily and (dimension.block_id, dimension.column_name) == daily:
            _require_column(contracts, *daily)
            return f"CAST(CAST({_qualified(*daily)} AS TIMESTAMPTZ) AT TIME ZONE 'UTC' AS DATE) AS " + _quote(dimension.alias)
        context = self._comparison.get()
        if context and context[2] is None:
            return self._comparison_day(contracts) + " AS " + _quote(dimension.alias)
        from .date_dimensions import date_dimension_sql
        bucket = date_dimension_sql(dimension, contracts)
        if bucket is not None:
            return bucket
        return super()._build_dimension_expr(dimension, contracts)

    def _build_sql(self, spec, contracts, joins, params):
        sql = super()._build_sql(spec, contracts, joins, params)
        alias = self._exact_metric.get()
        if alias is not None:
            name = _quote(alias)
            sql = f"SELECT * REPLACE (CAST({name} AS VARCHAR) AS {name}) FROM ({sql}) AS exact_values"
        context = self._comparison.get()
        if context:
            if context[2] is None:
                sql = 'SELECT MAX("__comparison_anchor") AS "__comparison_anchor" FROM (' + sql + ') AS anchor_rows'
            # Each core execution owns a fresh connection. This affects only the
            # comparison query, including interpretation of naive timestamps.
            sql = "SET TimeZone='UTC'; " + sql
        if (self._daily.get() or any(d.truncate_date_to for d in spec.dimensions)) and not context:
            sql = "SET TimeZone='UTC'; " + sql
        return sql

    def _rls_predicates(self, spec, contracts, params):
        clauses = super()._rls_predicates(spec, contracts, params)
        context = self._comparison.get()
        if context and context[2] is not None:
            start, end = context[2]
            expression = self._comparison_day(contracts)
            params.extend((start.isoformat(), end.isoformat()))
            clauses.append(f"({expression} >= ? AND {expression} < ?)")
        return clauses

    def run_with_metadata(self, *args, **kwargs):
        frame, metadata = super().run_with_metadata(*args, **kwargs)
        context = self._comparison.get()
        if context:
            block, column, window = context
            metadata.filters_applied.append(f"comparison UTC {block}.{column}: " +
                (f"{window[0]} <= day < {window[1]}" if window else "anchor before HAVING"))
        return frame, metadata


def window_executor(executor, query, config, page_id, visual_id):
    """Remove only separable date predicates; never alter RLS or unrelated ORs."""
    query = copy.deepcopy(query)
    if config["filter_policy"] == "keep":
        return executor, query
    def matching(leaf):
        return leaf.block_id == config["block_id"] and leaf.column_name == config["column_name"]
    def trim(node):
        leaves = predicates(node)
        if not any(matching(leaf) for leaf in leaves):
            return node
        if all(matching(leaf) for leaf in leaves):
            return None
        if node.operator == "or":
            raise AppError("AMBIGUOUS_COMPARISON_FILTER", "日期與其他欄位混合於 OR 群組，無法取代日期篩選；請改為保留篩選或調整群組。")
        children = [part for child in node.children if (part := trim(child)) is not None]
        return children[0] if len(children) == 1 else node.model_copy(update={"children": children})
    query.filters = [item for item in query.filters if not matching(item)]
    items = []
    applicable = {item.filter_id for item in executor.applicable(query, page_id, visual_id)}
    for item in executor.items:
        if item.filter_id not in applicable:
            items.append(item)
        elif isinstance(item, PersistentFilterGroup):
            expression = trim(item.expression)
            if isinstance(expression, FilterExpression):
                items.append(item.model_copy(update={"expression": expression}))
            elif expression is not None:
                scope = item.model_dump(exclude={"expression", "block_id"})
                items.append(PersistentFilter.model_validate({**scope, **expression.model_dump()}))
        elif not matching(item):
            items.append(item)
    return ScopedExecutor(executor.executor, executor.body, items, page_id, visual_id), query


def compare_query(executor, query, style, contracts, *, active_filters, page_id, visual_id):
    import pandas as pd
    from .core import clean
    config = validate_comparison(query, style, contracts)
    scope = dict(active_filters=active_filters, page_id=page_id, visual_id=visual_id)
    metric = query.metrics[0].alias or query.metrics[0].metric_name
    probe = replace(query, metrics=[], dimensions=[DimensionRef(config["block_id"], config["column_name"], "__comparison_anchor")],
                    having=[], sort=[], limit=None)
    with executor.comparison_window(config["block_id"], config["column_name"]):
        anchor_frame, anchor_metadata = executor.run_with_metadata(probe, **scope)
    anchor = anchor_frame.iloc[0]["__comparison_anchor"]
    result = {"version": 1, **config, "timezone": "UTC", "anchor": None, "status": "unavailable", "reason": None,
              "current": None, "previous": None, "delta": None, "delta_percent": None,
              "current_window": None, "previous_window": None, "previous_label": "—", "delta_label": "—",
              "anchor_metadata": clean(anchor_metadata), "previous_metadata": None, "captions": []}
    if pd.isna(anchor):
        result["reason"] = "目前篩選內沒有有效日期，無法比較；未改用全部期間數字。"
        return pd.DataFrame([{metric: None}]), anchor_metadata, result
    anchor = anchor.date() if hasattr(anchor, "date") else date.fromisoformat(str(anchor))
    current_window, previous_window = windows(anchor, config["period"], config["mode"])
    scoped, base = window_executor(executor, query, config, page_id, visual_id)
    def run(window):
        period_query = replace(base, data_version=f"{base.data_version}:comparison:{config['block_id']}:{config['column_name']}:{window[0]}:{window[1]}")
        with scoped.comparison_window(config["block_id"], config["column_name"], window):
            return scoped.run_with_metadata(period_query, **scope)
    current_frame, metadata = run(current_window)
    previous_frame, previous_metadata = run(previous_window)
    def scalar(frame):
        value = clean(frame)["rows"][0].get(metric) if len(frame) == 1 else None
        return value if finite(value) else None
    current, previous = scalar(current_frame), scalar(previous_frame)
    result.update(anchor=anchor.isoformat(), current=current, previous=previous,
                  current_window=[d.isoformat() for d in current_window], previous_window=[d.isoformat() for d in previous_window],
                  previous_metadata=clean(previous_metadata), previous_label=number_label(previous, style.extra))
    result["captions"] = [f"{label} {start.isoformat()} 至 {(end-timedelta(days=1)).isoformat()}（含）"
                          for label, (start, end) in (("本期", current_window), ("前期", previous_window))]
    if current is None or previous is None:
        result["reason"] = "本期或前期沒有有限值（可能無資料或未通過聚合篩選），無法計算差異。"
    else:
        delta = current - previous
        percent = delta / abs(previous) * 100 if previous else None
        if finite(delta):
            result.update(status="ready", delta=delta, delta_label=("+" if delta > 0 else "") + number_label(delta, style.extra))
        else:
            result["reason"] = "差異超出可計算範圍。"
        if percent is not None and finite(percent):
            result["delta_percent"] = percent
        elif previous == 0:
            result["reason"] = "前期為零，百分比差異未定義；保留絕對差異。"
        else:
            result["reason"] = "百分比差異超出可計算範圍。"
    unit = style.extra.get("unit", "")
    percent_label = f"（{result['delta_percent']:+,.2f}%）" if result["delta_percent"] is not None else ""
    result["captions"].extend([f"前期 {result['previous_label']}{unit} · 差異 {result['delta_label']}{unit}{percent_label}",
        f"UTC 日界 · {'保留全部篩選' if config['filter_policy'] == 'keep' else '比較視窗取代日期篩選'} · 錨定篩選內最新日期"])
    # Display eligibility must not replace exact governed values (such as
    # Decimal or integers encoded as strings for JavaScript) with nulls.
    # Only synthesize a null row when HAVING removed the scalar entirely.
    return current_frame if len(current_frame) else pd.DataFrame([{metric: None}]), metadata, result
