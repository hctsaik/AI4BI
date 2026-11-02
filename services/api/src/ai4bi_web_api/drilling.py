"""Typed, per-visual drill paths; never import the Streamlit state adapter."""
from __future__ import annotations

import copy
from pydantic import ConfigDict, Field
from ai4bi.query_spec import DimensionRef, FilterSpec, FilterOperator, SortSpec, SortDirection
from .bookmarks import Scalar
from .schemas import StrictModel
from .errors import AppError


class DrillStep(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    column: str = Field(min_length=1, max_length=200)
    value: Scalar | None


class DrillState(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    block_id: str = Field(min_length=1, max_length=100)
    hierarchy: list[str] = Field(min_length=2, max_length=10)
    field_types: list[str] = Field(min_length=2, max_length=10)
    path: list[DrillStep] = Field(default_factory=list, max_length=9)


def parse_states(states):
    if not isinstance(states,dict) or len(states)>100 or any(not isinstance(k,str) or not 1<=len(k)<=100 for k in states):
        raise AppError("INVALID_DRILL", "鑽取狀態格式不合法。")
    try:
        return {key:DrillState.model_validate(value).model_dump() for key,value in states.items()}
    except ValueError as exc:
        raise AppError("INVALID_DRILL", "鑽取路徑或值格式不合法。") from exc


def configuration(query, visualization, contracts):
    raw = visualization.extra.get("drill_hierarchy", [])
    if raw == [] or raw is None:
        return None
    if (not isinstance(raw,list) or not 2<=len(raw)<=10 or any(not isinstance(c,str) or not c or len(c)>200 for c in raw)
            or len(set(raw))!=len(raw) or not query.metrics or not query.block_refs):
        raise AppError("INVALID_DRILL", "鑽取須有指標及 2 至 10 個不重複欄位。")
    block = query.primary_block_id
    contract = contracts.get(block)
    columns = {c.name:c.data_type for c in contract.columns} if contract else {}
    if any(c not in columns for c in raw):
        raise AppError("DRILL_INCOMPATIBLE", "鑽取資料來源或欄位已不存在。",409)
    return {"block_id":block,"hierarchy":raw,"field_types":[columns[c] for c in raw],"path":[]}


def apply_drill(query, visualization, contracts, state=None):
    from .filters import PersistentFilter, validate_values
    config = configuration(query,visualization,contracts)
    if config is None:
        if state is not None:
            raise AppError("DRILL_INCOMPATIBLE", "圖表已停用鑽取，請重設鑽取狀態。",409)
        return copy.deepcopy(query), None
    selected = DrillState.model_validate(state or config)
    if any(getattr(selected,key)!=config[key] for key in ("block_id","hierarchy","field_types")) or len(selected.path)>=len(selected.hierarchy):
        raise AppError("DRILL_INCOMPATIBLE", "鑽取層級或欄位型別已變更，請重設路徑。",409)
    result = copy.deepcopy(query)
    for index,step in enumerate(selected.path):
        if step.column != selected.hierarchy[index]:
            raise AppError("DRILL_INCOMPATIBLE", "鑽取路徑必須依層級順序。",409)
        op = "is_null" if step.value is None else "eq"
        predicate = PersistentFilter(filter_id="drill",scope="report",block_id=selected.block_id,
            column_name=step.column,data_type=selected.field_types[index],operator=op,value=step.value)
        validate_values(predicate)
        result.filters.append(FilterSpec(selected.block_id,step.column,FilterOperator(op),step.value))
    column = selected.hierarchy[len(selected.path)]
    result.dimensions = [DimensionRef(selected.block_id,column,column)]
    result.sort = [SortSpec(query.metrics[0].alias or query.metrics[0].metric_name,SortDirection.desc)]
    return result, selected.model_dump()


def validate_snapshot(snapshot):
    """Check identity and value types using captured metadata before accepting a job."""
    from ai4bi.blocks.contracts import DataBlockContract
    from ai4bi.report.models import ExecutableReportSpec
    states = parse_states(snapshot.get("drill_state",{}))
    if not states:
        return
    report = ExecutableReportSpec.from_dict(snapshot["report"])
    visuals = {vid:v for page in report.pages.values() for vid,v in page.visuals.items()}
    contracts = {d["contract"]["block_id"]:DataBlockContract.model_validate(d["contract"]) for d in snapshot["datasets"]}
    for vid,state in states.items():
        if vid not in visuals:
            raise AppError("DRILL_INCOMPATIBLE", "鑽取圖表已不存在。",409)
        apply_drill(visuals[vid].query,visuals[vid].visualization,contracts,state)
    snapshot["drill_state"] = states


def assistant_drill_executor(executor, body, contracts, selected_id, states):
    """Apply exploration only at execution, leaving the proposal's report untouched."""
    from ai4bi.report.models import ExecutableReportSpec
    report = ExecutableReportSpec.from_dict(body)
    visuals = {vid:v for page in report.pages.values() for vid,v in page.visuals.items()}
    visual = visuals.get(selected_id)
    if visual is None:
        return executor, None
    drilled, context = apply_drill(visual.query,visual.visualization,contracts,states.get(selected_id))
    if context is None:
        return executor, None
    path_filters = drilled.filters[len(visual.query.filters):]
    known = {}
    for vid,v in visuals.items():
        known.setdefault(v.query.spec_id,[]).append(vid)

    class AssistantDrillExecutor:
        def __getattr__(self,name):
            return getattr(executor,name)

        def prepare(self,spec):
            owners = known.get(spec.spec_id,[])
            if len(owners)>1:
                raise AppError("INVALID_ASSISTANT_CONTEXT", "圖表查詢識別碼重複，無法判斷鑽取範圍。")
            owner = owners[0] if owners else None
            if owner == selected_id:
                return apply_drill(spec,visual.visualization,contracts,context)[0]
            query = copy.deepcopy(spec)
            if owner is None and context["block_id"] in query.all_block_ids:
                query.filters.extend(copy.deepcopy(path_filters))
            return query

        def run(self,spec,*args,**kwargs):
            return executor.run(self.prepare(spec),*args,**kwargs)

        def run_with_metadata(self,spec,*args,**kwargs):
            return executor.run_with_metadata(self.prepare(spec),*args,**kwargs)

    return AssistantDrillExecutor(), {"visual_id":selected_id,**context}


def assistant_source_contracts(executor, contracts, context, *, extra_filters=(), preserve_numeric_precision=False):
    """Give core dataframe analyses the same scoped population as governed queries."""
    import duckdb
    from ai4bi.analysis.executor import _build_filter_clause, _quote
    from ai4bi.blocks.loader import BlockLoader
    from ai4bi.blocks.contracts import CachedDataSource
    from ai4bi.blocks.datastore import put_dataframe
    from ai4bi.query_spec import BlockRef, VisualQuerySpec
    from .filters import PersistentFilterGroup, expression_sql
    result = dict(contracts)
    used_ids = {v["query"]["spec_id"] for page in executor.body["pages"].values() for v in page["visuals"].values()}
    source_id = "assistant_source_population"
    while source_id in used_ids:
        source_id += "_"
    for block_id,contract in contracts.items():
        # This adapter is owned by the API; explicit context avoids spec-ID inference.
        query = executor.prepare(VisualQuerySpec(source_id,[BlockRef(block_id)]),
                                 page_id=executor.page_id,visual_id=executor.visual_id)
        query.filters.extend(predicate for predicate in extra_filters if predicate.block_id == block_id)
        if context and context["block_id"] == block_id:
            query.filters.extend(FilterSpec(block_id,step["column"],
                FilterOperator.is_null if step["value"] is None else FilterOperator.eq,step["value"]) for step in context["path"])
        groups = [item for item in executor.applicable(query,page_id=executor.page_id,visual_id=executor.visual_id)
                  if isinstance(item,PersistentFilterGroup)]
        if not query.filters and not groups:
            continue
        params = []
        clauses = [_build_filter_clause(predicate,params) for predicate in query.filters]
        clauses.extend(expression_sql(group.expression,params,contracts) for group in groups)
        with duckdb.connect(database=":memory:") as conn:
            BlockLoader().register_to_duckdb(contract,block_id,conn)
            cursor = conn.execute(f"SELECT * FROM {_quote(block_id)} WHERE " + " AND ".join(clauses),params)
            if preserve_numeric_precision:
                import pandas as pd
                # DuckDB's pandas conversion can round HUGEINT/DECIMAL values.
                frame = pd.DataFrame(cursor.fetchall(), columns=[c[0] for c in cursor.description], dtype=object)
            else:
                frame = cursor.df()
        # A cached dataframe preserves column types even for an empty population.
        scoped = contract.model_copy(deep=True)
        scoped.data_source = CachedDataSource(content_hash=put_dataframe(frame),row_count=len(frame))
        result[block_id] = scoped
    return result
