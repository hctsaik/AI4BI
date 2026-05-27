"""Execute governed visual query specifications against DataBlock JSON."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any, Optional

import duckdb
import pandas as pd

from ai4bi.blocks.contracts import DataBlockContract, DisaggregationMethod
from ai4bi.blocks.loader import BlockLoader
from ai4bi.planning.join_planner import QueryPlanningError, ResolvedJoin, SafeJoinPlanner
from ai4bi.query_spec import (
    AggFunction,
    BlockRef,
    DimensionRef,
    FilterOperator,
    FilterSpec,
    MetricRef,
    VisualQuerySpec,
)

logger = logging.getLogger(__name__)

_DEFAULT_REGISTRY = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "blocks"
_APPROVED_AGGREGATIONS = {
    DisaggregationMethod.sum: AggFunction.sum,
    DisaggregationMethod.average: AggFunction.avg,
    DisaggregationMethod.count: AggFunction.count,
    DisaggregationMethod.min: AggFunction.min,
    DisaggregationMethod.max: AggFunction.max,
}


def _quote(name: str) -> str:
    """Double quote a DuckDB identifier."""
    return f'"{name}"'


def _qualified(block_id: str, column_name: str) -> str:
    return f"{_quote(block_id)}.{_quote(column_name)}"


def _column_names(contract: DataBlockContract) -> set[str]:
    return {column.name for column in contract.columns}


def _require_column(
    contracts: dict[str, DataBlockContract],
    block_id: str,
    column_name: str,
) -> None:
    if block_id not in contracts or column_name not in _column_names(contracts[block_id]):
        raise QueryPlanningError(f"Unknown column '{block_id}.{column_name}'.")


def _build_filter_clause(spec: FilterSpec, params: list[Any]) -> str:
    col = _qualified(spec.block_id, spec.column_name)
    op = spec.operator
    val = spec.value

    if op == FilterOperator.eq:
        params.append(val)
        return f"{col} = ?"
    if op == FilterOperator.neq:
        params.append(val)
        return f"{col} != ?"
    if op == FilterOperator.gt:
        params.append(val)
        return f"{col} > ?"
    if op == FilterOperator.gte:
        params.append(val)
        return f"{col} >= ?"
    if op == FilterOperator.lt:
        params.append(val)
        return f"{col} < ?"
    if op == FilterOperator.lte:
        params.append(val)
        return f"{col} <= ?"
    if op == FilterOperator.in_:
        if not val:
            return "1=0"
        params.extend(val)
        return f"{col} IN ({', '.join(['?'] * len(val))})"
    if op == FilterOperator.not_in:
        if not val:
            return "1=1"
        params.extend(val)
        return f"{col} NOT IN ({', '.join(['?'] * len(val))})"
    if op == FilterOperator.between:
        params.extend([val[0], val[1]])
        return f"{col} BETWEEN ? AND ?"
    if op == FilterOperator.like:
        params.append(val)
        return f"{col} LIKE ?"
    if op == FilterOperator.is_null:
        return f"{col} IS NULL"
    if op == FilterOperator.is_not_null:
        return f"{col} IS NOT NULL"
    raise QueryPlanningError(f"Unsupported filter operator '{op}'.")


class Executor:
    """Compile and execute validated single-fact visual query specifications."""

    def __init__(
        self,
        registry_root: Optional[str | Path] = None,
        loader: Optional[BlockLoader] = None,
        semantic_model_path: Optional[str | Path] = None,
    ) -> None:
        self._registry_root = Path(registry_root) if registry_root else _DEFAULT_REGISTRY
        self._loader = loader or BlockLoader()
        inferred_model = self._registry_root.parent / "semantic_model.json"
        configured_model = Path(semantic_model_path) if semantic_model_path else inferred_model
        self._semantic_model = (
            json.loads(configured_model.read_text(encoding="utf-8"))
            if configured_model.exists()
            else None
        )
        self._planner = SafeJoinPlanner(self._semantic_model)

    def _resolve_block_path(self, ref: BlockRef) -> Path:
        if ref.pinned_version:
            versioned = self._registry_root / ref.block_id / f"{ref.pinned_version}.json"
            if versioned.exists():
                return versioned
            logger.warning(
                "[executor] Pinned version %s for '%s' was not found; using current contract.",
                ref.pinned_version,
                ref.block_id,
            )
        return self._registry_root / f"{ref.block_id}.json"

    @staticmethod
    def _apply_active_filters(
        spec: VisualQuerySpec,
        active_filters: dict[str, Any],
    ) -> VisualQuerySpec:
        if not active_filters:
            return spec
        filters: list[FilterSpec] = []
        for filter_spec in spec.filters:
            key = f"{filter_spec.block_id}.{filter_spec.column_name}"
            if filter_spec.inherit_global_filter and key in active_filters:
                filters.append(replace(filter_spec, value=active_filters[key]))
            else:
                filters.append(filter_spec)
        return replace(spec, filters=filters)

    @staticmethod
    def _build_metric_expr(
        metric: MetricRef,
        contracts: dict[str, DataBlockContract],
        primary_block_id: str,
    ) -> str:
        if metric.block_id != primary_block_id:
            raise QueryPlanningError("Metrics must come from the primary fact block.")
        contract = contracts[metric.block_id]
        definition = next(
            (candidate for candidate in contract.metrics if candidate.name == metric.metric_name),
            None,
        )
        if definition is None:
            raise QueryPlanningError(
                f"Metric '{metric.metric_name}' is not declared by '{metric.block_id}'."
            )
        _require_column(contracts, metric.block_id, metric.metric_name)
        approved = _APPROVED_AGGREGATIONS.get(definition.disaggregation_method)
        if approved is None:
            raise QueryPlanningError(
                f"Metric '{metric.metric_name}' requires a derived-expression planner."
            )
        if metric.agg_override is not None and metric.agg_override is not approved:
            raise QueryPlanningError(
                f"Aggregation '{metric.agg_override.value}' is not approved for "
                f"metric '{metric.metric_name}'; use '{approved.value}'."
            )
        alias = _quote(metric.alias or metric.metric_name)
        return f"{approved.value}({_qualified(metric.block_id, metric.metric_name)}) AS {alias}"

    @staticmethod
    def _build_dimension_expr(
        dimension: DimensionRef,
        contracts: dict[str, DataBlockContract],
    ) -> str:
        _require_column(contracts, dimension.block_id, dimension.column_name)
        col = _qualified(dimension.block_id, dimension.column_name)
        alias = _quote(dimension.alias or dimension.column_name)
        if dimension.truncate_date_to:
            return f"DATE_TRUNC('{dimension.truncate_date_to.lower()}', {col}::DATE) AS {alias}"
        return f"{col} AS {alias}"

    def _build_sql(
        self,
        spec: VisualQuerySpec,
        contracts: dict[str, DataBlockContract],
        joins: list[ResolvedJoin],
        params: list[Any],
    ) -> str:
        for filter_spec in spec.filters:
            _require_column(contracts, filter_spec.block_id, filter_spec.column_name)

        aliases = [
            *(dimension.alias or dimension.column_name for dimension in spec.dimensions),
            *(metric.alias or metric.metric_name for metric in spec.metrics),
        ]
        if len(aliases) != len(set(aliases)):
            raise QueryPlanningError("Visual output aliases must be unique.")
        for sort_spec in spec.sort:
            if sort_spec.column_name not in aliases:
                raise QueryPlanningError(
                    f"Sort column '{sort_spec.column_name}' is not a projected output."
                )

        select_parts = [
            *(self._build_dimension_expr(dimension, contracts) for dimension in spec.dimensions),
            *(
                self._build_metric_expr(metric, contracts, spec.primary_block_id)
                for metric in spec.metrics
            ),
        ]
        select_clause = ",\n    ".join(select_parts) if select_parts else f"{_quote(spec.primary_block_id)}.*"
        sql_parts = [f"SELECT\n    {select_clause}", f"FROM {_quote(spec.primary_block_id)}"]

        for join in joins:
            predicates = " AND ".join(
                f"{_qualified(join.from_block, source)} = {_qualified(join.to_block, target)}"
                for source, target in join.key_pairs
            )
            sql_parts.append(f"LEFT JOIN {_quote(join.to_block)} ON {predicates}")

        where_parts = [
            _build_filter_clause(filter_spec, params)
            for filter_spec in spec.filters
            if filter_spec.value is not None
            or filter_spec.operator in (FilterOperator.is_null, FilterOperator.is_not_null)
        ]
        if where_parts:
            sql_parts.append("WHERE\n    " + "\n    AND ".join(where_parts))
        if spec.dimensions and spec.metrics:
            sql_parts.append(
                "GROUP BY " + ", ".join(_quote(d.alias or d.column_name) for d in spec.dimensions)
            )
        if spec.sort:
            sql_parts.append(
                "ORDER BY " + ", ".join(
                    f"{_quote(sort.column_name)} {sort.direction.value.upper()}"
                    for sort in spec.sort
                )
            )
        if spec.limit:
            sql_parts.append(f"LIMIT {spec.limit}")
        return "\n".join(sql_parts)

    def run(
        self,
        spec: VisualQuerySpec,
        active_filters: Optional[dict[str, Any]] = None,
    ) -> pd.DataFrame:
        if active_filters is not None:
            spec = self._apply_active_filters(spec, active_filters)

        conn = duckdb.connect(database=":memory:")
        contracts: dict[str, DataBlockContract] = {}
        try:
            for ref in spec.block_refs:
                contract = self._loader.load_json(str(self._resolve_block_path(ref)))
                contracts[ref.block_id] = contract
                self._loader.register_to_duckdb(contract, ref.block_id, conn)

            joins = self._planner.resolve(spec, contracts)
            params: list[Any] = []
            sql = self._build_sql(spec, contracts, joins, params)
            logger.debug("[executor] SQL:\n%s\nparams=%s", sql, params)
            return conn.execute(sql, params).df()
        finally:
            conn.close()
