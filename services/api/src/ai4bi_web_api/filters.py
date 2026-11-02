"""Typed persistent predicates and a thin adapter over the governed executor."""
from __future__ import annotations

import copy
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from typing import Literal
from uuid import uuid4
from pydantic import ConfigDict, Field, FiniteFloat, TypeAdapter, model_validator
from ai4bi.analysis.executor import Executor, _build_filter_clause, _require_column
from ai4bi.query_spec import FilterSpec, FilterOperator
from .bookmarks import ExplorationFilter
from .errors import AppError
from .schemas import StrictModel


class AggregateFilter(StrictModel):
    model_config = ConfigDict(extra="forbid",strict=True)
    block_id: str = Field(min_length=1,max_length=100)
    metric_name: str = Field(min_length=1,max_length=100)
    operator: Literal["eq","neq","gt","gte","lt","lte","between"]
    value: FiniteFloat | list[FiniteFloat]

    @model_validator(mode="after")
    def shape(self):
        if self.operator == "between":
            if not isinstance(self.value,list) or len(self.value)!=2 or self.value[0]>self.value[1]:
                raise ValueError("聚合區間須為由小至大的兩個數值。")
        elif isinstance(self.value,list):
            raise ValueError("聚合比較須使用單一數值。")
        return self


def validate_aggregate_filters(body):
    """Reject ignored, malformed or ambiguous HAVING before core deserialization."""
    for page in body.get("pages",{}).values():
        for visual in page.get("visuals",{}).values():
            query=visual["query"]
            raw=query.get("having",[])
            if not isinstance(raw,list) or len(raw)>50:
                raise AppError("INVALID_HAVING", "每張圖最多 50 個聚合後篩選。")
            try:
                items=[AggregateFilter.model_validate(item) for item in raw]
            except ValueError as exc:
                raise AppError("INVALID_HAVING", "聚合後篩選須使用有限數值比較或有效區間。") from exc
            for item in items:
                if sum(m["block_id"]==item.block_id and m["metric_name"]==item.metric_name for m in query.get("metrics",[]))!=1:
                    raise AppError("INVALID_HAVING_METRIC", "聚合後篩選須引用此圖唯一選取的指標；請先修正篩選再移除或更換指標。")


class FilterScope(StrictModel):
    filter_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    scope: Literal["report","page","visual"]
    page_id: str | None = Field(default=None,min_length=1,max_length=100)
    visual_id: str | None = Field(default=None,min_length=1,max_length=100)

    @model_validator(mode="after")
    def valid_scope(self):
        if (self.scope == "report" and (self.page_id is not None or self.visual_id is not None)
                or self.scope == "page" and (self.page_id is None or self.visual_id is not None)
                or self.scope == "visual" and (self.page_id is None or self.visual_id is None)):
            raise ValueError("篩選範圍與頁面／圖表識別不符。")
        return self


class TypedPredicate(ExplorationFilter):
    source_visual_id: None = None
    data_type: str = Field(min_length=1,max_length=100)


class PersistentFilter(TypedPredicate, FilterScope):
    pass


class FilterExpression(StrictModel):
    operator: Literal["and", "or"]
    children: list[TypedPredicate | FilterExpression] = Field(min_length=2,max_length=100)


def predicates(expression):
    if isinstance(expression, FilterExpression):
        return [leaf for child in expression.children for leaf in predicates(child)]
    return [expression]


class PersistentFilterGroup(FilterScope):
    block_id: str = Field(min_length=1,max_length=100)
    expression: FilterExpression

    @model_validator(mode="after")
    def bounded_tree(self):
        def depth(node):
            return 1 + max(depth(c) for c in node.children) if isinstance(node,FilterExpression) else 0
        leaves = predicates(self.expression)
        if depth(self.expression)>4 or len(leaves)>100:
            raise ValueError("篩選群組最多四層、100 個條件。")
        if any(leaf.block_id != self.block_id for leaf in leaves):
            raise ValueError("群組條件必須使用同一資料來源。")
        return self


PersistentCondition = PersistentFilter | PersistentFilterGroup


def parse_condition(raw):
    return TypeAdapter(PersistentCondition).validate_python(raw)


def condition_leaves(item):
    return predicates(item.expression) if isinstance(item,PersistentFilterGroup) else [item]


def expression_sql(expression,params,contracts=None):
    if isinstance(expression,FilterExpression):
        return "(" + (" AND " if expression.operator == "and" else " OR ").join(
            expression_sql(child,params,contracts) for child in expression.children) + ")"
    if contracts is not None:
        _require_column(contracts,expression.block_id,expression.column_name)
    return _build_filter_clause(FilterSpec(expression.block_id,expression.column_name,
                                          FilterOperator(expression.operator),expression.value),params)


class GroupedExecutor(Executor):
    """Pinned-core extension: add grouped WHERE predicates alongside existing RLS."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._web_groups = ContextVar("web_filter_groups",default=())

    @contextmanager
    def filter_groups(self,groups):
        token = self._web_groups.set(tuple(groups))
        try:
            yield
        finally:
            self._web_groups.reset(token)

    def _rls_predicates(self,spec,contracts,params):
        return super()._rls_predicates(spec,contracts,params) + [
            expression_sql(group.expression,params,contracts) for group in self._web_groups.get()]

    def run_with_metadata(self,*args,**kwargs):
        frame,metadata = super().run_with_metadata(*args,**kwargs)
        metadata.filters_applied.extend("group " + group.filter_id + ": " + expression_sql(group.expression,[])
                                       for group in self._web_groups.get())
        return frame,metadata


def validate_values(item):
    if item.operator in {"is_null","is_not_null"}:
        return
    values = item.value if isinstance(item.value,list) else [item.value]
    dtype = item.data_type.lower()
    for value in values:
        if dtype in {"integer","int","int64","int32"}:
            valid = isinstance(value,(int,float)) and not isinstance(value,bool) and int(value) == value
        elif dtype in {"float","number","numeric","double","decimal"}:
            valid = isinstance(value,(int,float)) and not isinstance(value,bool)
        elif dtype in {"boolean","bool"}:
            valid = isinstance(value,bool) and item.operator in {"eq","neq","in","not_in"}
        elif dtype in {"date","timestamp","datetime"}:
            try:
                (date.fromisoformat if dtype == "date" else datetime.fromisoformat)(value)
                valid = item.operator != "like"
            except (ValueError,TypeError):
                valid = False
        else:
            valid = isinstance(value,str)
        if not valid or item.operator == "like" and dtype not in {"string","str","text","varchar","category"}:
            raise AppError("FILTER_TYPE_MISMATCH", "篩選值或運算子不符合欄位型別。")


def validate_references(body,contracts,items):
    for item in items:
        contract = contracts.get(item.block_id)
        for leaf in condition_leaves(item):
            column = next((c for c in contract.columns if c.name == leaf.column_name),None) if contract else None
            if column is None or column.data_type != leaf.data_type:
                raise AppError("FILTER_FIELD_CHANGED", "持久篩選的來源、欄位或型別已變更，請先修正篩選。",409)
            validate_values(leaf)
        pages = body["pages"] if item.scope == "report" else {item.page_id:body["pages"].get(item.page_id)}
        targets = []
        for page in pages.values():
            if page is None:
                raise AppError("INVALID_FILTER_SCOPE", "篩選頁面不存在。")
            targets.extend(page["visuals"].values() if item.scope != "visual" else [page["visuals"].get(item.visual_id)])
        if any(v is None for v in targets) or not any(any(b["block_id"] == item.block_id for b in v["query"]["block_refs"]) for v in targets):
            raise AppError("INVALID_FILTER_SCOPE", "篩選範圍內沒有使用此來源的圖表。")


class ScopedExecutor:
    def __init__(self,executor,body,items,page_id=None,visual_id=None):
        self.executor,self.body,self.items,self.page_id,self.visual_id = executor,body,items,page_id,visual_id

    def __getattr__(self,name):
        return getattr(self.executor,name)

    def applicable(self,spec,page_id=None,visual_id=None):
        if page_id is None:
            matches = [(pid,vid) for pid,page in self.body["pages"].items() for vid,v in page["visuals"].items() if v["query"]["spec_id"] == spec.spec_id]
            if len(matches) == 1:
                page_id,visual_id = matches[0]
            else:
                page_id,visual_id = self.page_id,self.visual_id
        for item in self.items:
            if item.block_id not in spec.all_block_ids:
                continue
            if item.scope != "report" and item.page_id != page_id:
                continue
            if item.scope == "visual" and item.visual_id != visual_id:
                continue
            yield item

    def prepare(self,spec,page_id=None,visual_id=None):
        query = copy.deepcopy(spec)
        for item in self.applicable(spec,page_id,visual_id):
            if isinstance(item,PersistentFilter):
                query.filters.append(FilterSpec(item.block_id,item.column_name,FilterOperator(item.operator),item.value))
        return query

    def run(self,spec,*args,page_id=None,visual_id=None,**kwargs):
        groups = [item for item in self.applicable(spec,page_id,visual_id) if isinstance(item,PersistentFilterGroup)]
        if not groups:
            return self.executor.run(self.prepare(spec,page_id,visual_id),*args,**kwargs)
        with self.executor.filter_groups(groups):
            return self.executor.run(self.prepare(spec,page_id,visual_id),*args,**kwargs)

    def run_with_metadata(self,spec,*args,page_id=None,visual_id=None,**kwargs):
        groups = [item for item in self.applicable(spec,page_id,visual_id) if isinstance(item,PersistentFilterGroup)]
        if not groups:
            return self.executor.run_with_metadata(self.prepare(spec,page_id,visual_id),*args,**kwargs)
        with self.executor.filter_groups(groups):
            return self.executor.run_with_metadata(self.prepare(spec,page_id,visual_id),*args,**kwargs)


def prune_removed_filters(body,source):
    extra = body.get("web_extensions",{})
    def removed(item):
        pid,vid = item.get("page_id"),item.get("visual_id")
        if pid in source["pages"] and pid not in body["pages"]:
            return True
        return bool(pid in source["pages"] and pid in body["pages"] and vid in source["pages"][pid]["visuals"] and vid not in body["pages"][pid]["visuals"])
    if "persistent_filters" in extra:
        extra["persistent_filters"] = [f for f in extra["persistent_filters"] if not removed(f)]
    return body


def filter_command(body,kind,payload,contracts):
    from .report_extensions import extensions
    expected = {"filter"} if kind == "add_filter" else {"filter_id","filter"} if kind == "update_filter" else {"filter_id"}
    if set(payload) != expected:
        raise AppError("INVALID_FILTER", "篩選命令欄位不完整或含額外欄位。")
    extra = extensions(body).model_dump()
    items = extra["persistent_filters"]
    found = next((f for f in items if f["filter_id"] == payload.get("filter_id")),None)
    if kind != "add_filter" and found is None:
        raise AppError("FILTER_NOT_FOUND", "找不到此篩選。",404)
    if kind == "delete_filter":
        items.remove(found)
    else:
        raw = payload["filter"]
        allowed = {"scope","page_id","visual_id","block_id","column_name","operator","value","expression"}
        if not isinstance(raw,dict) or set(raw) - allowed:
            raise AppError("INVALID_FILTER", "篩選格式不合法，不接受客戶端指定型別或識別碼。")
        contract = contracts.get(raw.get("block_id")) if isinstance(raw.get("block_id"),str) else None
        def capture(node,depth=0):
            if not isinstance(node,dict) or depth>4:
                raise AppError("INVALID_FILTER", "篩選群組格式或深度不合法。")
            if node.get("operator") in ("and","or"):
                if set(node)!={"operator","children"} or not isinstance(node["children"],list) or not 2<=len(node["children"])<=100:
                    raise AppError("INVALID_FILTER", "群組須包含 2 至 100 個條件。")
                return {"operator":node["operator"],"children":[capture(child,depth+1) for child in node["children"]]}
            if set(node)-{"block_id","column_name","operator","value"} or node.get("block_id")!=raw.get("block_id"):
                raise AppError("INVALID_FILTER", "條件欄位不合法或來源不一致。")
            column = next((c for c in contract.columns if c.name==node.get("column_name")),None) if contract else None
            if column is None:
                raise AppError("FILTER_FIELD_CHANGED", "找不到篩選欄位。")
            return {**node,"data_type":column.data_type}
        try:
            typed = ({**raw,"expression":capture(raw["expression"])} if "expression" in raw else
                     {**raw,**capture({k:v for k,v in raw.items() if k in {"block_id","column_name","operator","value"}})})
            item = parse_condition({**typed,"filter_id":found["filter_id"] if found else "filter_"+uuid4().hex})
        except ValueError as exc:
            raise AppError("INVALID_FILTER", "篩選值、運算子或作用範圍不合法。") from exc
        validate_references(body,contracts,[item])
        if found is not None:
            items[items.index(found)] = item.model_dump()
        else:
            if len(items) >= 100:
                raise AppError("FILTER_LIMIT", "每份報表最多 100 個持久篩選。")
            items.append(item.model_dump())
        if sum(len(condition_leaves(parse_condition(f))) for f in items)>100:
            raise AppError("FILTER_LIMIT", "每份報表最多 100 個篩選條件，群組內條件也計入。")
    result = copy.deepcopy(body)
    result["web_extensions"] = extra
    return result
