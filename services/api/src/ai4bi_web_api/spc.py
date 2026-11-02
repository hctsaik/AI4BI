"""Versioned adapter for the fixed core's cross-entity control-limit scan."""
from __future__ import annotations

import math

import pandas as pd

from .errors import AppError
from .analysis_scope import exploration_context


ANALYSIS_CONTRACT = "spc-entity-v2"
MAX_ENTITIES = 5000


def validate_saved_analyses(body, contracts, definitions):
    """Check immutable field signatures and structural scope without reading rows."""
    import re
    for item in definitions:
        page = body.get("pages", {}).get(item.page_id)
        if page is None or (item.selected_component_id and item.selected_component_id not in page.get("visuals", {})):
            raise AppError("SPC_SETTINGS_INCOMPATIBLE", "SPC 設定引用的頁面或圖表已不存在；請先更新或刪除設定。", 409)
        contract = contracts.get(item.block_id)
        columns = {c.name: c.data_type for c in contract.columns} if contract else {}
        if (contract is None or contract.block_type.value not in {"fact", "snapshot_fact", "target_fact"}
                or item.entity_column == item.value_column
                or columns.get(item.entity_column) != item.entity_type
                or columns.get(item.value_column) != item.value_type
                or not re.fullmatch(r"integer|int|int32|int64|float|float32|float64|double|number|numeric|decimal", item.value_type, re.I)):
            raise AppError("SPC_SETTINGS_INCOMPATIBLE", "SPC 資料來源或欄位型別已改變；請以目前欄位更新或刪除設定。", 409)


def settings_command(body, kind, payload, contracts):
    import copy
    from uuid import uuid4
    from pydantic import ValidationError
    from .schemas import SpcSettings
    from .report_extensions import extensions, SavedSpcAnalysis
    expected = {
        "save_spc_analysis": {"name", "settings", "page_id", "selected_component_id"},
        "update_spc_analysis": {"analysis_id", "settings", "page_id", "selected_component_id"},
        "rename_spc_analysis": {"analysis_id", "name"},
        "delete_spc_analysis": {"analysis_id"},
    }
    if kind not in expected or set(payload) != expected[kind]:
        raise AppError("INVALID_SPC_SETTINGS", "SPC 設定命令欄位不完整或含有額外欄位。")
    extra = extensions(body).model_dump()
    items = extra["spc_analyses"]
    found = next((item for item in items if item["analysis_id"] == payload.get("analysis_id")), None)
    if kind != "save_spc_analysis" and found is None:
        raise AppError("SPC_SETTINGS_NOT_FOUND", "找不到此 SPC 設定。", 404)
    if "name" in payload:
        name = payload["name"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise AppError("INVALID_SPC_SETTINGS", "SPC 設定名稱須為 1 至 80 字。")
        name = name.strip()
        if any(item is not found and item["name"].casefold() == name.casefold() for item in items):
            raise AppError("DUPLICATE_SPC_SETTINGS", "已有相同名稱的 SPC 設定。")
    if kind == "delete_spc_analysis":
        items.remove(found)
    elif kind == "rename_spc_analysis":
        found["name"] = name
    else:
        if kind == "save_spc_analysis" and len(items) >= 30:
            raise AppError("SPC_SETTINGS_LIMIT", "每份報表最多保存 30 組 SPC 設定。")
        try:
            settings = SpcSettings.model_validate(payload["settings"])
            contract = contracts.get(settings.block_id)
            columns = {c.name: c.data_type for c in contract.columns} if contract else {}
            definition = SavedSpcAnalysis.model_validate({**settings.model_dump(),
                "analysis_id": found["analysis_id"] if found else "spc_" + uuid4().hex,
                "name": found["name"] if found else name, "page_id": payload["page_id"],
                "selected_component_id": payload["selected_component_id"],
                "entity_type": columns.get(settings.entity_column, ""),
                "value_type": columns.get(settings.value_column, ""), "analysis_contract": ANALYSIS_CONTRACT})
        except (ValidationError, TypeError) as exc:
            raise AppError("INVALID_SPC_SETTINGS", "SPC 設定必須引用有效欄位、頁面與數值參數。") from exc
        validate_saved_analyses(body, contracts, [definition])
        if found is None:
            items.append(definition.model_dump())
        else:
            found.update(definition.model_dump())
    result = copy.deepcopy(body)
    result["web_extensions"] = extra
    return result


def scan(frame, entity, value, *, k=3.0, aggregation="mean"):
    """Calculate on the complete scoped population, never a preview page."""
    from ai4bi.analysis.spc import control_limit_outliers

    if (entity == value or entity not in frame or value not in frame
            or aggregation not in {"mean", "sum"} or isinstance(k, bool)
            or not isinstance(k, (int, float)) or not math.isfinite(k) or not 0 < k <= 10):
        raise AppError("INVALID_SPC", "請選擇不同的實體與數值欄位，並設定 0 到 10 之間的正數門檻。")
    if not pd.api.types.is_numeric_dtype(frame[value]) or pd.api.types.is_bool_dtype(frame[value]):
        raise AppError("INVALID_SPC", "SPC 數值欄位必須是數字。")
    valid = frame[[entity, value]].dropna()
    if not valid[value].map(math.isfinite).all():
        raise AppError("INVALID_SPC", "SPC 數值包含無限值，請先修復資料。")
    grouped = valid.groupby(entity, observed=True)[value].agg(aggregation)
    if len(grouped) > MAX_ENTITIES:
        raise AppError("SPC_ENTITY_LIMIT", "實體超過 5,000 個，請縮小篩選範圍後重試。")
    if not grouped.map(math.isfinite).all():
        raise AppError("INVALID_SPC", "SPC 聚合結果超出有限數值範圍。")
    # Core groups the raw scoped records; do not average an already aggregated
    # or truncated query result and accidentally change entity weighting.
    core_frame = valid.rename(columns={entity: "entity", value: "value"}).copy()
    core_frame["entity"] = core_frame["entity"].astype(object)
    outliers, limits = control_limit_outliers(core_frame, "entity", "value", k=k, agg=aggregation)
    outliers = outliers.rename(columns={"偏離": "direction", "離均(σ)": "z_score"})
    if limits and not all(math.isfinite(number) for number in limits.values()):
        raise AppError("INVALID_SPC", "SPC 統計結果超出有限數值範圍。")
    status = "empty" if len(grouped) == 0 else "insufficient_groups" if len(grouped) < 3 else "zero_variance" if not limits else "ready"
    return {"status": status, "analysis_contract": ANALYSIS_CONTRACT,
            "method": "cross_entity_population_sigma", "aggregation": aggregation, "k": k,
            "entity_column": entity, "value_column": value,
            "input_rows": len(frame), "used_rows": len(valid), "excluded_rows": len(frame)-len(valid),
            "entity_count": len(grouped), "limits": limits or None,
            "points": [{"entity": name, "value": number} for name, number in grouped.items()],
            "outliers": outliers,
            "notice": "跨實體聚合值的 μ±kσ 離群掃描；σ 使用母體標準差。不是時序管制圖，不提供 Cpk/Ppk 或連串規則判讀。"}


def run_spc(root, snapshot):
    from .core import load_contracts
    from .publications import check_execution_runtime
    check_execution_runtime(root, snapshot)
    if snapshot.get("analysis_contract") != ANALYSIS_CONTRACT:
        raise AppError("SPC_INCOMPATIBLE", "SPC 分析版本已變更，請重新執行。", 409)
    return scan_snapshot(snapshot, load_contracts(root, snapshot["datasets"]))


def run_saved_analyses(snapshot, contracts):
    """Reuse verified source contracts; each definition owns its structural scope."""
    from .report_extensions import extensions
    from .bookmarks import exploration_page
    definitions = extensions(snapshot["report"]).spc_analyses
    validate_saved_analyses(snapshot["report"], contracts, definitions)
    active_page = exploration_page(snapshot["report"], snapshot)
    results = {}
    for item in definitions:
        page = snapshot["report"]["pages"][item.page_id]
        scoped = {**snapshot, **item.model_dump(), "exploration_page_id": item.page_id,
                  "filters": snapshot.get("filters", []) if item.page_id == active_page else [],
                  "drill_state": {vid: value for vid, value in snapshot.get("drill_state", {}).items() if vid in page["visuals"]}}
        results[item.analysis_id] = {**scan_snapshot(scoped, contracts),
            "analysis_id": item.analysis_id, "name": item.name, "page_id": item.page_id,
            "settings": item.model_dump()}
    return results


def scan_snapshot(snapshot, contracts):
    from ai4bi.blocks.datastore import materialize_dataframe
    from ai4bi.report.models import ExecutableReportSpec
    from .core import clean
    from .drilling import assistant_drill_executor, assistant_source_contracts, validate_snapshot
    from .report_extensions import report_executor

    if snapshot.get("analysis_contract") != ANALYSIS_CONTRACT:
        raise AppError("SPC_INCOMPATIBLE", "SPC 分析版本已變更，請重新執行。", 409)
    selected = snapshot.get("selected_component_id")
    validate_snapshot(snapshot)
    page_id, filters, serialized_filters = exploration_context(snapshot, contracts)
    bid = snapshot["block_id"]
    contract = contracts.get(bid)
    if contract is None or contract.block_type.value not in {"fact", "snapshot_fact", "target_fact"}:
        raise AppError("INVALID_SPC", "SPC 必須選擇可用的事實資料來源。")
    columns = {column.name for column in contract.columns}
    if {snapshot["entity_column"], snapshot["value_column"]} - columns:
        raise AppError("INVALID_SPC", "SPC 欄位不在選取的資料來源中。")
    executor, contracts = report_executor(snapshot["report"], contracts,
        page_id=page_id, visual_id=selected)
    _, context = assistant_drill_executor(executor, snapshot["report"], contracts,
                                          selected, snapshot.get("drill_state", {}))
    if context and context["block_id"] != bid:
        raise AppError("INVALID_SPC_CONTEXT", "SPC 資料來源必須與鑽取路徑一致。")
    selected_filters = []
    if selected is not None:
        report = ExecutableReportSpec.from_dict(snapshot["report"])
        query = report.pages[page_id].visuals[selected].query
        selected_filters = executor._apply_active_filters(query, report.merged_filters()).filters
    scoped = assistant_source_contracts(executor, contracts, context, extra_filters=[*selected_filters, *filters])
    result = scan(materialize_dataframe(scoped[bid]), snapshot["entity_column"], snapshot["value_column"],
                  k=snapshot["k"], aggregation=snapshot["aggregation"])
    return clean({**result, "block_id": bid, "snapshot_id": snapshot["snapshot_id"],
        "revision": snapshot["revision"], "execution_contract": snapshot["execution_contract"],
        "selected_component_id": selected, "drill_context": context,
        "exploration_page_id": page_id, "filters": serialized_filters,
        "applied_filters": [f for f in serialized_filters if f["block_id"] == bid],
        "selected_query_filters": [f for f in selected_filters if f.block_id == bid],
        "filter_bookmark_id": snapshot.get("filter_bookmark_id"),
        "data_versions": {d["dataset_id"]: d["version"] for d in snapshot["datasets"]}})
