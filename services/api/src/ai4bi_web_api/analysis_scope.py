"""Shared validation of page, drill and transient filters for domain analyses."""
from .errors import AppError


def exploration_context(snapshot, contracts, *, analysis="SPC"):
    from ai4bi.report.models import ExecutableReportSpec
    from ai4bi.query_spec import FilterSpec, FilterOperator
    from .bookmarks import ExplorationFilter, exploration_page
    from .drilling import apply_drill
    from .filters import TypedPredicate, validate_values

    body = snapshot["report"]
    selected = snapshot.get("selected_component_id")
    pages = body["pages"]
    matches = [pid for pid, page in pages.items() if selected in page["visuals"]]
    page_id = exploration_page(body, snapshot)
    if page_id is None:
        page_id = matches[0] if len(matches) == 1 else next(iter(pages)) if len(pages) == 1 else None
    if selected is not None and (len(matches) != 1 or page_id != matches[0]):
        raise AppError(f"INVALID_{analysis}_CONTEXT", f"{analysis} 選取圖表必須位於目前探索頁面。")
    states = snapshot.get("drill_state", {})
    if states and (page_id is None or set(states) - set(pages[page_id]["visuals"])):
        raise AppError(f"INVALID_{analysis}_CONTEXT", f"{analysis} 鑽取路徑必須位於目前探索頁面。")
    report = ExecutableReportSpec.from_dict(body)
    queries = {vid: apply_drill(v.query, v.visualization, contracts, states.get(vid))[0]
               for vid, v in report.pages[page_id].visuals.items()} if page_id else {}
    filters, serialized = [], []
    for raw in snapshot.get("filters", []):
        try:
            predicate = ExplorationFilter.model_validate(raw)
        except ValueError as exc:
            raise AppError(f"INVALID_{analysis}_FILTER", f"{analysis} 探索篩選格式不合法。") from exc
        contract = contracts.get(predicate.block_id)
        column = next((c for c in contract.columns if c.name == predicate.column_name), None) if contract else None
        if column is None or not any(predicate.block_id in q.all_block_ids for q in queries.values()):
            raise AppError(f"INVALID_{analysis}_FILTER", f"{analysis} 篩選來源或欄位不在目前探索頁面。")
        if predicate.source_visual_id is not None:
            source = queries.get(predicate.source_visual_id)
            if source is None or not any(d.block_id == predicate.block_id and d.column_name == predicate.column_name
                                        and not d.truncate_date_to for d in source.dimensions):
                raise AppError(f"INVALID_{analysis}_FILTER", f"{analysis} 跨圖篩選來源或維度已變更。")
        typed = TypedPredicate.model_validate({**predicate.model_dump(exclude={"source_visual_id"}), "data_type": column.data_type})
        validate_values(typed)
        filters.append(FilterSpec(predicate.block_id, predicate.column_name, FilterOperator(predicate.operator), predicate.value))
        serialized.append(predicate.model_dump())
    return page_id, filters, serialized
