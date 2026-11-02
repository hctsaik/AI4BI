"""Validated two-fact adapter around the pinned composition/statistics core.

Private projection names keep user identifiers out of the core SQL builder.
No detail join, row truncation, or client-side business aggregation is used.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime

import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype

from .errors import AppError
from .schemas import CrossFactSettings

ANALYSIS_CONTRACT = "crossfact-v1"
MAX_GROUPS = 10000
_NUMERIC = re.compile(r"integer|int|int32|int64|float|float32|float64|double|number|numeric|decimal", re.I)


def metric_columns(metric):
    if metric.kind == "aggregate":
        return [metric.column]
    return list(dict.fromkeys([metric.numerator_column, metric.denominator_column]))


def _delivery_invalid():
    raise AppError("CROSSFACT_DELIVERY_INVALID", "跨表分析結果、保存設定或完整性紀錄不一致。")


def validate_delivery_checks(body, checks):
    """Validate the compact receipt again before committing a publication."""
    from .report_extensions import extensions
    definitions = {item.analysis_id: item for item in extensions(body).crossfact_analyses}
    if checks is None and not definitions:
        return
    if not isinstance(checks, dict) or set(checks) != set(definitions):
        _delivery_invalid()
    for aid, item in checks.items():
        counts = ("aligned_count", "paired_count", "missing_pair_count", "zero_denominator_count",
                  "requested_quantiles", "actual_quantiles")
        if (not isinstance(item, dict) or item.get("analysis_contract") != ANALYSIS_CONTRACT
                or any(type(item.get(key)) is not int or item[key] < 0 for key in counts)):
            _delivery_invalid()
        aligned, paired, missing, zero, requested, actual = (item[key] for key in counts)
        if (aligned > MAX_GROUPS or paired + missing != aligned or zero > aligned
                or requested != definitions[aid].quantiles or actual > requested
                or item.get("status") != ("ready" if aligned else "empty")
                or definitions[aid].operation == "diff" and zero != 0):
            _delivery_invalid()
        correlation, cohort = item.get("correlation_status"), item.get("cohort_status")
        if (correlation not in ("insufficient_pairs", "constant_metric", "ready")
                or cohort not in ("insufficient_pairs", "constant_metric", "ready")
                or (correlation == "insufficient_pairs") != (paired < 3)
                or (cohort == "insufficient_pairs") != (paired < requested)
                or (cohort == "ready") != (actual > 0)):
            _delivery_invalid()


def _delivery_number(value):
    # clean() encodes integers outside JavaScript's exact range as strings.
    if isinstance(value, str) and re.fullmatch(r"-?(0|[1-9][0-9]*)", value):
        value = int(value)
        if abs(value) <= 2**53 - 1:
            _delivery_invalid()
    if type(value) not in (int, float):
        _delivery_invalid()
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        _delivery_invalid()
    return value


def delivery_checks(body, result):
    """Check full saved results before projecting any publication or document.

    This checks identity and structural completeness; it does not recompute
    business metrics or replace snapshot/runtime verification at the caller.
    """
    from .report_extensions import extensions
    definitions = {item.analysis_id: item for item in extensions(body).crossfact_analyses}
    analyses = result.get("crossfact_analyses", {})
    if not isinstance(analyses, dict) or set(analyses) != set(definitions):
        _delivery_invalid()
    fields = ("analysis_contract", "status", "aligned_count", "paired_count", "missing_pair_count",
              "zero_denominator_count", "requested_quantiles", "actual_quantiles",
              "correlation_status", "cohort_status")
    checks = {}
    for aid, item in analyses.items():
        definition = definitions[aid]
        if (not isinstance(item, dict) or item.get("analysis_id") != aid
                or item.get("name") != definition.name or item.get("page_id") != definition.page_id
                or item.get("settings") != definition.model_dump()
                or item.get("field_types") != definition.field_types):
            _delivery_invalid()
        checks[aid] = {field: item.get(field) for field in fields}
    validate_delivery_checks(body, checks)
    for aid, item in analyses.items():
        rows, cohorts = item.get("rows"), item.get("cohorts")
        if (not isinstance(rows, list) or len(rows) != item["aligned_count"]
                or not isinstance(cohorts, list) or len(cohorts) != item["actual_quantiles"]):
            _delivery_invalid()
        keys, pairs, zero = set(), [], 0
        operation = definitions[aid].operation
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"key", "a", "b", "result"}:
                _delivery_invalid()
            key = row["key"]
            if type(key) not in (str, int, float) or type(key) is float and not math.isfinite(key):
                _delivery_invalid()
            identity = (type(key), key)
            if identity in keys:
                _delivery_invalid()
            keys.add(identity)
            a, b, combined = (None if row[field] is None else _delivery_number(row[field])
                              for field in ("a", "b", "result"))
            denominator = b if operation == "ratio" else a
            zero += int(operation != "diff" and denominator == 0)
            undefined = a is None or b is None or operation != "diff" and denominator == 0
            if (combined is None) != undefined:
                _delivery_invalid()
            if a is not None and b is not None:
                pairs.append((a, b))
        if len(pairs) != item["paired_count"] or zero != item["zero_denominator_count"]:
            _delivery_invalid()
        unique_a, unique_b = ({pair[index] for pair in pairs} for index in (0, 1))
        expected_correlation = ("insufficient_pairs" if len(pairs) < 3 else "constant_metric"
                                if len(unique_a) < 2 or len(unique_b) < 2 else "ready")
        expected_cohort = ("insufficient_pairs" if len(pairs) < item["requested_quantiles"]
                           else "constant_metric" if len(unique_a) < 2 else "ready")
        if item["correlation_status"] != expected_correlation or item["cohort_status"] != expected_cohort:
            _delivery_invalid()
        correlation = item.get("correlation")
        if expected_correlation != "ready":
            if correlation is not None:
                _delivery_invalid()
        elif (not isinstance(correlation, dict) or type(correlation.get("n")) is not int
                or correlation["n"] != len(pairs) or abs(_delivery_number(correlation.get("r"))) > 1
                or not isinstance(correlation.get("direction"), str) or not correlation["direction"]
                or not isinstance(correlation.get("strength"), str) or not correlation["strength"]):
            _delivery_invalid()
        buckets, covered = set(), 0
        for cohort in cohorts:
            if (not isinstance(cohort, dict) or not isinstance(cohort.get("bucket"), str)
                    or not cohort["bucket"] or cohort["bucket"] in buckets
                    or not isinstance(cohort.get("range"), str) or not cohort["range"]
                    or type(cohort.get("count")) is not int or cohort["count"] <= 0):
                _delivery_invalid()
            _delivery_number(cohort.get("mean_b"))
            buckets.add(cohort["bucket"])
            covered += cohort["count"]
        if expected_cohort == "ready" and covered != len(pairs):
            _delivery_invalid()
        sources = item.get("sources")
        if not isinstance(sources, dict) or set(sources) != {"a", "b"}:
            _delivery_invalid()
        for source in sources.values():
            fields = ("input_rows", "excluded_key_rows", "missing_measure_rows", "group_count", "unmatched_groups")
            if not isinstance(source, dict) or any(type(source.get(k)) is not int or source[k] < 0 for k in fields):
                _delivery_invalid()
            total, excluded, missing, groups, unmatched = (source[k] for k in fields)
            if (excluded > total or missing > total - excluded or groups > total - excluded
                    or groups > MAX_GROUPS or groups != item["aligned_count"] + unmatched):
                _delivery_invalid()
    return checks


def validate_saved_analyses(body, contracts, definitions):
    for item in definitions:
        try:
            current = validate_settings(contracts, item)
        except AppError as exc:
            raise AppError("CROSSFACT_SETTINGS_INCOMPATIBLE", "跨表分析來源或欄位已不相容，請更新或刪除設定。", 409) from exc
        page = body.get("pages", {}).get(item.page_id)
        if current != item.field_types or page is None or (item.selected_component_id and item.selected_component_id not in page.get("visuals", {})):
            raise AppError("CROSSFACT_SETTINGS_INCOMPATIBLE", "跨表分析欄位型別或頁面引用已不相容，請更新或刪除設定。", 409)


def settings_command(body, kind, payload, contracts):
    import copy
    from uuid import uuid4
    from pydantic import ValidationError
    from .report_extensions import extensions, SavedCrossFactAnalysis
    action = kind.removesuffix("_crossfact_analysis")
    expected = {"save": {"name", "settings", "page_id", "selected_component_id"},
                "update": {"analysis_id", "settings", "page_id", "selected_component_id"},
                "rename": {"analysis_id", "name"}, "delete": {"analysis_id"}}
    if action not in expected or set(payload) != expected[action]:
        raise AppError("INVALID_CROSSFACT_SETTINGS", "跨表設定命令欄位不完整或含額外欄位。")
    extra = extensions(body).model_dump()
    items = extra["crossfact_analyses"]
    found = next((item for item in items if item["analysis_id"] == payload.get("analysis_id")), None)
    if action != "save" and found is None:
        raise AppError("CROSSFACT_SETTINGS_NOT_FOUND", "找不到跨表分析設定。", 404)
    if "name" in payload:
        name = payload["name"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise AppError("INVALID_CROSSFACT_SETTINGS", "跨表分析名稱須為 1 至 80 字。")
        name = name.strip()
        if any(item is not found and item["name"].casefold() == name.casefold() for item in items):
            raise AppError("DUPLICATE_CROSSFACT_SETTINGS", "已有相同名稱的跨表分析。")
    if action == "delete":
        items.remove(found)
    elif action == "rename":
        found["name"] = name
    else:
        if action == "save" and len(items) >= 30:
            raise AppError("CROSSFACT_SETTINGS_LIMIT", "每份報表最多保存 30 組跨表分析。")
        try:
            settings = CrossFactSettings.model_validate(payload["settings"])
            definition = SavedCrossFactAnalysis.model_validate({**settings.model_dump(),
                "analysis_id": found["analysis_id"] if found else "crossfact_" + uuid4().hex,
                "name": found["name"] if found else name, "page_id": payload["page_id"],
                "selected_component_id": payload["selected_component_id"],
                "field_types": validate_settings(contracts, settings), "analysis_contract": ANALYSIS_CONTRACT})
        except (ValidationError, TypeError) as exc:
            raise AppError("INVALID_CROSSFACT_SETTINGS", "跨表分析設定包含無效參數。") from exc
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
    definitions = extensions(snapshot["report"]).crossfact_analyses
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
    delivery_checks(snapshot["report"], {"crossfact_analyses": results})
    return results


def run_crossfact(root, snapshot):
    from .core import load_contracts
    from .publications import check_execution_runtime
    from .drilling import validate_snapshot
    check_execution_runtime(root, snapshot)
    if snapshot.get("analysis_contract") != ANALYSIS_CONTRACT:
        raise AppError("CROSSFACT_INCOMPATIBLE", "跨表分析版本已變更，請重新執行。", 409)
    validate_snapshot(snapshot)
    return analyze_snapshot(snapshot, load_contracts(root, snapshot["datasets"]))


def analyze_snapshot(snapshot, contracts):
    from ai4bi.report.models import ExecutableReportSpec
    from .core import clean
    from .analysis_scope import exploration_context
    from .drilling import validate_snapshot, assistant_drill_executor, assistant_source_contracts
    from .report_extensions import report_executor
    if snapshot.get("analysis_contract") != ANALYSIS_CONTRACT:
        raise AppError("CROSSFACT_INCOMPATIBLE", "跨表分析版本已變更，請重新執行。", 409)
    validate_snapshot(snapshot)
    settings = CrossFactSettings.model_validate({key: snapshot[key] for key in CrossFactSettings.model_fields})
    validate_settings(contracts, settings)
    page, filters, serialized = exploration_context(snapshot, contracts, analysis="CROSSFACT")
    selected = snapshot.get("selected_component_id")
    blocks = {settings.block_a, settings.block_b}
    executor, contracts = report_executor(snapshot["report"], contracts, page_id=page, visual_id=selected)
    _, context = assistant_drill_executor(executor, snapshot["report"], contracts, selected, snapshot.get("drill_state", {}))
    if context and context["block_id"] not in blocks:
        raise AppError("INVALID_CROSSFACT_CONTEXT", "鑽取來源必須屬於跨表分析的兩個來源。")
    selected_filters = []
    if selected is not None:
        report = ExecutableReportSpec.from_dict(snapshot["report"])
        selected_filters = executor._apply_active_filters(report.pages[page].visuals[selected].query, report.merged_filters()).filters
    scoped = assistant_source_contracts(executor, contracts, context, extra_filters=[*selected_filters, *filters])
    result = analyze(scoped, settings)
    return clean({**result, "snapshot_id": snapshot["snapshot_id"], "revision": snapshot["revision"],
                  "execution_contract": snapshot["execution_contract"], "exploration_page_id": page,
                  "selected_component_id": selected, "drill_context": context, "filters": serialized,
                  "applied_filters": [f for f in serialized if f["block_id"] in blocks],
                  "selected_query_filters": [f for f in selected_filters if f.block_id in blocks],
                  "filter_bookmark_id": snapshot.get("filter_bookmark_id"),
                  "data_versions": {d["dataset_id"]: d["version"] for d in snapshot["datasets"]}})


def validate_settings(contracts, settings):
    if settings.block_a == settings.block_b:
        raise AppError("INVALID_CROSSFACT", "跨表分析須選擇兩個不同的事實來源。")
    types = {}
    for side in ("a", "b"):
        bid, key, metric = (getattr(settings, name + side) for name in ("block_", "key_", "metric_"))
        contract = contracts.get(bid)
        if contract is None or contract.block_type.value != "fact":
            raise AppError("INVALID_CROSSFACT", "跨表分析須引用有效的事實來源。")
        declared = {column.name: column.data_type for column in contract.columns}
        fields = metric_columns(metric)
        if key not in declared or key in fields or any(c not in declared or not _NUMERIC.fullmatch(declared[c]) for c in fields):
            raise AppError("INVALID_CROSSFACT", "請選擇不同的共同鍵與有效數值欄位。")
        types[side] = {column: declared[column] for column in [key, *fields]}
    if types["a"][settings.key_a] != types["b"][settings.key_b]:
        raise AppError("CROSSFACT_KEY_TYPE_MISMATCH", "兩側共同鍵的宣告型別必須一致。")
    return types


def _project(frame, key, metric):
    """Preserve null measures for SQL aggregate semantics; exclude null keys."""
    fields = metric_columns(metric)
    if not frame.columns.is_unique or set([key, *fields]) - set(frame.columns):
        raise AppError("INVALID_CROSSFACT", "來源資料欄位與宣告不一致。")
    keys = frame[key].dropna()
    values = keys.tolist()
    types = {type(value) for value in values}
    if len(types) > 1 or any(isinstance(v, bool) or not isinstance(v, (str, int, float, date, datetime))
                             or isinstance(v, float) and not math.isfinite(v) for v in values):
        raise AppError("CROSSFACT_KEY_TYPE_MISMATCH", "共同鍵不能包含混合型別、複合值或非有限數字。")
    if keys.nunique() > MAX_GROUPS:
        raise AppError("CROSSFACT_LIMIT", "跨表分析每側最多 10,000 個群體，不截斷資料。")
    for column in fields:
        series = frame[column]
        if (not is_numeric_dtype(series) or is_bool_dtype(series)
                or not series.dropna().map(math.isfinite).all()):
            raise AppError("INVALID_CROSSFACT", "指標欄位須為數字，且不能包含無限值。")
    projected = frame.loc[frame[key].notna(), [key, *fields]].copy()
    names = {column: "value_" + str(i) for i, column in enumerate(fields)}
    projected = projected.rename(columns={key: "group_key", **names})
    return projected, names, types, {
        "input_rows": len(frame), "excluded_key_rows": int(frame[key].isna().sum()),
        "missing_measure_rows": int(frame.loc[frame[key].notna(), fields].isna().any(axis=1).sum()),
        "group_count": int(keys.nunique()),
    }


def analyze(contracts, settings):
    """Return complete aligned rows, combinations, Pearson and quantile cohorts.

    Aggregate null semantics are inherited from SQL (COUNT counts non-null;
    other aggregates ignore nulls and all-null groups remain null). Weighted
    ratios use independent SUMs with NULLIF, never an average of row ratios.
    """
    import duckdb
    from ai4bi.analysis.composition_executor import CompositionExecutor
    from ai4bi.analysis.cross_fact import combine
    from ai4bi.analysis.crossfact import correlate_facts, cohort_by_quantile
    from ai4bi.blocks.datastore import materialize_dataframe
    from ai4bi.blocks.contracts import ColumnSchema
    from ai4bi.planning.composition_plan import AggStep, ComposeStep, CompositionPlan, SimpleMetricExpr, RatioMetricExpr
    from .core import clean

    if not isinstance(settings, CrossFactSettings):
        settings = CrossFactSettings.model_validate(settings)
    field_types = validate_settings(contracts, settings)
    projections, key_types, counts, steps, normalized = {}, {}, {}, [], {}
    for side in ("a", "b"):
        bid, key, metric = (getattr(settings, name + side) for name in ("block_", "key_", "metric_"))
        frame = materialize_dataframe(contracts[bid])
        projected, names, key_types[side], counts[side] = _project(frame, key, metric)
        projections[side] = projected
        contract = contracts[bid].model_copy(deep=True)
        contract.block_id = side
        contract.columns = [ColumnSchema(name="group_key", data_type=field_types[side][key]),
                            *[ColumnSchema(name=names[c], data_type=field_types[side][c]) for c in names]]
        normalized[side] = contract
        expression = (SimpleMetricExpr(alias=side, agg_function=metric.aggregation, column=names[metric.column])
                      if metric.kind == "aggregate" else RatioMetricExpr(alias=side,
                      numerator_column=names[metric.numerator_column], denominator_column=names[metric.denominator_column],
                      scale=metric.scale))
        steps.append(AggStep(block_id=side, group_by_columns=["group_key"], metric_exprs=[expression]))
    if key_types["a"] and key_types["b"] and key_types["a"] != key_types["b"]:
        raise AppError("CROSSFACT_KEY_TYPE_MISMATCH", "兩側共同鍵的實際型別不一致，不能自動轉換識別碼。")
    plan = CompositionPlan(plan_id="crossfact", agg_steps=steps,
                           compose_step=ComposeStep(join_key="group_key", left_step_id="a", right_step_id="b"),
                           final_metrics=["a", "b"])
    plan.validate(normalized)
    with duckdb.connect(database=":memory:") as connection:
        for side, frame in projections.items():
            connection.register(side, frame)
        merged = CompositionExecutor().run(plan, connection, {"a": "a", "b": "b"})
    merged = merged.sort_values("group_key").reset_index(drop=True)
    if len(merged) > MAX_GROUPS or merged["group_key"].duplicated().any():
        raise AppError("CROSSFACT_INVALID_RESULT", "跨表結果違反每個共同鍵只產生一列的限制。", 500)
    for side in ("a", "b"):
        if not merged[side].dropna().map(math.isfinite).all():
            raise AppError("CROSSFACT_NONFINITE", "跨表聚合結果超出有限數值範圍。")
        counts[side]["unmatched_groups"] = counts[side]["group_count"] - len(merged)
    # The pinned helper uses pd.NA for zero denominators. Normalize its output
    # to nullable floats before rounding; object-series round cannot handle NA.
    combined = combine(merged["a"].astype(float), merged["b"].astype(float), settings.operation).astype("Float64").round(2)
    if not combined.dropna().map(math.isfinite).all():
        raise AppError("CROSSFACT_NONFINITE", "跨表計算結果超出有限數值範圍。")
    merged["result"] = combined
    pairs = merged[["a", "b"]].dropna()
    correlation = correlate_facts(pairs, "a", "b")
    correlation_status = ("insufficient_pairs" if len(pairs) < 3 else "constant_metric"
                          if pairs.a.nunique() < 2 or pairs.b.nunique() < 2 else "ready")
    if correlation_status == "ready" and (correlation is None or not math.isfinite(correlation["r"])):
        raise AppError("CROSSFACT_STATISTICS_UNAVAILABLE", "相關性運算無法完成。", 503)
    table = cohort_by_quantile(pairs, "a", "b", q=settings.quantiles)
    cohorts = [{"bucket": row["分組"], "range": row["a 範圍"], "count": row["筆數"], "mean_b": row["平均b"]}
               for row in table.to_dict("records")]
    cohort_status = ("insufficient_pairs" if len(pairs) < settings.quantiles else "constant_metric"
                     if pairs.a.nunique() < 2 else "ready")
    if cohort_status == "ready" and (not cohorts or sum(row["count"] for row in cohorts) != len(pairs)
                                     or any(not math.isfinite(row["mean_b"]) for row in cohorts)):
        raise AppError("CROSSFACT_STATISTICS_UNAVAILABLE", "分位群組運算無法完整涵蓋母體。", 503)
    denominator = merged["b"] if settings.operation == "ratio" else merged["a"]
    return clean({"analysis_contract": ANALYSIS_CONTRACT, "status": "ready" if len(merged) else "empty",
                  "settings": settings.model_dump(), "field_types": field_types, "sources": counts,
                  "aligned_count": len(merged), "paired_count": len(pairs),
                  "missing_pair_count": len(merged) - len(pairs),
                  "zero_denominator_count": int(denominator.eq(0).sum()) if settings.operation != "diff" else 0,
                  "rows": merged.rename(columns={"group_key": "key"}).to_dict("records"),
                  "correlation_status": correlation_status, "correlation": correlation,
                  "cohort_status": cohort_status, "requested_quantiles": settings.quantiles,
                  "actual_quantiles": len(cohorts), "cohorts": cohorts,
                  "notice": "兩側各自聚合後只保留共同鍵交集；缺值不補零。相關性不代表因果，未提供顯著性檢定。"
                            "相關係數四捨五入至三位，計算結果與分組平均至兩位；相同值可能使分位組數減少。"})
