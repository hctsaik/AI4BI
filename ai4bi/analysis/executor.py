"""Execute governed visual query specifications against DataBlock JSON."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import duckdb
import pandas as pd

from ai4bi.blocks.contracts import DataBlockContract, DisaggregationMethod
from ai4bi.blocks.loader import BlockLoader
from ai4bi.blocks.registry import BlockRegistryProtocol
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


# ---------------------------------------------------------------------------
# ResultMetadata — spec section 7.4
# ---------------------------------------------------------------------------

@dataclass
class ResultMetadata:
    """Execution lineage returned alongside each query result.

    Satisfies spec 7.4 (ResultMetadata) and the "Explain before trust" principle.
    Stored in st.session_state["metadata_by_component"][component_id].
    """
    component_id: str
    row_count: int
    executed_at: str                          # ISO 8601 UTC
    blocks_used: list[str] = field(default_factory=list)
    relationships_used: list[str] = field(default_factory=list)  # "A → B (many_to_one)"
    metrics_used: list[dict] = field(default_factory=list)       # {name, formula, agg}
    dimensions_used: list[str] = field(default_factory=list)
    filters_applied: list[str] = field(default_factory=list)
    quality_warnings: list[str] = field(default_factory=list)
    data_freshness: dict[str, str] = field(default_factory=dict)  # block_id → ISO timestamp
    sql_preview: str = ""                     # first 400 chars of generated SQL
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
        registry: Optional[BlockRegistryProtocol] = None,
        extra_contracts: Optional[dict[str, "DataBlockContract"]] = None,
    ) -> None:
        self._registry_root = Path(registry_root) if registry_root else _DEFAULT_REGISTRY
        self._loader = loader or BlockLoader()
        self._registry = registry  # optional BlockRegistryProtocol for versioned resolution
        self._extra_contracts: dict[str, DataBlockContract] = extra_contracts or {}
        # Round 032: cache Arrow tables so InlineDataSource records are not
        # re-serialised on every query within the same Executor instance
        self._arrow_cache: dict[str, Any] = {}
        inferred_model = self._registry_root.parent / "semantic_model.json"
        configured_model = Path(semantic_model_path) if semantic_model_path else inferred_model
        self._semantic_model = (
            json.loads(configured_model.read_text(encoding="utf-8"))
            if configured_model.exists()
            else None
        )
        self._planner = SafeJoinPlanner(self._semantic_model)

    def _resolve_block_path(self, ref: BlockRef) -> Path:
        """
        Resolve a BlockRef to a filesystem Path.

        Backward-compatible: if no BlockRegistry was provided at construction
        time, falls back to the original filesystem-convention logic.
        """
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

    def _resolve_block_contract(
        self,
        ref: BlockRef,
        version_snapshot: Optional[dict[str, str]] = None,
    ) -> DataBlockContract:
        """
        Resolve a BlockRef to a DataBlockContract.

        Checks extra_contracts (user-uploaded blocks) first, then the
        BlockRegistryProtocol (if configured), then the filesystem.
        """
        if ref.block_id in self._extra_contracts:
            return self._extra_contracts[ref.block_id]
        if self._registry is not None:
            return self._registry.resolve(
                ref.block_id,
                ref.pinned_version or None,
                version_snapshot=version_snapshot,
            )
        return self._loader.load_json(str(self._resolve_block_path(ref)))

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
            # Use positional GROUP BY to avoid ambiguous column references when
            # the same column name exists in both the fact table and a joined dim table.
            dim_positions = ", ".join(str(i + 1) for i in range(len(spec.dimensions)))
            sql_parts.append(f"GROUP BY {dim_positions}")
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
        version_snapshot: Optional[dict[str, str]] = None,
    ) -> pd.DataFrame:
        df, _ = self.run_with_metadata(
            spec, active_filters=active_filters, version_snapshot=version_snapshot
        )
        return df

    def run_with_metadata(
        self,
        spec: VisualQuerySpec,
        active_filters: Optional[dict[str, Any]] = None,
        version_snapshot: Optional[dict[str, str]] = None,
        component_id: Optional[str] = None,
    ) -> tuple[pd.DataFrame, ResultMetadata]:
        """Execute and return (DataFrame, ResultMetadata).

        ResultMetadata contains the full execution lineage required by spec 7.4
        and displayed in the per-visual Explanation Panel (spec 8.1).
        """
        if active_filters is not None:
            spec = self._apply_active_filters(spec, active_filters)

        conn = duckdb.connect(database=":memory:")
        contracts: dict[str, DataBlockContract] = {}
        executed_at = datetime.now(timezone.utc).isoformat()
        try:
            for ref in spec.block_refs:
                contract = self._resolve_block_contract(ref, version_snapshot=version_snapshot)
                contracts[ref.block_id] = contract
                # Round 032: reuse cached Arrow table for InlineDataSource blocks
                from ai4bi.blocks.contracts import InlineDataSource as _Inline
                if isinstance(contract.data_source, _Inline) and ref.block_id in self._arrow_cache:
                    conn.register(ref.block_id, self._arrow_cache[ref.block_id])
                else:
                    self._loader.register_to_duckdb(contract, ref.block_id, conn)
                    if isinstance(contract.data_source, _Inline):
                        # Cache the Arrow table for subsequent queries in this session
                        self._arrow_cache[ref.block_id] = self._loader.to_arrow(contract)

            joins = self._planner.resolve(spec, contracts)
            params: list[Any] = []
            sql = self._build_sql(spec, contracts, joins, params)
            logger.debug("[executor] SQL:\n%s\nparams=%s", sql, params)
            df = conn.execute(sql, params).df()

            # Build metadata
            blocks_used = [ref.block_id for ref in spec.block_refs]
            relationships_used = [
                f"{j.from_block} → {j.to_block} "
                f"({getattr(j, 'cardinality', 'many_to_one')}) "
                f"[{getattr(j, 'certification_status', 'certified')}]"
                for j in joins
            ]
            metrics_used = []
            for m in spec.metrics:
                contract = contracts.get(m.block_id)
                defn = next(
                    (md for md in (contract.metrics if contract else []) if md.name == m.metric_name),
                    None,
                )
                metrics_used.append({
                    "name": m.alias or m.metric_name,
                    "metric_id": m.metric_name,
                    "formula": getattr(defn, "formula", None) or m.metric_name,
                    "agg": getattr(defn, "disaggregation_method", None) or "unknown",
                    "block_id": m.block_id,
                })
            dimensions_used = [
                f"{d.alias or d.column_name}"
                + (f" (DATE_TRUNC {d.truncate_date_to})" if d.truncate_date_to else "")
                for d in spec.dimensions
            ]
            filters_applied = [
                f"{f.block_id}.{f.column_name} {f.operator.value} {f.value!r}"
                for f in spec.filters
                if f.value is not None
            ]
            quality_warnings: list[str] = []
            if df.empty:
                quality_warnings.append("Query returned 0 rows — check active filters.")
            data_freshness: dict[str, str] = {}
            for ref in spec.block_refs:
                block_path = self._resolve_block_path(ref)
                if block_path.exists():
                    mtime = datetime.fromtimestamp(
                        block_path.stat().st_mtime, tz=timezone.utc
                    ).isoformat()
                    data_freshness[ref.block_id] = mtime

            metadata = ResultMetadata(
                component_id=component_id or spec.spec_id,
                row_count=len(df),
                executed_at=executed_at,
                blocks_used=blocks_used,
                relationships_used=relationships_used,
                metrics_used=metrics_used,
                dimensions_used=dimensions_used,
                filters_applied=filters_applied,
                quality_warnings=quality_warnings,
                data_freshness=data_freshness,
                sql_preview=sql[:400],
            )
            logger.debug(
                "[executor] run_with_metadata spec=%s rows=%d blocks=%s",
                spec.spec_id, len(df), blocks_used,
            )
            return df, metadata
        finally:
            conn.close()
