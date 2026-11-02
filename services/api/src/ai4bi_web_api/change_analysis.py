"""Strict boundary for the pinned trailing-window comparison engine.

The caller supplies a governed, scoped query and an explicit date anchor.
This module does not load sources or interpret exploration filters.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
import math
from numbers import Real
from decimal import Decimal, localcontext
import sys

import pandas as pd

from .errors import AppError

ANALYSIS_CONTRACT = "change-v2"
PERIOD_DAYS = {"week": 7, "month": 30, "quarter": 90, "year": 365}
MAX_GROUPS = 10000
_GROUP = "__change_group"
_VALUE = "__change_value"


def _number(value):
    # Numeric strings are decoded only by WindowExecutor from an explicit SQL
    # VARCHAR projection; arbitrary executor strings remain invalid input.
    if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
        raise AppError("CHANGE_METRIC_UNDEFINED", "期間指標包含未定義或無效數值。")
    value = value if isinstance(value, Decimal) else Decimal(str(value))
    if not value.is_finite() or value.copy_abs() > Decimal(str(sys.float_info.max)):
        raise AppError("CHANGE_METRIC_UNDEFINED", "指標或變化超出有限數值範圍。")
    return value


def _wire_number(value):
    if value is None:
        return None
    value = _number(value)
    if value == value.to_integral_value():
        return int(value)
    candidate = float(value)
    return candidate if Decimal(str(candidate)) == value else format(value, "f")


def compare(executor, base_spec, *, block_id, date_column, dimension_column,
            period, anchor, additive):
    """Governed core aggregates with exact decimal differences and stable ties.

    The core period-spec helper still constructs both queries. Decimal arithmetic
    avoids pandas outer-merge coercion and int64 overflow in derived results.
    SQL metric evaluation, source filters and permissions remain in the core.
    """
    from ai4bi.analysis.time_intelligence import _period_spec
    from ai4bi.query_spec import DimensionRef

    if (period not in PERIOD_DAYS or type(anchor) is not date
            or type(additive) is not bool or len(base_spec.metrics) != 1
            or base_spec.metrics[0].block_id != block_id
            or not date_column or not dimension_column or date_column == dimension_column):
        raise AppError("CHANGE_SETTINGS_INVALID", "變化拆解需要單一指標、日期、拆解維度與有效期間。")
    days = PERIOD_DAYS[period]
    try:
        start = anchor - timedelta(days=days - 1)
        previous_end = start - timedelta(days=1)
        previous_start = start - timedelta(days=days)
    except OverflowError as exc:
        raise AppError("CHANGE_SETTINGS_INVALID", "比較期間超出支援日期範圍。") from exc
    base = replace(base_spec, metrics=[replace(base_spec.metrics[0], alias=_VALUE)],
                   dimensions=[], sort=[], limit=None)

    def execute(start, end, suffix, grouped):
        spec = _period_spec(base, block_id, date_column, start, end, suffix)
        spec = replace(spec, dimensions=[DimensionRef(block_id, dimension_column, _GROUP)] if grouped else [])
        frame = executor.run(spec)
        expected = [_GROUP, _VALUE] if grouped else [_VALUE]
        if not isinstance(frame, pd.DataFrame) or list(frame.columns) != expected:
            raise AppError("CHANGE_RESULT_INVALID", "變化拆解查詢未回傳預期欄位。")
        if len(frame) > (MAX_GROUPS if grouped else 1):
            raise AppError("CHANGE_RESULT_LIMIT", "變化拆解群組超過上限，請縮小分析範圍。")
        if not grouped:
            return None if frame.empty else _number(frame[_VALUE].iloc[0])
        values = {}
        for group, value in frame.itertuples(index=False, name=None):
            if pd.isna(group):
                group = None
            elif hasattr(group, "item"):
                group = group.item()
            if group is not None and type(group) not in (str, int, bool, float):
                raise AppError("CHANGE_RESULT_INVALID", "不支援此群組識別值型別。")
            if isinstance(group, float) and not math.isfinite(group):
                raise AppError("CHANGE_RESULT_INVALID", "群組識別值不能是非有限數字。")
            if group in values:
                raise AppError("CHANGE_RESULT_INVALID", "變化拆解回傳重複群組。")
            values[group] = _number(value)
        return values

    try:
        current_groups = execute(start, anchor, "gcur", True)
        previous_groups = execute(previous_start, previous_end, "gprev", True)
        keys = set(current_groups) | set(previous_groups)
        if len(keys) > MAX_GROUPS:
            raise AppError("CHANGE_RESULT_LIMIT", "變化拆解群組超過上限，請縮小分析範圍。")
        # Always use ungrouped governed execution for rates, averages, distinct
        # counts and other nonadditive formulas. Empty populations stay missing.
        current = execute(start, anchor, "ocur", False) if not additive and current_groups else None
        previous = execute(previous_start, previous_end, "oprev", False) if not additive and previous_groups else None
        values = [*current_groups.values(), *previous_groups.values(), *[v for v in (current, previous) if v is not None]]
        # Enough precision for exact sums/differences, even when a very large
        # value and a very small fraction occur together. Ratios round to 0.1.
        precision = max(80, max((v.adjusted() for v in values), default=0)
                        - min((v.as_tuple().exponent for v in values), default=0) + 12)
        with localcontext() as context:
            context.prec = precision
            if additive:
                current = sum(current_groups.values(), Decimal(0)) if keys else None
                previous = sum(previous_groups.values(), Decimal(0)) if keys else None
            delta = current - previous if current is not None and previous is not None else None
            rows = []
            for group in keys:
                cur = current_groups.get(group, Decimal(0) if additive else None)
                prev = previous_groups.get(group, Decimal(0) if additive else None)
                change = cur - prev if cur is not None and prev is not None else None
                percent = (change / abs(prev) * 100).quantize(Decimal("0.1")) if change is not None and prev else None
                contribution = ((change / delta * 100).quantize(Decimal("0.1")) if delta else Decimal(0)) if additive else None
                rows.append(dict(group=group, current=cur, previous=prev, delta=change,
                                 delta_pct=percent, contribution_pct=contribution))
            rows.sort(key=lambda row: (row["delta"] is None, row["delta"] or Decimal(0),
                      row["group"] is None, type(row["group"]).__name__, row["group"] if row["group"] is not None else ""))
            rows = [{"group": row["group"], **{k: _wire_number(v) for k, v in row.items() if k != "group"}} for row in rows]
            return {"analysis_contract": ANALYSIS_CONTRACT, "status": "ready" if rows else "empty",
                    "period": period, "anchor": anchor.isoformat(), "additive": additive,
                    "windows": {"current": [start.isoformat(), anchor.isoformat()],
                                "previous": [previous_start.isoformat(), previous_end.isoformat()]},
                    "overall_current": _wire_number(current), "overall_previous": _wire_number(previous),
                    "overall_delta": _wire_number(delta), "group_count": len(rows), "rows": rows}
    except AppError:
        raise
    except Exception as exc:
        raise AppError("CHANGE_QUERY_FAILED", "變化拆解查詢失敗，請檢查資料與指標設定。") from exc


def run_change(root, snapshot):
    from .core import load_contracts
    from .publications import check_execution_runtime
    from .drilling import validate_snapshot
    check_execution_runtime(root, snapshot)
    if snapshot.get("analysis_contract") != ANALYSIS_CONTRACT:
        raise AppError("CHANGE_INCOMPATIBLE", "變化拆解版本已變更，請重新執行。", 409)
    validate_snapshot(snapshot)
    return analyze_snapshot(snapshot, load_contracts(root, snapshot["datasets"]))


def settings_identity(body, contracts, settings):
    """Resolve signatures without executing or validating obsolete saved entries."""
    from ai4bi.blocks.contracts import MetricDefinition, DisaggregationMethod
    from .report_extensions import extensions
    from .storage import digest
    contract = contracts.get(settings.block_id)
    columns = {c.name: c.data_type.lower() for c in contract.columns} if contract else {}
    metric = next((m for m in contract.metrics if m.name == settings.metric_name), None) if contract else None
    calculation = next((m for m in extensions(body).calculated_metrics
                        if m.block_id == settings.block_id and m.name == settings.metric_name), None)
    if calculation is not None:
        if metric is not None and metric.formula != calculation.formula:
            raise AppError("CHANGE_SETTINGS_INCOMPATIBLE", "計算指標與來源指標名稱衝突。", 409)
        metric = MetricDefinition(name=calculation.name, formula=calculation.formula,
                                  disaggregation_method=DisaggregationMethod.none)
    if (contract is None or contract.block_type.value not in {"fact", "snapshot_fact", "target_fact"}
            or metric is None or columns.get(settings.date_column) not in {"date", "datetime", "timestamp"}
            or settings.dimension_column == settings.date_column
            or columns.get(settings.dimension_column) not in {"string", "str", "object", "integer", "int", "int32", "int64", "boolean", "bool"}):
        raise AppError("CHANGE_SETTINGS_INCOMPATIBLE", "變化拆解來源、指標、日期或類別欄位已不相容，請更新設定。", 409)
    if settings.anchor:
        try:
            anchor = date.fromisoformat(settings.anchor)
            anchor - timedelta(days=PERIOD_DAYS[settings.period] * 2 - 1)
            anchor + timedelta(days=1)
        except (ValueError, OverflowError) as exc:
            raise AppError("CHANGE_SETTINGS_INCOMPATIBLE", "變化拆解截止日或比較視窗不合法。", 409) from exc
    return {"field_types": {name: columns[getattr(settings, name)] for name in ("date_column", "dimension_column")},
            "metric_signature": digest({"formula": metric.formula, "method": metric.disaggregation_method.value, "unit": metric.unit})}


def validate_saved_analyses(body, contracts, definitions):
    if not definitions:
        return
    from ai4bi.report.models import ExecutableReportSpec
    report = ExecutableReportSpec.from_dict(body)
    for item in definitions:
        identity = settings_identity(body, contracts, item)
        page = report.pages.get(item.page_id)
        if (page is None or item.selected_component_id and item.selected_component_id not in page.visuals
                or page and not any(item.block_id in v.query.all_block_ids for v in page.visuals.values())
                or item.field_types != identity["field_types"] or item.metric_signature != identity["metric_signature"]):
            raise AppError("CHANGE_SETTINGS_INCOMPATIBLE", "變化拆解欄位、指標定義或頁面引用已變更，請更新或刪除設定。", 409)


def settings_command(body, kind, payload, contracts):
    import copy
    from uuid import uuid4
    from pydantic import ValidationError
    from .schemas import ChangeSettings
    from .report_extensions import extensions, SavedChangeAnalysis
    action = kind.removesuffix("_change_analysis")
    expected = {"save": {"name", "settings", "page_id", "selected_component_id"},
                "update": {"analysis_id", "settings", "page_id", "selected_component_id"},
                "rename": {"analysis_id", "name"}, "delete": {"analysis_id"}}
    if action not in expected or set(payload) != expected[action]:
        raise AppError("INVALID_CHANGE_SETTINGS", "變化拆解命令欄位不完整或含額外欄位。")
    extra = extensions(body).model_dump()
    items = extra["change_analyses"]
    found = next((item for item in items if item["analysis_id"] == payload.get("analysis_id")), None)
    if action != "save" and found is None:
        raise AppError("CHANGE_SETTINGS_NOT_FOUND", "找不到變化拆解設定。", 404)
    if "name" in payload:
        name = payload["name"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise AppError("INVALID_CHANGE_SETTINGS", "變化拆解名稱須為 1 至 80 字。")
        name = name.strip()
        if any(item is not found and item["name"].casefold() == name.casefold() for item in items):
            raise AppError("DUPLICATE_CHANGE_SETTINGS", "已有同名變化拆解設定。")
    if action == "delete":
        items.remove(found)
    elif action == "rename":
        found["name"] = name
    else:
        if action == "save" and len(items) >= 30:
            raise AppError("CHANGE_SETTINGS_LIMIT", "每份報表最多保存 30 組變化拆解。")
        try:
            settings = ChangeSettings.model_validate(payload["settings"])
            definition = SavedChangeAnalysis.model_validate({**settings.model_dump(),
                "analysis_id": found["analysis_id"] if found else "change_" + uuid4().hex,
                "name": found["name"] if found else name, "page_id": payload["page_id"],
                "selected_component_id": payload["selected_component_id"],
                **settings_identity(body, contracts, settings), "analysis_contract": ANALYSIS_CONTRACT})
        except (ValidationError, TypeError) as exc:
            raise AppError("INVALID_CHANGE_SETTINGS", "變化拆解設定包含無效參數。") from exc
        validate_saved_analyses(body, contracts, [definition])
        if found is None:
            items.append(definition.model_dump())
        else:
            found.update(definition.model_dump())
    result = copy.deepcopy(body)
    result["web_extensions"] = extra
    return result


def run_saved_analyses(snapshot, contracts):
    from .report_extensions import extensions
    from .bookmarks import exploration_page
    definitions = extensions(snapshot["report"]).change_analyses
    validate_saved_analyses(snapshot["report"], contracts, definitions)
    active_page = exploration_page(snapshot["report"], snapshot)
    results = {}
    for item in definitions:
        page = snapshot["report"]["pages"][item.page_id]
        scoped = {**snapshot, **item.model_dump(), "exploration_page_id": item.page_id,
                  "filters": snapshot.get("filters", []) if item.page_id == active_page else [],
                  "drill_state": {vid: state for vid, state in snapshot.get("drill_state", {}).items() if vid in page["visuals"]}}
        results[item.analysis_id] = {**analyze_snapshot(scoped, contracts), "analysis_id": item.analysis_id,
                                   "name": item.name, "page_id": item.page_id, "settings": item.model_dump()}
    return results


def _delivery_invalid():
    raise AppError("CHANGE_DELIVERY_INVALID", "變化拆解結果、保存設定或完整性紀錄不一致。")


def _delivery_number(value):
    """Decode only the canonical JSON representation emitted by change-v2."""
    from .core import clean
    import re
    if type(value) not in (int, float, str):
        _delivery_invalid()
    if isinstance(value, str) and not re.fullmatch(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?", value):
        _delivery_invalid()
    try:
        number = _number(Decimal(str(value)))
        canonical = clean(_wire_number(number))
    except (ValueError, ArithmeticError, AppError):
        _delivery_invalid()
    if type(canonical) is not type(value) or canonical != value:
        _delivery_invalid()
    return number


def validate_delivery_checks(body, checks):
    """Recheck saved definition identity and period receipts at publication commit."""
    from .report_extensions import extensions
    from .storage import digest
    definitions = {item.analysis_id: item for item in extensions(body).change_analyses}
    if checks is None and not definitions:
        return
    if not isinstance(checks, dict) or set(checks) != set(definitions):
        _delivery_invalid()
    for aid, receipt in checks.items():
        definition = definitions[aid]
        if (not isinstance(receipt, dict) or receipt.get("analysis_contract") != ANALYSIS_CONTRACT
                or receipt.get("settings_digest") != digest(definition.model_dump())
                or type(receipt.get("group_count")) is not int or not 0 <= receipt["group_count"] <= MAX_GROUPS
                or type(receipt.get("additive")) is not bool
                or receipt.get("status") != ("ready" if receipt["group_count"] else "empty")):
            _delivery_invalid()
        anchor = receipt.get("anchor")
        if definition.anchor is not None and anchor != definition.anchor:
            _delivery_invalid()
        if anchor is None:
            if receipt["group_count"] or receipt.get("windows") is not None:
                _delivery_invalid()
        else:
            try:
                end = date.fromisoformat(anchor)
                days = PERIOD_DAYS[definition.period]
                start = end - timedelta(days=days - 1)
                expected = {"current": [start.isoformat(), end.isoformat()],
                            "previous": [(start-timedelta(days=days)).isoformat(), (start-timedelta(days=1)).isoformat()]}
            except (TypeError, ValueError, OverflowError):
                _delivery_invalid()
            if anchor != end.isoformat() or receipt.get("windows") != expected:
                _delivery_invalid()


def delivery_checks(body, result):
    """Validate complete saved results before any document projection.

    Scope and source authenticity remain the snapshot executor's responsibility;
    this boundary checks identity, completeness and exact arithmetic consistency.
    """
    from .report_extensions import extensions
    from .storage import digest
    definitions = {item.analysis_id: item for item in extensions(body).change_analyses}
    analyses = result.get("change_analyses", {})
    if not isinstance(analyses, dict) or set(analyses) != set(definitions):
        _delivery_invalid()
    checks = {}
    for aid, item in analyses.items():
        definition = definitions[aid]
        if (not isinstance(item, dict) or item.get("analysis_id") != aid
                or not {"overall_current", "overall_previous", "overall_delta", "snapshot_id", "revision", "execution_contract", "data_versions"} <= item.keys()
                or item.get("name") != definition.name or item.get("page_id") != definition.page_id
                or item.get("settings") != definition.model_dump() or item.get("period") != definition.period
                or item.get("exploration_page_id") != definition.page_id
                or item.get("selected_component_id") != definition.selected_component_id
                or item.get("timezone") != "UTC" or item.get("filter_policy") != definition.filter_policy
                or any(item.get(key) != result.get(key) for key in ("snapshot_id", "revision", "execution_contract", "data_versions"))):
            _delivery_invalid()
        checks[aid] = {key: item.get(key) for key in ("analysis_contract", "status", "group_count", "additive", "anchor", "windows")}
        checks[aid]["settings_digest"] = digest(definition.model_dump())
    validate_delivery_checks(body, checks)
    for aid, item in analyses.items():
        rows = item.get("rows")
        if not isinstance(rows, list) or len(rows) != item["group_count"]:
            _delivery_invalid()
        fields = ("current", "previous", "delta", "delta_pct", "contribution_pct")
        decoded, identities = [], set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"group", *fields}:
                _delivery_invalid()
            group = row["group"]
            if group is not None and type(group) not in (str, int, float, bool):
                _delivery_invalid()
            if type(group) is float and not math.isfinite(group):
                _delivery_invalid()
            identity = (type(group), group)
            if identity in identities:
                _delivery_invalid()
            identities.add(identity)
            decoded.append({key: None if row[key] is None else _delivery_number(row[key]) for key in fields})
        overall = [None if item.get(key) is None else _delivery_number(item[key])
                   for key in ("overall_current", "overall_previous", "overall_delta")]
        numbers = [v for row in decoded for v in row.values() if v is not None] + [v for v in overall if v is not None]
        with localcontext() as context:
            context.prec = max(80, max((v.adjusted() for v in numbers), default=0)
                               - min((v.as_tuple().exponent for v in numbers), default=0) + 12)
            current, previous, delta = overall
            if delta != (current-previous if current is not None and previous is not None else None):
                _delivery_invalid()
            if not rows and any(v is not None for v in overall):
                _delivery_invalid()
            for row in decoded:
                cur, prev, change = (row[key] for key in ("current", "previous", "delta"))
                if item["additive"] and (cur is None or prev is None):
                    _delivery_invalid()
                if cur is None and prev is None:
                    _delivery_invalid()
                expected_delta = cur-prev if cur is not None and prev is not None else None
                if change != expected_delta:
                    _delivery_invalid()
                percent = (expected_delta/abs(prev)*100).quantize(Decimal("0.1")) if expected_delta is not None and prev else None
                contribution = ((change/delta*100).quantize(Decimal("0.1")) if delta else Decimal(0)) if item["additive"] else None
                if change != expected_delta or row["delta_pct"] != percent or row["contribution_pct"] != contribution:
                    _delivery_invalid()
            if rows and item["additive"] and any(overall[index] != sum((row[key] for row in decoded), Decimal(0))
                                               for index, key in enumerate(("current", "previous", "delta"))):
                _delivery_invalid()
            if rows and not item["additive"] and any((overall[index] is None) != all(row[key] is None for row in decoded)
                                                    for index, key in enumerate(("current", "previous"))):
                _delivery_invalid()
    return checks


def analyze_snapshot(snapshot, contracts):
    """Use captured scope, governed metrics and UTC windows for one analysis."""
    from ai4bi.query_spec import BlockRef, MetricRef, VisualQuerySpec, DimensionRef, FilterSpec, FilterOperator
    from ai4bi.report.models import ExecutableReportSpec
    from .schemas import ChangeSettings
    from .core import clean
    from .analysis_scope import exploration_context
    from .report_extensions import report_executor
    from .drilling import assistant_drill_executor, validate_snapshot
    from .comparison import window_executor, windows

    if snapshot.get("analysis_contract") != ANALYSIS_CONTRACT:
        raise AppError("CHANGE_INCOMPATIBLE", "變化拆解版本已變更，請重新執行。", 409)
    validate_snapshot(snapshot)
    settings = ChangeSettings.model_validate({k: snapshot[k] for k in ChangeSettings.model_fields})
    page, transient, serialized = exploration_context(snapshot, contracts, analysis="CHANGE")
    selected = snapshot.get("selected_component_id")
    body = snapshot["report"]
    report = ExecutableReportSpec.from_dict(body)
    if page is None or not any(settings.block_id in v.query.all_block_ids for v in report.pages[page].visuals.values()):
        raise AppError("INVALID_CHANGE_CONTEXT", "變化拆解來源必須用於目前探索頁面。")
    executor, enriched = report_executor(body, contracts, page_id=page, visual_id=selected)
    contract = enriched.get(settings.block_id)
    columns = {c.name: c.data_type.lower() for c in contract.columns} if contract else {}
    metric = next((m for m in contract.metrics if m.name == settings.metric_name), None) if contract else None
    if (contract is None or contract.block_type.value not in {"fact", "snapshot_fact", "target_fact"}
            or metric is None or columns.get(settings.date_column) not in {"date", "datetime", "timestamp"}
            or settings.dimension_column not in columns or settings.dimension_column == settings.date_column
            or columns[settings.dimension_column] not in {"string", "str", "object", "integer", "int", "int32", "int64", "boolean", "bool"}):
        raise AppError("CHANGE_SETTINGS_INVALID", "請選擇有效指標、日期欄位與類別維度。")
    additive = getattr(metric.disaggregation_method, "value", None) == "sum"
    _, context = assistant_drill_executor(executor, body, enriched, selected, snapshot.get("drill_state", {}))
    if context and context["block_id"] != settings.block_id:
        raise AppError("INVALID_CHANGE_CONTEXT", "鑽取來源必須與變化拆解來源相同。")
    query = VisualQuerySpec("change_analysis", [BlockRef(settings.block_id)],
                           metrics=[MetricRef(settings.block_id, settings.metric_name, _VALUE)])
    if selected:
        selected_query = report.pages[page].visuals[selected].query
        inherited = executor._apply_active_filters(selected_query, report.merged_filters()).filters
    else:
        inherited = executor._apply_active_filters(query, report.merged_filters()).filters
    query.filters = [f for f in [*inherited, *transient] if f.block_id == settings.block_id]
    if context:
        query.filters.extend(FilterSpec(settings.block_id, step["column"],
                             FilterOperator.is_null if step["value"] is None else FilterOperator.eq, step["value"])
                             for step in context["path"])
    scope = dict(page_id=page, visual_id=selected)
    metadata = {}
    anchor = None
    if settings.anchor:
        try:
            anchor = date.fromisoformat(settings.anchor)
        except ValueError as exc:
            raise AppError("CHANGE_SETTINGS_INVALID", "日期錨點不是有效日期。") from exc
    else:
        probe = replace(query, metrics=[], dimensions=[DimensionRef(settings.block_id, settings.date_column, "__comparison_anchor")])
        with executor.comparison_window(settings.block_id, settings.date_column):
            frame, info = executor.run_with_metadata(probe, **scope)
        metadata["anchor"] = clean(info)
        value = frame.iloc[0]["__comparison_anchor"] if len(frame) else None
        if value is not None and not pd.isna(value):
            anchor = value.date() if hasattr(value, "date") else date.fromisoformat(str(value))
    config = {"block_id": settings.block_id, "column_name": settings.date_column, "filter_policy": settings.filter_policy}
    scoped, base = window_executor(executor, query, config, page, selected)
    if anchor is None:
        result = {"analysis_contract": ANALYSIS_CONTRACT, "status": "empty", "anchor": None,
                  "period": settings.period, "additive": additive, "windows": None, "rows": [], "group_count": 0,
                  "overall_current": None, "overall_previous": None, "overall_delta": None}
    else:
        try:
            current, previous = windows(anchor, settings.period, "trailing")
        except OverflowError as exc:
            raise AppError("CHANGE_SETTINGS_INVALID", "比較期間超出支援日期範圍。") from exc

        class WindowExecutor:
            def run(self, spec):
                suffix = spec.spec_id.rsplit("__", 1)[-1]
                window = current if suffix in {"gcur", "ocur"} else previous
                # The pinned helper rewrites date filters. Restore the already
                # validated keep/replace scope and inject a UTC half-open window.
                spec = replace(spec, filters=base.filters, having=[])
                with scoped.comparison_window(settings.block_id, settings.date_column, window), scoped.exact_metric_output(_VALUE):
                    frame, info = scoped.run_with_metadata(spec, **scope)
                metadata[suffix] = clean(info)
                frame = frame.copy()
                frame[_VALUE] = frame[_VALUE].map(lambda v: Decimal(v) if isinstance(v, str) else v)
                return frame

        result = compare(WindowExecutor(), base, block_id=settings.block_id, date_column=settings.date_column,
                         dimension_column=settings.dimension_column, period=settings.period, anchor=anchor, additive=additive)
    return clean({**result, "settings": settings.model_dump(), "timezone": "UTC", "filter_policy": settings.filter_policy,
                  "metric_formula": metric.formula, "metric_unit": metric.unit, "metadata": metadata,
                  "snapshot_id": snapshot["snapshot_id"], "revision": snapshot["revision"],
                  "execution_contract": snapshot["execution_contract"], "exploration_page_id": page,
                  "selected_component_id": selected, "drill_context": context, "filters": serialized,
                  "filter_bookmark_id": snapshot.get("filter_bookmark_id"),
                  "data_versions": {d["dataset_id"]: d["version"] for d in snapshot["datasets"]},
                  "notice": "非加總指標只比較各組與整體變化，不顯示加總貢獻率。" if not additive else
                            "貢獻率以帶正負號的整體變化為分母；正負變化可能互相抵銷。"})
