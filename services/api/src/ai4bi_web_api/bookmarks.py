"""Saved exploration views with typed predicates and explicit stale references."""
from __future__ import annotations

import copy
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import ConfigDict, Field, FiniteFloat, StrictBool, StrictInt, StringConstraints, model_validator
from ai4bi.query_spec import FilterOperator, FilterSpec
from ai4bi.report.models import ExecutableReportSpec
from .schemas import StrictModel
from .errors import AppError

Scalar = StrictBool | StrictInt | FiniteFloat | Annotated[str, StringConstraints(max_length=2000)]


def exploration_page(body: dict, options: dict):
    """Resolve one page for transient predicates; never silently filter other pages."""
    pages = body["pages"]
    explicit = options.get("exploration_page_id")
    if explicit is not None and (not isinstance(explicit,str) or explicit not in pages):
        raise AppError("INVALID_EXPLORATION_PAGE", "探索頁面已不存在。", 409)
    filters = options.get("filters", [])
    if not filters:
        return explicit
    sources = set()
    for predicate in filters:
        source = predicate.get("source_visual_id")
        if source is None:
            continue
        if not isinstance(source,str):
            raise AppError("INVALID_EXPLORATION_PAGE", "探索來源圖表識別碼不合法。")
        matches = [pid for pid,page in pages.items() if source in page["visuals"]]
        if len(matches) != 1:
            raise AppError("INVALID_EXPLORATION_PAGE", "探索來源圖表已不存在或識別不唯一。", 409)
        sources.add(matches[0])
    if explicit is not None:
        if sources - {explicit}:
            raise AppError("INVALID_EXPLORATION_PAGE", "探索篩選來源必須位於指定頁面。")
        return explicit
    if len(sources) == 1:
        return next(iter(sources))
    if not sources:
        wanted = options.get("visual_ids", [])
        candidates = {pid for pid,page in pages.items() if any(vid in page["visuals"] for vid in wanted)} if wanted else set(pages)
        if len(candidates) == 1:
            return next(iter(candidates))
    raise AppError("EXPLORATION_PAGE_REQUIRED", "多頁報表的探索篩選必須指定單一作用頁面。")


class ExplorationFilter(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_visual_id: str | None = Field(default=None, min_length=1, max_length=100)
    block_id: str = Field(min_length=1, max_length=100)
    column_name: str = Field(min_length=1, max_length=200)
    operator: Literal["eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in", "between", "like", "is_null", "is_not_null"]
    value: Scalar | list[Scalar] | None = None

    @model_validator(mode="after")
    def shape(self):
        if self.operator in {"is_null", "is_not_null"}:
            valid = self.value is None
        elif self.operator in {"in", "not_in", "between"}:
            valid = isinstance(self.value, list) and 1 <= len(self.value) <= 100
            if self.operator == "between":
                valid = valid and len(self.value) == 2
        elif self.operator == "like":
            valid = isinstance(self.value, str)
        else:
            valid = self.value is not None and not isinstance(self.value, list)
        if not valid:
            raise ValueError("篩選運算子與值的形狀不相符。")
        return self


class ExplorationView(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    page_id: str = Field(min_length=1, max_length=100)
    selected_visual_id: str | None = Field(default=None, min_length=1, max_length=100)
    filters: list[ExplorationFilter] = Field(default_factory=list, max_length=50)
    filter_bookmark_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$")
    drill_state: dict[str, dict] = Field(default_factory=dict, max_length=100)


class FieldSignature(StrictModel):
    block_id: str = Field(min_length=1, max_length=100)
    column_name: str = Field(min_length=1, max_length=200)
    data_type: str = Field(min_length=1, max_length=100)


class Bookmark(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    bookmark_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    name: str = Field(min_length=1, max_length=80)
    view: ExplorationView
    fields: list[FieldSignature] = Field(max_length=50)
    persistent_filters: list[dict] | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def consistent(self):
        from .drilling import parse_states
        parse_states(self.view.drill_state)
        if self.view.filter_bookmark_id is not None:
            raise ValueError("保存的書籤不可間接引用其他書籤條件。")
        if self.persistent_filters is not None:
            from .filters import parse_condition, condition_leaves
            parsed = [parse_condition(f) for f in self.persistent_filters]
            if sum(len(condition_leaves(f)) for f in parsed)>100:
                raise ValueError("書籤篩選條件超過上限。")
            if len({f.filter_id for f in parsed}) != len(parsed):
                raise ValueError("書籤持久篩選識別碼重複。")
        if not self.name.strip() or self.name != self.name.strip():
            raise ValueError("書籤名稱不得空白或含頭尾空白。")
        required = {(f.block_id, f.column_name) for f in self.view.filters}
        supplied = {(f.block_id, f.column_name) for f in self.fields}
        if required != supplied or len(supplied) != len(self.fields):
            raise ValueError("書籤欄位簽章不完整或重複。")
        return self


def validate_view(body: dict, view: ExplorationView, contracts: dict, fields=None, *,
                  execution_loader=None, validation_cache=None, validation_context=None):
    """Check references before running the exact same core predicates as a query."""
    from .report_extensions import report_executor, extensions
    def reject(message):
        raise AppError("BOOKMARK_INCOMPATIBLE", message + " 請以目前檢視更新書籤。", 409)
    page = body["pages"].get(view.page_id)
    if page is None:
        reject("書籤頁面已不存在。")
    if view.selected_visual_id and view.selected_visual_id not in page["visuals"]:
        reject("書籤選取的圖表已不存在。")
    signatures = {}
    report = ExecutableReportSpec.from_dict(body)
    from .drilling import parse_states, apply_drill
    states = parse_states(view.drill_state)
    visuals = report.pages[view.page_id].visuals
    if set(states) - set(visuals):
        reject("書籤鑽取圖表已不存在或位於其他頁面。")
    queries = {vid:apply_drill(visual.query,visual.visualization,contracts,states.get(vid))[0] for vid,visual in visuals.items()}
    for predicate in view.filters:
        contract = contracts.get(predicate.block_id)
        column = next((c for c in contract.columns if c.name == predicate.column_name), None) if contract else None
        if column is None:
            reject("書籤資料來源或欄位已不存在。")
        signatures[(predicate.block_id,predicate.column_name)] = {"block_id":predicate.block_id,"column_name":predicate.column_name,"data_type":column.data_type}
        if not any(predicate.block_id in q.all_block_ids for q in queries.values()):
            reject("此頁已沒有使用書籤資料來源的圖表。")
        if predicate.source_visual_id:
            source = queries.get(predicate.source_visual_id)
            if source is None or not any(d.block_id == predicate.block_id and d.column_name == predicate.column_name and not d.truncate_date_to for d in source.dimensions):
                reject("書籤的來源圖表或維度已變更。")
    result = [signatures[key] for key in sorted(signatures)]
    if fields is not None and sorted(fields, key=lambda f:(f["block_id"],f["column_name"])) != result:
        reject("書籤欄位型別已變更。")
    # Always validate current references, including captured persistent filters.
    report_executor(body, contracts)
    def check():
        executor, _ = report_executor(body, execution_loader() if execution_loader else contracts)
        try:
            for vid, query in queries.items():
                effective_query = copy.deepcopy(query)
                for predicate in view.filters:
                    if predicate.source_visual_id != vid and predicate.block_id in effective_query.all_block_ids:
                        effective_query.filters.append(FilterSpec(predicate.block_id,predicate.column_name,FilterOperator(predicate.operator),predicate.value))
                executor.run(effective_query, active_filters=report.merged_filters(),page_id=view.page_id,visual_id=vid)
        except Exception as exc:
            raise AppError("BOOKMARK_INCOMPATIBLE", "書籤篩選無法通過目前核心查詢驗證；原檢視保持不變。", 409) from exc
    if validation_cache is None or validation_context is None:
        check()
    else:
        from .core import validation_digest
        proof_body = copy.deepcopy(body)
        # Saved bookmark names/IDs do not affect the already resolved conditions.
        proof_body["web_extensions"] = extensions(body).model_dump(exclude={"bookmarks"})
        proof_view = view.model_dump(exclude={"filter_bookmark_id"})
        validation_cache.run(validation_digest({"format":"bookmark-view-v1", "context":validation_context,
                                               "report":proof_body, "view":proof_view}), check)
    return result


def bookmark_command(body: dict, kind: str, payload: dict, contracts: dict, **validation_options):
    from .report_extensions import extensions
    expected = {"name","view"} if kind == "save_bookmark" else {"bookmark_id","view"} if kind == "update_bookmark" else {"bookmark_id","name"} if kind == "rename_bookmark" else {"bookmark_id"}
    if set(payload) != expected:
        raise AppError("INVALID_BOOKMARK", "書籤命令欄位不完整或含有額外欄位。")
    extra = extensions(body).model_dump()
    items = extra["bookmarks"]
    item = next((item for item in items if item["bookmark_id"] == payload.get("bookmark_id")), None)
    if kind != "save_bookmark" and item is None:
        raise AppError("BOOKMARK_NOT_FOUND", "找不到此書籤。", 404)
    if kind in {"save_bookmark","rename_bookmark"}:
        name = payload["name"]
        if not isinstance(name,str) or not 1 <= len(name.strip()) <= 80:
            raise AppError("INVALID_BOOKMARK", "書籤名稱須為 1 至 80 字。")
        name = name.strip()
        if any(other is not item and other["name"].casefold() == name.casefold() for other in items):
            raise AppError("DUPLICATE_BOOKMARK", "已有相同名稱的書籤，請使用更新或其他名稱。")
    if kind in {"save_bookmark","update_bookmark"}:
        try:
            view = ExplorationView.model_validate(payload["view"])
        except ValueError as exc:
            raise AppError("INVALID_BOOKMARK", "書籤頁面或篩選格式不合法。") from exc
        effective = bookmark_filter_report(body, view.filter_bookmark_id)
        fields = validate_view(effective,view,contracts,**validation_options)
        captured = copy.deepcopy(extensions(effective).model_dump()["persistent_filters"])
        view.filter_bookmark_id = None
    if kind == "save_bookmark":
        if len(items) >= 30:
            raise AppError("BOOKMARK_LIMIT", "每份報表最多保存 30 個探索書籤。")
        items.append({"bookmark_id":"bookmark_"+uuid4().hex,"name":name,"view":view.model_dump(),"fields":fields,"persistent_filters":captured})
    elif kind == "update_bookmark":
        item.update(view=view.model_dump(),fields=fields,persistent_filters=captured)
    elif kind == "rename_bookmark":
        item["name"] = name
    elif kind == "delete_bookmark":
        items.remove(item)
    else:
        raise AppError("INVALID_BOOKMARK", "不支援的書籤操作。")
    result = copy.deepcopy(body)
    result["web_extensions"] = extra
    return result


def resolve_bookmark(body: dict, bookmark_id: str, contracts: dict, **validation_options):
    from .report_extensions import extensions
    item = next((item for item in extensions(body).bookmarks if item.bookmark_id == bookmark_id), None)
    if item is None:
        raise AppError("BOOKMARK_NOT_FOUND", "找不到此書籤。", 404)
    effective = bookmark_filter_report(body, bookmark_id)
    validate_view(effective,item.view,contracts,[field.model_dump() for field in item.fields],**validation_options)
    return {**item.view.model_dump(), "filter_bookmark_id":bookmark_id if item.persistent_filters is not None else None}


def bookmark_filter_report(body: dict, bookmark_id: str | None):
    """Resolve server-owned conditions before snapshot hashing; never mutate the source."""
    if bookmark_id is None:
        return body
    from .report_extensions import extensions
    item = next((b for b in extensions(body).bookmarks if b.bookmark_id == bookmark_id), None)
    if item is None:
        raise AppError("BOOKMARK_NOT_FOUND", "找不到此書籤。", 404)
    if item.persistent_filters is None:
        return body
    result = copy.deepcopy(body)
    result["web_extensions"]["persistent_filters"] = copy.deepcopy(item.persistent_filters)
    return result
