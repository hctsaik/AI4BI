"""Commonality adapter: intersect measured groups before calling the pinned core."""
from __future__ import annotations

import math

import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype

from .errors import AppError

ANALYSIS_CONTRACT = "commonality-v1"
MAX_ENTITIES = 5000


def validate_delivery_checks(body, checks):
    from .report_extensions import extensions
    expected = {item.analysis_id for item in extensions(body).commonality_analyses}
    if checks is None and not expected:
        return
    if not isinstance(checks, dict) or set(checks) != expected:
        raise AppError("COMMONALITY_DELIVERY_INVALID", "共同性分析結果與保存設定不完整對應。")
    for item in checks.values():
        fields = ("population_count", "qualifying_count", "comparison_count")
        if (not isinstance(item, dict) or item.get("analysis_contract") != ANALYSIS_CONTRACT
                or any(type(item.get(key)) is not int or item[key] < 0 for key in fields)):
            raise AppError("COMMONALITY_DELIVERY_INVALID", "共同性分析版本或群體數量不合法。")
        population, qualifying, comparison = (item[key] for key in fields)
        expected_status = ("empty" if population == 0 else "no_qualifying_groups" if qualifying == 0
                           else "no_comparison_groups" if comparison == 0 else "ready")
        if population != qualifying + comparison or item.get("status") != expected_status:
            raise AppError("COMMONALITY_DELIVERY_INVALID", "共同性分析狀態與群體數量不一致。")


def delivery_checks(body, result):
    analyses = result.get("commonality_analyses", {})
    if not isinstance(analyses, dict) or any(not isinstance(item, dict) for item in analyses.values()):
        raise AppError("COMMONALITY_DELIVERY_INVALID", "共同性分析結果不合法。")
    fields = ("analysis_contract", "status", "population_count", "qualifying_count", "comparison_count")
    checks = {aid: {key: item.get(key) for key in fields} for aid, item in analyses.items()}
    validate_delivery_checks(body, checks)
    return checks


def field_types(settings, contracts):
    roles = {"entity_column": settings.block_id, "group_column": settings.block_id,
             "outcome_group_column": settings.outcome_block_id, "value_column": settings.outcome_block_id}
    result = {}
    for role, bid in roles.items():
        contract = contracts.get(bid)
        if contract is None or contract.block_type.value not in {"fact", "snapshot_fact", "target_fact"}:
            raise AppError("COMMONALITY_SETTINGS_INCOMPATIBLE", "共同性設定必須引用可用的事實來源。", 409)
        result[role] = next((c.data_type for c in contract.columns if c.name == getattr(settings, role)), "")
    return result


def validate_saved_analyses(body, contracts, definitions):
    import re
    for item in definitions:
        page = body.get("pages", {}).get(item.page_id)
        current = field_types(item, contracts)
        if (page is None or (item.selected_component_id and item.selected_component_id not in page.get("visuals", {}))
                or not all(current.values()) or current != item.field_types
                or item.entity_column == item.group_column or item.outcome_group_column == item.value_column
                or current["group_column"] != current["outcome_group_column"]
                or not re.fullmatch(r"integer|int|int32|int64|float|float32|float64|double|number|numeric|decimal", current["value_column"], re.I)):
            raise AppError("COMMONALITY_SETTINGS_INCOMPATIBLE", "共同性設定的欄位型別、群體鍵或頁面引用已不相容，請更新或刪除設定。", 409)


def settings_command(body, kind, payload, contracts):
    import copy
    from uuid import uuid4
    from pydantic import ValidationError
    from .schemas import CommonalitySettings
    from .report_extensions import extensions, SavedCommonalityAnalysis
    action = kind.removesuffix("_commonality_analysis")
    expected = {"save": {"name", "settings", "page_id", "selected_component_id"},
                "update": {"analysis_id", "settings", "page_id", "selected_component_id"},
                "rename": {"analysis_id", "name"}, "delete": {"analysis_id"}}
    if action not in expected or set(payload) != expected[action]:
        raise AppError("INVALID_COMMONALITY_SETTINGS", "共同性設定命令欄位不完整或含額外欄位。")
    extra = extensions(body).model_dump()
    items = extra["commonality_analyses"]
    found = next((item for item in items if item["analysis_id"] == payload.get("analysis_id")), None)
    if action != "save" and found is None:
        raise AppError("COMMONALITY_SETTINGS_NOT_FOUND", "找不到共同性設定。", 404)
    if "name" in payload:
        name = payload["name"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise AppError("INVALID_COMMONALITY_SETTINGS", "共同性設定名稱須為 1 至 80 字。")
        name = name.strip()
        if any(item is not found and item["name"].casefold() == name.casefold() for item in items):
            raise AppError("DUPLICATE_COMMONALITY_SETTINGS", "已有相同名稱的共同性設定。")
    if action == "delete":
        items.remove(found)
    elif action == "rename":
        found["name"] = name
    else:
        if action == "save" and len(items) >= 30:
            raise AppError("COMMONALITY_SETTINGS_LIMIT", "每份報表最多保存 30 組共同性設定。")
        try:
            settings = CommonalitySettings.model_validate(payload["settings"])
            definition = SavedCommonalityAnalysis.model_validate({**settings.model_dump(),
                "analysis_id": found["analysis_id"] if found else "commonality_" + uuid4().hex,
                "name": found["name"] if found else name, "page_id": payload["page_id"],
                "selected_component_id": payload["selected_component_id"],
                "field_types": field_types(settings, contracts), "analysis_contract": ANALYSIS_CONTRACT})
        except (ValidationError, TypeError) as exc:
            raise AppError("INVALID_COMMONALITY_SETTINGS", "共同性設定包含無效參數。") from exc
        validate_saved_analyses(body, contracts, [definition])
        if found is None:
            items.append(definition.model_dump())
        else:
            found.update(definition.model_dump())
    result = copy.deepcopy(body)
    result["web_extensions"] = extra
    return result


def run_commonality(root, snapshot):
    from .core import load_contracts
    from .publications import check_execution_runtime
    from .drilling import validate_snapshot
    check_execution_runtime(root, snapshot)
    if snapshot.get("analysis_contract") != ANALYSIS_CONTRACT:
        raise AppError("COMMONALITY_INCOMPATIBLE", "共同性分析版本已變更，請重新執行。", 409)
    validate_snapshot(snapshot)
    return scan_snapshot(snapshot, load_contracts(root, snapshot["datasets"]))


def run_saved_analyses(snapshot, contracts):
    """Reuse one verified source set; restore each definition's structural scope."""
    from .report_extensions import extensions
    from .bookmarks import exploration_page
    definitions = extensions(snapshot["report"]).commonality_analyses
    validate_saved_analyses(snapshot["report"], contracts, definitions)
    active_page = exploration_page(snapshot["report"], snapshot)
    results = {}
    for item in definitions:
        page = snapshot["report"]["pages"][item.page_id]
        scoped = {**snapshot, **item.model_dump(), "exploration_page_id": item.page_id,
                  "filters": snapshot.get("filters", []) if item.page_id == active_page else [],
                  "drill_state": {vid: state for vid, state in snapshot.get("drill_state", {}).items() if vid in page["visuals"]}}
        results[item.analysis_id] = {**scan_snapshot(scoped, contracts), "analysis_id": item.analysis_id,
            "name": item.name, "page_id": item.page_id, "settings": item.model_dump()}
    return results


def scan_snapshot(snapshot, contracts):
    from ai4bi.blocks.datastore import materialize_dataframe
    from ai4bi.report.models import ExecutableReportSpec
    from .core import clean
    from .analysis_scope import exploration_context
    from .drilling import validate_snapshot, assistant_drill_executor, assistant_source_contracts
    from .report_extensions import report_executor

    if snapshot.get("analysis_contract") != ANALYSIS_CONTRACT:
        raise AppError("COMMONALITY_INCOMPATIBLE", "共同性分析版本已變更，請重新執行。", 409)
    validate_snapshot(snapshot)
    page, filters, serialized = exploration_context(snapshot, contracts, analysis="COMMONALITY")
    blocks = (snapshot["block_id"], snapshot["outcome_block_id"])
    fields = ((snapshot["entity_column"], snapshot["group_column"]),
              (snapshot["value_column"], snapshot["outcome_group_column"]))
    for bid, required in zip(blocks, fields):
        contract = contracts.get(bid)
        if (contract is None or contract.block_type.value not in {"fact", "snapshot_fact", "target_fact"}
                or set(required) - {column.name for column in contract.columns}):
            raise AppError("INVALID_COMMONALITY", "請選擇有效的事實來源及欄位。")
    selected = snapshot.get("selected_component_id")
    executor, contracts = report_executor(snapshot["report"], contracts, page_id=page, visual_id=selected)
    _, context = assistant_drill_executor(executor, snapshot["report"], contracts,
                                          selected, snapshot.get("drill_state", {}))
    if context and context["block_id"] not in blocks:
        raise AppError("INVALID_COMMONALITY_CONTEXT", "鑽取來源必須屬於共同性分析的兩個來源。")
    selected_filters = []
    if selected is not None:
        report = ExecutableReportSpec.from_dict(snapshot["report"])
        query = report.pages[page].visuals[selected].query
        selected_filters = executor._apply_active_filters(query, report.merged_filters()).filters
    scoped = assistant_source_contracts(executor, contracts, context, extra_filters=[*selected_filters, *filters])
    result = scan(materialize_dataframe(scoped[blocks[0]]), materialize_dataframe(scoped[blocks[1]]),
                  **{key: snapshot[key] for key in ("entity_column", "group_column", "outcome_group_column",
                     "value_column", "threshold", "aggregation", "comparison")})
    return clean({**result, "snapshot_id": snapshot["snapshot_id"], "revision": snapshot["revision"],
                  "execution_contract": snapshot["execution_contract"], "exploration_page_id": page,
                  "selected_component_id": selected, "drill_context": context,
                  "settings": {key: snapshot[key] for key in ("block_id", "outcome_block_id", "entity_column",
                      "group_column", "outcome_group_column", "value_column", "threshold", "aggregation", "comparison")},
                  "filters": serialized, "applied_filters": [f for f in serialized if f["block_id"] in blocks],
                  "selected_query_filters": [f for f in selected_filters if f.block_id in blocks],
                  "filter_bookmark_id": snapshot.get("filter_bookmark_id"),
                  "data_versions": {d["dataset_id"]: d["version"] for d in snapshot["datasets"]}})


def scan(detail, outcomes, *, entity_column, group_column, outcome_group_column,
         value_column, threshold, aggregation="mean", comparison="lt"):
    """Use one observed group population, without a many-to-many detail join.

    Outcome rows aggregate independently. Only groups with both a finite outcome
    and a non-null exposure enter the statistical population. Identifier types
    must agree: converting IDs to strings could merge distinct groups.
    """
    from ai4bi.analysis.crossfact import commonality

    def invalid(message):
        raise AppError("INVALID_COMMONALITY", message)

    if (entity_column == group_column or value_column == outcome_group_column
            or not detail.columns.is_unique or not outcomes.columns.is_unique
            or not {entity_column, group_column}.issubset(detail.columns)
            or not {outcome_group_column, value_column}.issubset(outcomes.columns)):
        invalid("共同性分析需要有效且不同的識別與數值欄位。")
    if aggregation not in {"mean", "sum"} or comparison not in {"lt", "lte", "gt", "gte"}:
        invalid("不支援的聚合或門檻運算。")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold):
        invalid("門檻必須是有限數字。")
    if not is_numeric_dtype(outcomes[value_column]) or is_bool_dtype(outcomes[value_column]):
        invalid("結果欄位必須是數字。")
    # Object columns can conceal mixed identifier types even when dtypes agree.
    def key_types(series):
        return {type(value) for value in series.dropna().tolist()}

    left_types, right_types = key_types(detail[group_column]), key_types(outcomes[outcome_group_column])
    if len(left_types) > 1 or len(right_types) > 1 or (left_types and right_types and left_types != right_types):
        invalid("兩個來源的群體識別型別必須一致，不能混用文字與數字。")
    raw_outcomes = outcomes[[outcome_group_column, value_column]].dropna()
    if not raw_outcomes[value_column].map(math.isfinite).all():
        invalid("結果資料含非有限數值。")
    measured = raw_outcomes.groupby(outcome_group_column, observed=True)[value_column].agg(aggregation)
    if not measured.map(math.isfinite).all():
        invalid("聚合結果含非有限數值。")
    exposures = detail[[group_column, entity_column]].dropna().drop_duplicates()
    # Use private names so an entity column named 'lift' cannot overwrite output.
    exposures = exposures.rename(columns={group_column: "group", entity_column: "entity"})
    observed = set(exposures["group"])
    measured_keys = set(measured.index)
    population = observed & measured_keys
    aligned = exposures[exposures["group"].isin(population)].copy()
    aligned["entity"] = aligned["entity"].astype(object)
    if aligned["entity"].nunique() > MAX_ENTITIES:
        raise AppError("COMMONALITY_LIMIT", "共同性分析最多支援 5,000 個實體，不截斷資料。")
    values = measured[measured.index.isin(population)]
    mask = {"lt": values.lt, "lte": values.le, "gt": values.gt, "gte": values.ge}[comparison](threshold)
    qualifying = set(values[mask].index)
    status = ("empty" if not population else "no_qualifying_groups" if not qualifying
              else "no_comparison_groups" if qualifying == population else "ready")
    table = commonality(aligned, "entity", "group", qualifying)
    rows = []
    for item in table.to_dict("records"):
        rows.append({"entity": item["entity"], "qualifying_count": item["涉及批數"],
                     "coverage_percent": item["涵蓋率%"], "lift": item["lift"],
                     "p_value": item.get("p_value") if status == "ready" else None})
    if status == "ready" and any(row["p_value"] is None for row in rows):
        raise AppError("COMMONALITY_STATISTICS_UNAVAILABLE", "統計檢定無法完成，請檢查運算環境。", 503)
    return {"analysis_contract": ANALYSIS_CONTRACT, "status": status,
            "population_count": len(population), "qualifying_count": len(qualifying),
            "comparison_count": len(population) - len(qualifying),
            "unmeasured_group_count": len(observed - measured_keys),
            "unexposed_group_count": len(measured_keys - observed),
            "excluded_detail_rows": len(detail) - len(detail[[group_column, entity_column]].dropna()),
            "excluded_outcome_rows": len(outcomes) - len(raw_outcomes),
            "rows": rows, "notice": "共同性代表關聯，不證明因果；p 值為單尾 Fisher 檢定，未校正多重比較。"}
