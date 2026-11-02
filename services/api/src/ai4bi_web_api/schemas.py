from __future__ import annotations

from typing import Annotated, Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PairRequest(StrictModel):
    code: str = Field(min_length=12, max_length=200)


class WorkspaceCreate(StrictModel):
    title: str = Field(min_length=1, max_length=150)
    template: Literal["fab", "retail", "cv", "blank"] = "fab"
    idempotency_key: str = Field(min_length=8, max_length=128)


class Command(StrictModel):
    request_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=128)
    base_revision: int = Field(ge=1)
    command_type: Literal["replace_report", "save", "undo", "redo", "restore_saved", "apply_proposal", "duplicate_page", "save_scenario", "update_scenario", "rename_scenario", "apply_scenario", "delete_scenario", "save_bookmark", "update_bookmark", "rename_bookmark", "delete_bookmark", "add_filter", "update_filter", "delete_filter", "save_spc_analysis", "update_spc_analysis", "rename_spc_analysis", "delete_spc_analysis", "save_commonality_analysis", "update_commonality_analysis", "rename_commonality_analysis", "delete_commonality_analysis", "save_crossfact_analysis", "update_crossfact_analysis", "rename_crossfact_analysis", "delete_crossfact_analysis", "save_change_analysis", "update_change_analysis", "rename_change_analysis", "delete_change_analysis", "save_rfm_analysis", "update_rfm_analysis", "rename_rfm_analysis", "delete_rfm_analysis"]
    payload: dict[str, Any] = Field(default_factory=dict)


class QueryRequest(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    base_revision: int = Field(ge=1)
    visual_ids: list[str] = Field(default_factory=list, max_length=50)
    filters: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    exploration_page_id: str | None = Field(default=None, min_length=1, max_length=100)
    filter_bookmark_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$")
    drill_state: dict[str, dict[str, Any]] = Field(default_factory=dict, max_length=100)
    include_spc: bool = Field(default=False, strict=True)
    include_commonality: bool = Field(default=False, strict=True)
    include_crossfact: bool = Field(default=False, strict=True)
    include_change: bool = Field(default=False, strict=True)
    include_rfm: bool = Field(default=False, strict=True)

    def execution_options(self):
        result = {"visual_ids":self.visual_ids,"filters":self.filters}
        if self.include_rfm:
            result["include_rfm"] = True
        if self.include_change:
            result["include_change"] = True
        if self.include_crossfact:
            result["include_crossfact"] = True
        if self.include_commonality:
            result["include_commonality"] = True
        if self.include_spc:
            result["include_spc"] = True
        if self.exploration_page_id is not None:
            result["exploration_page_id"] = self.exploration_page_id
        if self.filter_bookmark_id is not None:
            result["filter_bookmark_id"] = self.filter_bookmark_id
        if self.drill_state:
            result["drill_state"] = self.drill_state
        return result


class PublishRequest(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    base_revision: int = Field(ge=1)


class AssistantRequest(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    base_revision: int = Field(ge=1)
    prompt: str = Field(min_length=1, max_length=4000)
    selected_component_id: str | None = None
    conversation: dict[str, Any] = Field(default_factory=dict)
    filter_bookmark_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$")
    drill_state: dict[str, dict[str, Any]] = Field(default_factory=dict, max_length=1)


class ExportRequest(QueryRequest):
    format: Literal["xlsx", "pdf", "json", "csv"] = "xlsx"
    include_spc: Literal[True] = True
    include_commonality: Literal[True] = True
    include_crossfact: Literal[True] = True
    include_change: Literal[True] = True
    include_rfm: Literal[True] = True


class SpcSettings(StrictModel):
    block_id: str = Field(min_length=1, max_length=200)
    entity_column: str = Field(min_length=1, max_length=200)
    value_column: str = Field(min_length=1, max_length=200)
    k: float = Field(default=3.0, gt=0, le=10, allow_inf_nan=False, strict=True)
    aggregation: Literal["mean", "sum"] = "mean"


class SpcRequest(SpcSettings):
    idempotency_key: str = Field(min_length=8, max_length=128)
    base_revision: int = Field(ge=1)
    selected_component_id: str | None = None
    filter_bookmark_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$")
    drill_state: dict[str, dict[str, Any]] = Field(default_factory=dict, max_length=100)
    filters: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    exploration_page_id: str | None = Field(default=None, min_length=1, max_length=100)


class CommonalitySettings(StrictModel):
    block_id: str = Field(min_length=1, max_length=200)
    outcome_block_id: str = Field(min_length=1, max_length=200)
    entity_column: str = Field(min_length=1, max_length=200)
    group_column: str = Field(min_length=1, max_length=200)
    outcome_group_column: str = Field(min_length=1, max_length=200)
    value_column: str = Field(min_length=1, max_length=200)
    threshold: float = Field(allow_inf_nan=False, strict=True)
    aggregation: Literal["mean", "sum"] = "mean"
    comparison: Literal["lt", "lte", "gt", "gte"] = "lt"


class CommonalityRequest(CommonalitySettings):
    idempotency_key: str = Field(min_length=8, max_length=128)
    base_revision: int = Field(ge=1)
    selected_component_id: str | None = None
    filter_bookmark_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$")
    drill_state: dict[str, dict[str, Any]] = Field(default_factory=dict, max_length=100)
    filters: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    exploration_page_id: str | None = Field(default=None, min_length=1, max_length=100)


class CrossFactAggregate(StrictModel):
    kind: Literal["aggregate"] = "aggregate"
    column: str = Field(min_length=1, max_length=200)
    aggregation: Literal["SUM", "AVG", "COUNT", "MIN", "MAX"] = "SUM"


class CrossFactWeightedRatio(StrictModel):
    kind: Literal["weighted_ratio"] = "weighted_ratio"
    numerator_column: str = Field(min_length=1, max_length=200)
    denominator_column: str = Field(min_length=1, max_length=200)
    scale: float = Field(default=100.0, allow_inf_nan=False, strict=True)


CrossFactMetric = Annotated[CrossFactAggregate | CrossFactWeightedRatio, Field(discriminator="kind")]


class CrossFactSettings(StrictModel):
    block_a: str = Field(min_length=1, max_length=200)
    block_b: str = Field(min_length=1, max_length=200)
    key_a: str = Field(min_length=1, max_length=200)
    key_b: str = Field(min_length=1, max_length=200)
    metric_a: CrossFactMetric
    metric_b: CrossFactMetric
    operation: Literal["ratio", "diff", "margin_pct"] = "ratio"
    quantiles: int = Field(default=5, ge=2, le=10, strict=True)


class CrossFactRequest(CrossFactSettings):
    idempotency_key: str = Field(min_length=8, max_length=128)
    base_revision: int = Field(ge=1)
    selected_component_id: str | None = None
    filter_bookmark_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$")
    drill_state: dict[str, dict[str, Any]] = Field(default_factory=dict, max_length=100)
    filters: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    exploration_page_id: str | None = Field(default=None, min_length=1, max_length=100)


class ChangeSettings(StrictModel):
    block_id: str = Field(min_length=1, max_length=200)
    metric_name: str = Field(min_length=1, max_length=200)
    date_column: str = Field(min_length=1, max_length=200)
    dimension_column: str = Field(min_length=1, max_length=200)
    period: Literal["week", "month", "quarter", "year"] = "month"
    filter_policy: Literal["keep", "replace"] = "replace"
    anchor: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class ChangeRequest(ChangeSettings):
    idempotency_key: str = Field(min_length=8, max_length=128)
    base_revision: int = Field(ge=1)
    selected_component_id: str | None = None
    filter_bookmark_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$")
    drill_state: dict[str, dict[str, Any]] = Field(default_factory=dict, max_length=100)
    filters: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    exploration_page_id: str | None = Field(default=None, min_length=1, max_length=100)


class RfmSettings(StrictModel):
    block_id: str = Field(min_length=1, max_length=200)
    customer_column: str = Field(min_length=1, max_length=200)
    date_column: str = Field(min_length=1, max_length=200)
    monetary_column: str = Field(min_length=1, max_length=200)
    anchor: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class RfmRequest(RfmSettings):
    idempotency_key: str = Field(min_length=8, max_length=128)
    base_revision: int = Field(ge=1)
    selected_component_id: str | None = None
    filter_bookmark_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$")
    drill_state: dict[str, dict[str, Any]] = Field(default_factory=dict, max_length=100)
    filters: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    exploration_page_id: str | None = Field(default=None, min_length=1, max_length=100)


class ImportConfig(StrictModel):
    encoding: Literal["utf-8-sig", "utf-8", "big5", "cp950", "latin-1"] = "utf-8-sig"
    delimiter: Literal[",", ";", "\t", "|"] = ","
    sheet: str | int = 0
    column_types: dict[str, Literal["string", "number", "integer", "date"]] = Field(default_factory=dict)


class ImportCommit(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    draft_revision: int = Field(ge=1)


class JobView(StrictModel):
    job_id: str
    workspace_id: str
    kind: str
    status: Literal["queued", "running", "cancelling", "succeeded", "failed", "cancelled"]
    created_at: str
    updated_at: str
    result: Any = None
    error: dict[str, Any] | None = None
