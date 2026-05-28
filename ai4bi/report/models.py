"""Executable report state for the governed Streamlit report canvas."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai4bi.query_spec import (
    AggFunction,
    BlockRef,
    DimensionRef,
    FilterOperator,
    FilterSpec,
    MetricRef,
    SortDirection,
    SortSpec,
    VisualizationSpec,
    VisualQuerySpec,
    VisualType,
)


class ReportValidationError(ValueError):
    """Raised when a report or proposal does not conform to the draft contract."""


@dataclass
class AuditMetadata:
    """Governance audit trail for a report draft."""

    report_id: str
    created_by: str = "unknown"
    created_at: str | None = None      # ISO-8601 string, set on first save
    last_modified_by: str = "unknown"
    last_modified_at: str | None = None
    revision: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "last_modified_by": self.last_modified_by,
            "last_modified_at": self.last_modified_at,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AuditMetadata":
        return cls(
            report_id=payload["report_id"],
            created_by=payload.get("created_by", "unknown"),
            created_at=payload.get("created_at"),
            last_modified_by=payload.get("last_modified_by", "unknown"),
            last_modified_at=payload.get("last_modified_at"),
            revision=int(payload.get("revision", 0)),
        )


@dataclass
class ControlSpec:
    """One user-editable report control, optionally bound to a global filter."""

    control_id: str
    label: str
    value: Any
    options: list[Any]
    filter_key: str | None = None

    def validate(self) -> None:
        values = self.value if isinstance(self.value, list) else [self.value]
        invalid = [value for value in values if value not in self.options]
        if invalid:
            raise ReportValidationError(
                f"Control '{self.control_id}' contains unsupported values: {invalid}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "label": self.label,
            "value": copy.deepcopy(self.value),
            "options": copy.deepcopy(self.options),
            "filter_key": self.filter_key,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ControlSpec":
        control = cls(
            control_id=payload["control_id"],
            label=payload["label"],
            value=copy.deepcopy(payload["value"]),
            options=copy.deepcopy(payload["options"]),
            filter_key=payload.get("filter_key"),
        )
        control.validate()
        return control


def _block_ref_to_dict(ref: BlockRef) -> dict[str, Any]:
    return {
        "block_id": ref.block_id,
        "pinned_version": ref.pinned_version,
        "pin_reason": ref.pin_reason,
        "pinned_at": ref.pinned_at.isoformat() if ref.pinned_at else None,
    }


def _block_ref_from_dict(payload: dict[str, Any]) -> BlockRef:
    pinned_at = payload.get("pinned_at")
    return BlockRef(
        block_id=payload["block_id"],
        pinned_version=payload.get("pinned_version"),
        pin_reason=payload.get("pin_reason"),
        pinned_at=datetime.fromisoformat(pinned_at) if pinned_at else None,
    )


def query_to_dict(query: VisualQuerySpec) -> dict[str, Any]:
    return {
        "spec_id": query.spec_id,
        "block_refs": [_block_ref_to_dict(ref) for ref in query.block_refs],
        "metrics": [
            {
                "block_id": metric.block_id,
                "metric_name": metric.metric_name,
                "alias": metric.alias,
                "agg_override": metric.agg_override.value if metric.agg_override else None,
            }
            for metric in query.metrics
        ],
        "dimensions": [
            {
                "block_id": dimension.block_id,
                "column_name": dimension.column_name,
                "alias": dimension.alias,
                "truncate_date_to": dimension.truncate_date_to,
            }
            for dimension in query.dimensions
        ],
        "filters": [
            {
                "block_id": filter_spec.block_id,
                "column_name": filter_spec.column_name,
                "operator": filter_spec.operator.value,
                "value": copy.deepcopy(filter_spec.value),
                "inherit_global_filter": filter_spec.inherit_global_filter,
            }
            for filter_spec in query.filters
        ],
        "sort": [
            {"column_name": sort.column_name, "direction": sort.direction.value}
            for sort in query.sort
        ],
        "limit": query.limit,
        "data_version": query.data_version,
        "inherit_global_filter": query.inherit_global_filter,
    }


def query_from_dict(payload: dict[str, Any]) -> VisualQuerySpec:
    return VisualQuerySpec(
        spec_id=payload["spec_id"],
        block_refs=[_block_ref_from_dict(ref) for ref in payload["block_refs"]],
        metrics=[
            MetricRef(
                block_id=metric["block_id"],
                metric_name=metric["metric_name"],
                alias=metric.get("alias"),
                agg_override=(
                    AggFunction(metric["agg_override"]) if metric.get("agg_override") else None
                ),
            )
            for metric in payload.get("metrics", [])
        ],
        dimensions=[
            DimensionRef(
                block_id=dimension["block_id"],
                column_name=dimension["column_name"],
                alias=dimension.get("alias"),
                truncate_date_to=dimension.get("truncate_date_to"),
            )
            for dimension in payload.get("dimensions", [])
        ],
        filters=[
            FilterSpec(
                block_id=filter_spec["block_id"],
                column_name=filter_spec["column_name"],
                operator=FilterOperator(filter_spec["operator"]),
                value=copy.deepcopy(filter_spec.get("value")),
                inherit_global_filter=filter_spec.get("inherit_global_filter", False),
            )
            for filter_spec in payload.get("filters", [])
        ],
        sort=[
            SortSpec(sort["column_name"], SortDirection(sort.get("direction", "desc")))
            for sort in payload.get("sort", [])
        ],
        limit=payload.get("limit"),
        data_version=payload.get("data_version", "v1"),
        inherit_global_filter=payload.get("inherit_global_filter", False),
    )


def visualization_to_dict(style: VisualizationSpec) -> dict[str, Any]:
    return {
        "visual_type": style.visual_type.value,
        "title": style.title,
        "subtitle": style.subtitle,
        "x_axis_label": style.x_axis_label,
        "y_axis_label": style.y_axis_label,
        "color_scheme": style.color_scheme,
        "show_legend": style.show_legend,
        "show_sparkline": style.show_sparkline,
        "delta_metric": style.delta_metric,
        "height_px": style.height_px,
        "extra": copy.deepcopy(style.extra),
    }


def visualization_from_dict(payload: dict[str, Any]) -> VisualizationSpec:
    return VisualizationSpec(
        visual_type=VisualType(payload.get("visual_type", "kpi_card")),
        title=payload.get("title"),
        subtitle=payload.get("subtitle"),
        x_axis_label=payload.get("x_axis_label"),
        y_axis_label=payload.get("y_axis_label"),
        color_scheme=payload.get("color_scheme", "plotly"),
        show_legend=payload.get("show_legend", True),
        show_sparkline=payload.get("show_sparkline", False),
        delta_metric=payload.get("delta_metric"),
        height_px=payload.get("height_px", 300),
        extra=copy.deepcopy(payload.get("extra", {})),
    )


@dataclass
class ReportVisualSpec:
    component_id: str
    query: VisualQuerySpec
    visualization: VisualizationSpec

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "query": query_to_dict(self.query),
            "visualization": visualization_to_dict(self.visualization),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReportVisualSpec":
        return cls(
            component_id=payload["component_id"],
            query=query_from_dict(payload["query"]),
            visualization=visualization_from_dict(payload["visualization"]),
        )


@dataclass
class ReportPageSpec:
    page_id: str
    title: str
    visuals: dict[str, ReportVisualSpec]
    visual_order: list[str]

    def validate(self) -> None:
        if set(self.visual_order) != set(self.visuals):
            raise ReportValidationError("Page visual_order must exactly identify its visuals.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "title": self.title,
            "visuals": {key: visual.to_dict() for key, visual in self.visuals.items()},
            "visual_order": list(self.visual_order),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReportPageSpec":
        page = cls(
            page_id=payload["page_id"],
            title=payload["title"],
            visuals={
                key: ReportVisualSpec.from_dict(value)
                for key, value in payload["visuals"].items()
            },
            visual_order=list(payload["visual_order"]),
        )
        page.validate()
        return page

    def add_visual(self, visual_id: str, visual_spec: "ReportVisualSpec") -> None:
        """Add a visual to this page, appending its id to visual_order."""
        if visual_id in self.visuals:
            raise ReportValidationError(
                f"Visual '{visual_id}' already exists on page '{self.page_id}'."
            )
        self.visuals[visual_id] = visual_spec
        self.visual_order.append(visual_id)


@dataclass
class ExecutableReportSpec:
    audit: AuditMetadata
    title: str
    semantic_model_ref: str
    status: str
    pages: dict[str, ReportPageSpec]
    controls: dict[str, ControlSpec]
    read_only: bool = False
    saved_at: str | None = None

    # ------------------------------------------------------------------
    # Backward-compat properties so existing code using report.report_id
    # and report.revision continues to work without modification.
    # ------------------------------------------------------------------

    @property
    def report_id(self) -> str:
        return self.audit.report_id

    @property
    def revision(self) -> int:
        return self.audit.revision

    @revision.setter
    def revision(self, value: int) -> None:
        self.audit.revision = value

    def validate(self) -> None:
        if self.status != "validated_demo_draft":
            raise ReportValidationError("Only validated demo drafts are supported in this MVP.")
        if not self.pages:
            raise ReportValidationError("A report must contain at least one page.")
        for page in self.pages.values():
            page.validate()
        for control in self.controls.values():
            control.validate()

    def deep_copy(self) -> "ExecutableReportSpec":
        return ExecutableReportSpec.from_dict(self.to_dict())

    def active_filters(self) -> dict[str, Any]:
        return {
            control.filter_key: copy.deepcopy(control.value)
            for control in self.controls.values()
            if control.filter_key
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_version": "2.0-draft",
            "audit": self.audit.to_dict(),
            "title": self.title,
            "semantic_model_ref": self.semantic_model_ref,
            "status": self.status,
            "pages": {key: page.to_dict() for key, page in self.pages.items()},
            "controls": {key: control.to_dict() for key, control in self.controls.items()},
            "read_only": self.read_only,
            "saved_at": self.saved_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExecutableReportSpec":
        if payload.get("spec_version") != "2.0-draft":
            raise ReportValidationError("Unsupported report draft spec version.")
        # Backward compat: old drafts have top-level report_id/revision, no audit key
        if "audit" in payload:
            audit = AuditMetadata.from_dict(payload["audit"])
        else:
            audit = AuditMetadata(
                report_id=payload.get("report_id", ""),
                revision=int(payload.get("revision", 0)),
            )
        report = cls(
            audit=audit,
            title=payload["title"],
            semantic_model_ref=payload["semantic_model_ref"],
            status=payload["status"],
            pages={
                key: ReportPageSpec.from_dict(value)
                for key, value in payload["pages"].items()
            },
            controls={
                key: ControlSpec.from_dict(value)
                for key, value in payload["controls"].items()
            },
            read_only=bool(payload.get("read_only", False)),
            saved_at=payload.get("saved_at"),
        )
        report.validate()
        return report


@dataclass(frozen=True)
class ReportChange:
    path: str
    label: str
    before: Any
    after: Any
    affects_data: bool


@dataclass
class ReportProposal:
    description: str
    changes: list[ReportChange] = field(default_factory=list)
    target_component_id: str | None = None

    @property
    def affects_data(self) -> bool:
        return any(change.affects_data for change in self.changes)


def _get_path(report: ExecutableReportSpec, path: str) -> Any:
    parts = path.split("/")
    if len(parts) == 3 and parts[0] == "controls" and parts[2] == "value":
        return report.controls[parts[1]].value
    if len(parts) == 3 and parts[0] == "pages" and parts[2] == "add_visual":
        # For add_visual the "current" state is None (visual does not exist yet).
        return None
    if len(parts) == 7 and parts[0] == "pages" and parts[2] == "visuals":
        visual = report.pages[parts[1]].visuals[parts[3]]
        if parts[4:] == ["visualization", "extra", "line_color"]:
            return visual.visualization.extra.get("line_color")
    if len(parts) == 6 and parts[0] == "pages" and parts[2] == "visuals":
        visual = report.pages[parts[1]].visuals[parts[3]]
        if parts[4:] == ["visualization", "title"]:
            return visual.visualization.title
        if parts[4:] == ["query", "dimensions"]:
            return [
                {
                    "block_id": dimension.block_id,
                    "column_name": dimension.column_name,
                    "alias": dimension.alias,
                    "truncate_date_to": dimension.truncate_date_to,
                }
                for dimension in visual.query.dimensions
            ]
    if len(parts) == 8 and parts[0] == "pages" and parts[2] == "visuals" and parts[4] == "query" and parts[5] == "block_refs" and parts[7] == "pinned_version":
        visual = report.pages[parts[1]].visuals[parts[3]]
        block_id = parts[6]
        for ref in visual.query.block_refs:
            if ref.block_id == block_id:
                return ref.pinned_version
        raise ReportValidationError(f"BlockRef '{block_id}' not found in visual '{parts[3]}'.")
    raise ReportValidationError(f"Unsupported proposal path '{path}'.")


def _set_path(report: ExecutableReportSpec, path: str, value: Any) -> None:
    parts = path.split("/")
    if len(parts) == 3 and parts[0] == "controls" and parts[2] == "value":
        report.controls[parts[1]].value = copy.deepcopy(value)
        return
    if len(parts) == 3 and parts[0] == "pages" and parts[2] == "add_visual":
        # value is {"visual_id": str, "visual": dict}
        page = report.pages[parts[1]]
        visual_id = value["visual_id"]
        visual_spec = ReportVisualSpec.from_dict(value["visual"])
        page.add_visual(visual_id, visual_spec)
        return
    if len(parts) == 7 and parts[0] == "pages" and parts[2] == "visuals":
        visual = report.pages[parts[1]].visuals[parts[3]]
        if parts[4:] == ["visualization", "extra", "line_color"]:
            visual.visualization.extra["line_color"] = value
            return
    if len(parts) == 6 and parts[0] == "pages" and parts[2] == "visuals":
        visual = report.pages[parts[1]].visuals[parts[3]]
        if parts[4:] == ["visualization", "title"]:
            visual.visualization.title = str(value)
            return
        if parts[4:] == ["query", "dimensions"]:
            visual.query.dimensions = [
                DimensionRef(
                    block_id=dimension["block_id"],
                    column_name=dimension["column_name"],
                    alias=dimension.get("alias"),
                    truncate_date_to=dimension.get("truncate_date_to"),
                )
                for dimension in value
            ]
            return
    if len(parts) == 8 and parts[0] == "pages" and parts[2] == "visuals" and parts[4] == "query" and parts[5] == "block_refs" and parts[7] == "pinned_version":
        visual = report.pages[parts[1]].visuals[parts[3]]
        block_id = parts[6]
        for ref in visual.query.block_refs:
            if ref.block_id == block_id:
                ref.pinned_version = value
                if ref.pin_reason is None:
                    ref.pin_reason = "manually pinned by user"
                return
        raise ReportValidationError(f"BlockRef '{block_id}' not found in visual '{parts[3]}'.")
    raise ReportValidationError(f"Unsupported proposal path '{path}'.")


def apply_report_proposal(
    report: ExecutableReportSpec,
    proposal: ReportProposal,
) -> ExecutableReportSpec:
    """Atomically apply an allowlisted proposal to a report draft."""
    candidate = report.deep_copy()
    for change in proposal.changes:
        current = _get_path(candidate, change.path)
        if current != change.before:
            raise ReportValidationError(
                f"Proposal is stale for '{change.label}': expected {change.before!r}, got {current!r}."
            )
        _set_path(candidate, change.path, change.after)
    candidate.audit.revision += 1
    candidate.saved_at = None
    candidate.validate()
    return candidate


class DraftReportStore:
    """Filesystem store for explicitly non-published local report drafts."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    @staticmethod
    def _safe_name(report_id: str) -> str:
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", report_id).strip("_")
        if not name:
            raise ReportValidationError("Report id cannot be converted to a draft filename.")
        return name

    def save(self, report: ExecutableReportSpec) -> Path:
        report.validate()
        saved = report.deep_copy()
        saved.saved_at = datetime.now().astimezone().isoformat(timespec="seconds")
        saved.audit.last_modified_at = datetime.now(timezone.utc).isoformat()
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{self._safe_name(saved.report_id)}.json"
        path.write_text(json.dumps(saved.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def list_paths(self) -> list[Path]:
        if not self.directory.exists():
            return []
        return sorted(self.directory.glob("*.json"))

    def load(self, path: str | Path) -> ExecutableReportSpec:
        candidate = Path(path)
        if candidate.parent.resolve() != self.directory.resolve():
            raise ReportValidationError("Draft path is outside the configured store.")
        return ExecutableReportSpec.from_dict(
            json.loads(candidate.read_text(encoding="utf-8"))
        )
