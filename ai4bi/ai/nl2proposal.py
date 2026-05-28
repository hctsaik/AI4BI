"""Deterministic NL-to-proposal service for governed BI workflows."""

from __future__ import annotations

import re
from typing import Any

from ai4bi.ai.intent_models import (
    AIIntent,
    AnalysisPlan,
    GovernanceRefusal,
    NL2ProposalResult,
    SemanticSelection,
)
from ai4bi.query_spec import AggFunction, DimensionRef, MetricRef, VisualType
from ai4bi.report.models import ExecutableReportSpec, ReportChange, ReportProposal, ReportVisualSpec

# ---------------------------------------------------------------------------
# Round 019: Chart-type change mappings
# Safe transitions: bar ↔ line only. table/kpi_card require different query
# contracts and are blocked (design-council 003-E safety review).
# ---------------------------------------------------------------------------

_CHART_TYPE_SAFE_TRANSITIONS: dict[VisualType, VisualType] = {
    VisualType.bar_chart:  VisualType.line_chart,
    VisualType.line_chart: VisualType.bar_chart,
}

_CHART_TYPE_KEYWORDS: dict[str, VisualType] = {
    "bar": VisualType.bar_chart,
    "bar chart": VisualType.bar_chart,
    "長條圖": VisualType.bar_chart,
    "柱狀圖": VisualType.bar_chart,
    "line": VisualType.line_chart,
    "line chart": VisualType.line_chart,
    "折線圖": VisualType.line_chart,
    "trend chart": VisualType.line_chart,
}

# ---------------------------------------------------------------------------
# Round 019: Dimension-change mappings (date truncation keywords)
# ---------------------------------------------------------------------------

_DIMENSION_DATE_KEYWORDS: dict[str, str] = {
    "month": "month",
    "monthly": "month",
    "月份": "month",
    "月": "month",
    "week": "week",
    "weekly": "week",
    "週": "week",
    "day": "day",
    "daily": "day",
    "日": "day",
    "quarter": "quarter",
    "季": "quarter",
    "year": "year",
    "yearly": "year",
    "年": "year",
}

# ---------------------------------------------------------------------------
# Round 019: Add-metric keywords
# ---------------------------------------------------------------------------

_METRIC_ADD_PATTERNS = (
    r"也加上\s*(\w+)",
    r"加上\s*(\w+)\s*指標",
    r"add\s+(\w+)\s*metric",
    r"include\s+(\w+)",
    r"also\s+show\s+(\w+)",
)

_MAX_METRICS_PER_VISUAL = 3

_COLOR_HEX = {
    "red": "#D62728",
    "blue": "#1F77B4",
    "green": "#2CA02C",
    "orange": "#FF7F0E",
    "purple": "#9467BD",
    "gray": "#7F7F7F",
    "grey": "#7F7F7F",
    "black": "#111111",
}
_COLOR_ALIASES = {
    "red": "red",
    "blue": "blue",
    "green": "green",
    "orange": "orange",
    "purple": "purple",
    "gray": "gray",
    "grey": "grey",
    "black": "black",
    "紅": "red",
    "紅色": "red",
    "藍": "blue",
    "藍色": "blue",
    "綠": "green",
    "綠色": "green",
}
_STYLE_TERMS = (
    "color",
    "colour",
    "style",
    "line",
    "bar",
    "red",
    "blue",
    "green",
    "orange",
    "purple",
    "gray",
    "grey",
    "black",
)
_ANALYSIS_TERMS = (
    "analyze",
    "analysis",
    "explain",
    "why",
    "driver",
    "drivers",
    "breakdown",
    "trend",
    "compare",
    "investigate",
)
_QUEUE_TERMS = ("queue", "queue-time", "queue time", "wait", "waiting")
_SQL_REFUSAL_PATTERNS = (
    r"\bsql\b",
    r"\bjoin\b",
    r"\bselect\s+.+\bfrom\b",
    r"\byield\b.*\b(detail|row|raw|move|join)\b",
    r"\b(detail|row|raw|move)\b.*\byield\b.*\bjoin\b",
)

# ---------------------------------------------------------------------------
# Round 020: Date Filter keyword → relative period mapping
# Uses {anchor:"relative", period:...} — no datetime.now() call, deterministic.
# The execution layer resolves relative periods at query time.
# ---------------------------------------------------------------------------

_DATE_FILTER_PERIOD_MAP: dict[str, str] = {
    # last 3 months
    "最近3個月": "last_3m",
    "最近 3 個月": "last_3m",
    "最近三個月": "last_3m",
    "last 3 months": "last_3m",
    "last3months": "last_3m",
    "past 3 months": "last_3m",
    # last quarter
    "last quarter": "last_quarter",
    "上季": "last_quarter",
    "上一季": "last_quarter",
    "前一季": "last_quarter",
    # year to date
    "今年": "ytd",
    "ytd": "ytd",
    "year to date": "ytd",
    "this year": "ytd",
    "本年度": "ytd",
    # last 6 months
    "最近6個月": "last_6m",
    "最近 6 個月": "last_6m",
    "最近半年": "last_6m",
    "last 6 months": "last_6m",
    # last month
    "上個月": "last_month",
    "last month": "last_month",
    # clear date filter
    "清除日期": "clear",
    "clear date": "clear",
    "remove date filter": "clear",
    "取消日期篩選": "clear",
}

_DATE_FILTER_TRIGGER_TERMS = (
    "最近", "上季", "上一季", "前一季", "今年", "本年度",
    "last quarter", "last month", "last 3", "last 6",
    "ytd", "year to date", "this year", "past 3", "past 6",
    "清除日期", "clear date", "remove date",
)

_DATE_FILTER_GLOBAL_KEY = "date_range"


class NL2ProposalService:
    """Classifies natural-language BI requests into typed, governed outcomes.

    This first implementation is deterministic. It grounds requests to the
    selected report visual, creates style-only proposals for chart color
    changes, plans queue-time analysis without SQL, and refuses requests that
    ask for raw SQL or unsafe free-form joins.
    """

    def propose(
        self,
        prompt: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None = None,
        semantic_model: dict[str, Any] | None = None,
        contracts: dict[str, Any] | None = None,
    ) -> NL2ProposalResult:
        normalized = _normalize(prompt)
        if not normalized:
            return self._unsupported(
                "Enter a governed BI request.",
                target_scope=_target_scope(selected_component_id),
            )

        refusal = self._governance_refusal(normalized, semantic_model)
        if refusal is not None:
            intent = AIIntent(
                intent_kind="unsupported",
                target_scope=_target_scope(selected_component_id),
                trust_notes=refusal.trust_notes,
                risk_level=refusal.risk_level,
            )
            return NL2ProposalResult(
                intent=intent,
                message=refusal.reason,
                refusal=refusal,
                trust_notes=refusal.trust_notes,
                risk_level=refusal.risk_level,
            )

        # Chart-type change is checked before style: both include "bar"/"line" keywords,
        # but chart-type requires a change verb + chart noun (more specific pattern).
        if _looks_like_chart_type_change(prompt, normalized):
            return self._chart_type_change(prompt, normalized, report, selected_component_id)

        if _looks_like_style_request(prompt, normalized):
            return self._style_change(prompt, normalized, report, selected_component_id)

        if _looks_like_dimension_change(prompt, normalized):
            return self._dimension_change(prompt, normalized, report, selected_component_id)

        add_metric_name = _extract_add_metric_name(prompt, normalized)
        if add_metric_name is not None:
            return self._add_metric(add_metric_name, report, selected_component_id, semantic_model)

        if _looks_like_date_filter(prompt, normalized):
            return self._date_filter_change(prompt, normalized, report)

        if _looks_like_queue_analysis(normalized):
            return self._queue_time_plan(prompt, report, selected_component_id, semantic_model, contracts)

        return self._unsupported(
            "No supported governed BI intent was detected.",
            target_scope=_target_scope(selected_component_id),
        )

    def _style_change(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
    ) -> NL2ProposalResult:
        found = _find_visual(report, selected_component_id)
        if found is None:
            return self._unsupported(
                "Select a line or bar chart before changing chart style.",
                target_scope=_target_scope(selected_component_id),
            )
        page_id, visual_id, visual = found
        visual_type = visual.visualization.visual_type
        color = _extract_color(prompt, normalized)
        if color is None:
            return self._unsupported(
                "Specify a supported chart color such as red, blue, green, orange, purple, gray, or black.",
                target_scope=f"visual:{visual_id}",
            )

        selection = _selection_from_visual(visual)
        if visual_type == VisualType.line_chart:
            style_key = "line_color"
            label = "Line color"
        elif visual_type == VisualType.bar_chart:
            style_key = "bar_color"
            label = "Bar color"
        else:
            return self._unsupported(
                f"Style color changes are supported for line and bar charts, not {visual_type.value}.",
                target_scope=f"visual:{visual_id}",
                selection=selection,
            )

        path = f"pages/{page_id}/visuals/{visual_id}/visualization/extra/{style_key}"
        before = visual.visualization.extra.get(style_key)
        notes = [
            f"Grounded to selected {visual_type.value} visual '{visual_id}'.",
            "Proposal changes visualization metadata only; query semantics are unchanged.",
        ]
        proposal = None
        if before != color:
            proposal = ReportProposal(
                description=f"Change {label.lower()} to {color}",
                changes=[
                    ReportChange(
                        path=path,
                        label=label,
                        before=before,
                        after=color,
                        affects_data=False,
                    )
                ],
                target_component_id=visual_id,
            )
        intent = AIIntent(
            intent_kind="style_change",
            target_scope=f"visual:{visual_id}",
            selection=selection,
            suggested_visuals=[visual_id],
            trust_notes=notes,
            risk_level="low",
        )
        message = (
            "Style proposal created. Review the diff before applying it."
            if proposal
            else "The selected chart already uses that color."
        )
        return NL2ProposalResult(
            intent=intent,
            message=message,
            proposal=proposal,
            trust_notes=notes,
            risk_level="low",
        )

    def _queue_time_plan(
        self,
        prompt: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
        semantic_model: dict[str, Any] | None,
        contracts: dict[str, Any] | None,
    ) -> NL2ProposalResult:
        found = _find_visual(report, selected_component_id)
        if found is None:
            found = _first_queue_visual(report)
        visual_id = found[1] if found is not None else None
        visual = found[2] if found is not None else None
        selection = _selection_from_visual(visual) if visual is not None else _selection_from_semantic_model(semantic_model)
        scope = f"visual:{visual_id}" if visual_id is not None else "semantic_model"
        suggested_visuals = _queue_visual_ids(report)
        model_ref = getattr(report, "semantic_model_ref", "unknown")
        contract_count = len(contracts or {})
        notes = [
            "Uses governed queue-time metric selection; no SQL is generated.",
            f"Report semantic model reference: {model_ref}.",
            f"Contracts available for grounding: {contract_count}.",
        ]
        plan = AnalysisPlan(
            question=prompt.strip(),
            target_scope=scope,
            selection=selection,
            steps=[
                "Confirm the queue-time metric and inherited report filters.",
                "Compare the queue-time trend across the selected date dimension.",
                "Break down queue time by certified dimensions already present in the report.",
                "Return observations with metric, dimension, and filter lineage.",
            ],
            suggested_visuals=suggested_visuals,
            trust_notes=notes,
            risk_level="medium",
            generated_sql=None,
        )
        intent = AIIntent(
            intent_kind="analysis_request",
            target_scope=scope,
            selection=selection,
            suggested_visuals=suggested_visuals,
            trust_notes=notes,
            risk_level="medium",
        )
        return NL2ProposalResult(
            intent=intent,
            message="Analysis plan created. It does not generate SQL or change the report.",
            analysis_plan=plan,
            trust_notes=notes,
            risk_level="medium",
        )

    # ------------------------------------------------------------------
    # Round 020: date_filter_change intent (global_filters/date_range)
    # ------------------------------------------------------------------

    def _date_filter_change(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
    ) -> NL2ProposalResult:
        period = _extract_date_period(prompt, normalized)
        if period is None:
            return self._unsupported(
                "Specify a date period: last 3 months (最近3個月), last quarter (上季), "
                "this year (今年), or clear date filter (清除日期).",
                target_scope="report",
            )

        before = report.global_filters.get(_DATE_FILTER_GLOBAL_KEY)

        if period == "clear":
            after = None
            description = "Clear date range filter"
            label = "Date range filter"
        else:
            after = {"anchor": "relative", "period": period}
            description = f"Set date range to {period}"
            label = f"Date range → {period}"

        if before == after:
            notes = [f"Date filter is already set to {period}."]
            intent = AIIntent(
                intent_kind="analysis_request",
                target_scope="report",
                trust_notes=notes,
                risk_level="low",
            )
            return NL2ProposalResult(
                intent=intent,
                message=f"Date filter is already set to {period}.",
                trust_notes=notes,
                risk_level="low",
            )

        notes = [
            f"Setting report-level date_range global filter to {period!r}.",
            "This affects all visuals that inherit global filters.",
            "No SQL is generated — the execution layer resolves the relative period at query time.",
        ]
        proposal = ReportProposal(
            description=description,
            changes=[
                ReportChange(
                    path=f"global_filters/{_DATE_FILTER_GLOBAL_KEY}",
                    label=label,
                    before=before,
                    after=after,
                    affects_data=True,
                )
            ],
        )
        intent = AIIntent(
            intent_kind="analysis_request",
            target_scope="report",
            trust_notes=notes,
            risk_level="low",
        )
        return NL2ProposalResult(
            intent=intent,
            message=f"Date filter proposal created: {description}.",
            proposal=proposal,
            trust_notes=notes,
            risk_level="low",
        )

    # ------------------------------------------------------------------
    # Round 019: chart_type_change intent
    # ------------------------------------------------------------------

    def _chart_type_change(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
    ) -> NL2ProposalResult:
        found = _find_visual(report, selected_component_id)
        if found is None:
            return self._unsupported(
                "Select a bar or line chart before changing the chart type.",
                target_scope=_target_scope(selected_component_id),
            )
        page_id, visual_id, visual = found
        current_type = visual.visualization.visual_type

        # Detect target chart type from prompt
        target_type = _extract_chart_type(prompt, normalized)
        if target_type is None:
            return self._unsupported(
                "Specify a supported chart type: bar chart (長條圖) or line chart (折線圖).",
                target_scope=f"visual:{visual_id}",
            )

        # Safety: only allow bar ↔ line transitions
        if current_type not in _CHART_TYPE_SAFE_TRANSITIONS:
            return self._unsupported(
                f"Chart type change is not supported for {current_type.value} visuals. "
                "Only bar chart and line chart can be converted to each other.",
                target_scope=f"visual:{visual_id}",
            )
        if target_type not in (VisualType.bar_chart, VisualType.line_chart):
            return self._unsupported(
                "Only bar chart ↔ line chart conversions are supported. "
                "table and kpi_card require different query contracts.",
                target_scope=f"visual:{visual_id}",
            )
        if current_type == target_type:
            notes = [f"Visual '{visual_id}' is already a {target_type.value}."]
            intent = AIIntent(
                intent_kind="style_change",
                target_scope=f"visual:{visual_id}",
                trust_notes=notes,
                risk_level="low",
            )
            return NL2ProposalResult(
                intent=intent,
                message=f"Visual '{visual_id}' is already a {target_type.value}.",
                trust_notes=notes,
                risk_level="low",
            )

        path = f"pages/{page_id}/visuals/{visual_id}/visualization/visual_type"
        notes = [
            f"Grounded to visual '{visual_id}' ({current_type.value}).",
            "Only bar ↔ line conversions are allowed; query semantics are unchanged.",
            "Presentation-only change: no data re-query required.",
        ]
        proposal = ReportProposal(
            description=f"Change chart type from {current_type.value} to {target_type.value}",
            changes=[
                ReportChange(
                    path=path,
                    label="Chart type",
                    before=current_type.value,
                    after=target_type.value,
                    affects_data=False,
                )
            ],
            target_component_id=visual_id,
        )
        intent = AIIntent(
            intent_kind="style_change",
            target_scope=f"visual:{visual_id}",
            suggested_visuals=[visual_id],
            trust_notes=notes,
            risk_level="low",
        )
        return NL2ProposalResult(
            intent=intent,
            message="Chart type proposal created. Review the diff before applying it.",
            proposal=proposal,
            trust_notes=notes,
            risk_level="low",
        )

    # ------------------------------------------------------------------
    # Round 019: dimension_change intent
    # ------------------------------------------------------------------

    def _dimension_change(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
    ) -> NL2ProposalResult:
        found = _find_visual(report, selected_component_id)
        if found is None:
            return self._unsupported(
                "Select a visual before changing the grouping dimension.",
                target_scope=_target_scope(selected_component_id),
            )
        page_id, visual_id, visual = found

        # Detect target date truncation granularity
        truncate_to = _extract_date_granularity(prompt, normalized)
        if truncate_to is None:
            return self._unsupported(
                "Specify a time granularity: month (月份), week (週), day (日), quarter (季), or year (年).",
                target_scope=f"visual:{visual_id}",
            )

        # Derive block_id from the visual's first metric block
        if not visual.query.metrics:
            return self._unsupported(
                "This visual has no metrics; cannot determine the dimension block.",
                target_scope=f"visual:{visual_id}",
            )
        block_id = visual.query.metrics[0].block_id

        # Find a date/time column to group by — use the first time column in current dimensions
        # or fall back to detecting a date column in the existing query dimensions.
        time_column = _find_time_column(visual)
        if time_column is None:
            return self._unsupported(
                "Could not find a time dimension in this visual to apply date grouping.",
                target_scope=f"visual:{visual_id}",
            )

        before_dims = [
            {
                "block_id": d.block_id,
                "column_name": d.column_name,
                "alias": d.alias,
                "truncate_date_to": d.truncate_date_to,
            }
            for d in visual.query.dimensions
        ]
        after_dims = [
            {
                "block_id": d.block_id,
                "column_name": d.column_name,
                "alias": d.alias if d.column_name != time_column else truncate_to.title(),
                "truncate_date_to": d.truncate_date_to if d.column_name != time_column else truncate_to,
            }
            for d in visual.query.dimensions
        ]

        path = f"pages/{page_id}/visuals/{visual_id}/query/dimensions"
        notes = [
            f"Grounded to visual '{visual_id}', time column '{time_column}'.",
            f"Applying date truncation: {truncate_to}.",
            "This change affects the query grouping — numbers will update after approval.",
        ]
        proposal = ReportProposal(
            description=f"Group by {truncate_to} (truncate {time_column})",
            changes=[
                ReportChange(
                    path=path,
                    label=f"Date grouping → {truncate_to}",
                    before=before_dims,
                    after=after_dims,
                    affects_data=True,
                )
            ],
            target_component_id=visual_id,
        )
        intent = AIIntent(
            intent_kind="analysis_request",
            target_scope=f"visual:{visual_id}",
            suggested_visuals=[visual_id],
            trust_notes=notes,
            risk_level="medium",
        )
        return NL2ProposalResult(
            intent=intent,
            message="Dimension change proposal created. This will re-query after approval.",
            proposal=proposal,
            trust_notes=notes,
            risk_level="medium",
        )

    # ------------------------------------------------------------------
    # Round 019: add_metric intent
    # ------------------------------------------------------------------

    def _add_metric(
        self,
        metric_name: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
        semantic_model: dict[str, Any] | None,
    ) -> NL2ProposalResult:
        found = _find_visual(report, selected_component_id)
        if found is None:
            return self._unsupported(
                "Select a visual before adding a metric.",
                target_scope=_target_scope(selected_component_id),
            )
        page_id, visual_id, visual = found

        # Governance check: metric must exist in semantic model
        sm_metrics = {m["metric_id"]: m for m in (semantic_model or {}).get("metrics", [])}
        if metric_name not in sm_metrics:
            refusal = GovernanceRefusal(
                reason=f"Metric '{metric_name}' is not in the semantic model. "
                       "Only certified metrics may be added to a report.",
                blocked_terms=[metric_name],
                trust_notes=[
                    "The metric was not found in the semantic model's certified metric list.",
                    "Ask your data team to certify this metric before adding it.",
                ],
                risk_level="high",
            )
            intent = AIIntent(
                intent_kind="unsupported",
                target_scope=f"visual:{visual_id}",
                trust_notes=refusal.trust_notes,
                risk_level="high",
            )
            return NL2ProposalResult(
                intent=intent,
                message=refusal.reason,
                refusal=refusal,
                trust_notes=refusal.trust_notes,
                risk_level="high",
            )

        sm_metric = sm_metrics[metric_name]
        owner_block = sm_metric.get("owner_block", "")

        # Governance check: owner_block must match existing visual block
        visual_block_ids = [ref.block_id for ref in visual.query.block_refs]
        if owner_block not in visual_block_ids:
            refusal = GovernanceRefusal(
                reason=(
                    f"Metric '{metric_name}' belongs to block '{owner_block}', "
                    f"which is not in this visual's block refs {visual_block_ids}. "
                    "Cross-block metric addition requires a certified relationship."
                ),
                blocked_terms=[metric_name, owner_block],
                trust_notes=[
                    f"Owner block '{owner_block}' not in visual block refs.",
                    "Add the block to the visual first, or choose a metric from the same block.",
                ],
                risk_level="high",
            )
            intent = AIIntent(
                intent_kind="unsupported",
                target_scope=f"visual:{visual_id}",
                trust_notes=refusal.trust_notes,
                risk_level="high",
            )
            return NL2ProposalResult(
                intent=intent,
                message=refusal.reason,
                refusal=refusal,
                trust_notes=refusal.trust_notes,
                risk_level="high",
            )

        # Governance check: max metrics per visual
        if len(visual.query.metrics) >= _MAX_METRICS_PER_VISUAL:
            return self._unsupported(
                f"This visual already has {len(visual.query.metrics)} metrics "
                f"(maximum {_MAX_METRICS_PER_VISUAL}). Remove one before adding another.",
                target_scope=f"visual:{visual_id}",
            )

        # Check not already present
        if any(m.metric_name == metric_name for m in visual.query.metrics):
            return self._unsupported(
                f"Metric '{metric_name}' is already in this visual.",
                target_scope=f"visual:{visual_id}",
            )

        before_metrics = [
            {
                "block_id": m.block_id,
                "metric_name": m.metric_name,
                "alias": m.alias,
                "agg_override": m.agg_override.value if m.agg_override else None,
            }
            for m in visual.query.metrics
        ]
        new_metric = {"block_id": owner_block, "metric_name": metric_name, "alias": None, "agg_override": None}
        after_metrics = before_metrics + [new_metric]

        path = f"pages/{page_id}/visuals/{visual_id}/query/metrics"
        notes = [
            f"Adding certified metric '{metric_name}' from block '{owner_block}'.",
            "This change re-queries the visual after approval.",
        ]
        proposal = ReportProposal(
            description=f"Add metric '{metric_name}' to visual '{visual_id}'",
            changes=[
                ReportChange(
                    path=path,
                    label=f"Add metric: {metric_name}",
                    before=before_metrics,
                    after=after_metrics,
                    affects_data=True,
                )
            ],
            target_component_id=visual_id,
        )
        intent = AIIntent(
            intent_kind="analysis_request",
            target_scope=f"visual:{visual_id}",
            suggested_visuals=[visual_id],
            trust_notes=notes,
            risk_level="medium",
        )
        return NL2ProposalResult(
            intent=intent,
            message=f"Metric '{metric_name}' proposal created. This will re-query after approval.",
            proposal=proposal,
            trust_notes=notes,
            risk_level="medium",
        )

    def _governance_refusal(
        self,
        normalized: str,
        semantic_model: dict[str, Any] | None,
    ) -> GovernanceRefusal | None:
        blocked = [pattern for pattern in _SQL_REFUSAL_PATTERNS if re.search(pattern, normalized)]
        if not blocked:
            return None
        policy_note = "Free-form SQL and detail joins must go through certified semantic workflows."
        prohibited = semantic_model.get("prohibited_paths", []) if semantic_model else []
        if "yield" in normalized and prohibited:
            policy_note = "Yield detail joins are prohibited by the semantic model because they can duplicate quality metrics."
        return GovernanceRefusal(
            reason="This request needs a governed metric or certified relationship workflow and cannot be staged as a draft proposal.",
            blocked_terms=_blocked_terms(normalized),
            trust_notes=[
                policy_note,
                "Ask for a governed analysis plan or select certified metrics/dimensions instead.",
            ],
        )

    def _unsupported(
        self,
        message: str,
        *,
        target_scope: str,
        selection: SemanticSelection | None = None,
    ) -> NL2ProposalResult:
        notes = ["No report changes were staged."]
        intent = AIIntent(
            intent_kind="unsupported",
            target_scope=target_scope,
            selection=selection or SemanticSelection(),
            trust_notes=notes,
            risk_level="medium",
        )
        return NL2ProposalResult(
            intent=intent,
            message=message,
            trust_notes=notes,
            risk_level="medium",
        )


def _normalize(prompt: str) -> str:
    return " ".join(prompt.strip().lower().split())


def _target_scope(selected_component_id: str | None) -> str:
    return f"visual:{selected_component_id}" if selected_component_id else "report"


def _looks_like_style_request(prompt: str, normalized: str) -> bool:
    return (
        any(term in normalized for term in _STYLE_TERMS)
        or any(alias in prompt for alias in _COLOR_ALIASES)
        or "蝝" in prompt
    )


def _looks_like_queue_analysis(normalized: str) -> bool:
    return any(term in normalized for term in _QUEUE_TERMS) and any(term in normalized for term in _ANALYSIS_TERMS)


def _extract_color(prompt: str, normalized: str) -> str | None:
    for source, color_name in _COLOR_ALIASES.items():
        if source in prompt:
            return _COLOR_HEX[color_name]
    if "蝝" in prompt:
        return _COLOR_HEX["red"]
    for name, value in _COLOR_HEX.items():
        if re.search(rf"\b{re.escape(name)}\b", normalized):
            return value
    hex_match = re.search(r"#[0-9a-fA-F]{6}\b", prompt)
    return hex_match.group(0).upper() if hex_match else None


def _find_visual(
    report: ExecutableReportSpec,
    selected_component_id: str | None,
) -> tuple[str, str, ReportVisualSpec] | None:
    if not selected_component_id:
        return None
    for page_id, page in report.pages.items():
        visual = page.visuals.get(selected_component_id)
        if visual is not None:
            return page_id, selected_component_id, visual
    return None


def _selection_from_visual(visual: ReportVisualSpec) -> SemanticSelection:
    metric = visual.query.metrics[0] if visual.query.metrics else None
    dimension = visual.query.dimensions[0] if visual.query.dimensions else None
    filter_spec = visual.query.filters[0] if visual.query.filters else None
    return SemanticSelection(
        metric_block_id=metric.block_id if metric else None,
        metric_name=metric.metric_name if metric else None,
        dimension_block_id=dimension.block_id if dimension else None,
        dimension_name=dimension.column_name if dimension else None,
        filter_block_id=filter_spec.block_id if filter_spec else None,
        filter_name=filter_spec.column_name if filter_spec else None,
        filter_value=filter_spec.value if filter_spec else None,
    )


def _selection_from_semantic_model(semantic_model: dict[str, Any] | None) -> SemanticSelection:
    for metric in (semantic_model or {}).get("metrics", []):
        metric_id = metric.get("metric_id", "")
        if "queue" in metric_id:
            return SemanticSelection(
                metric_block_id=metric.get("owner_block"),
                metric_name=metric_id,
            )
    return SemanticSelection(metric_block_id="process_move_fact", metric_name="queue_time_hr")


def _first_queue_visual(report: ExecutableReportSpec) -> tuple[str, str, ReportVisualSpec] | None:
    for page_id, page in report.pages.items():
        for visual_id, visual in page.visuals.items():
            if _visual_mentions_queue(visual_id, visual):
                return page_id, visual_id, visual
    return None


def _queue_visual_ids(report: ExecutableReportSpec) -> list[str]:
    return [
        visual_id
        for page in report.pages.values()
        for visual_id, visual in page.visuals.items()
        if _visual_mentions_queue(visual_id, visual)
    ]


def _visual_mentions_queue(visual_id: str, visual: ReportVisualSpec) -> bool:
    title = visual.visualization.title or ""
    metric_names = " ".join(metric.metric_name for metric in visual.query.metrics)
    return "queue" in f"{visual_id} {title} {metric_names}".lower()


# ---------------------------------------------------------------------------
# Round 019: Detection helpers for new intents
# ---------------------------------------------------------------------------

def _looks_like_chart_type_change(prompt: str, normalized: str) -> bool:
    """Detect requests to change chart type: bar chart, line chart, 折線圖, 長條圖."""
    chart_keywords = ("bar chart", "line chart", "長條圖", "柱狀圖", "折線圖", "trend chart")
    change_keywords = ("change", "convert", "switch", "改成", "換成", "轉成", "改為", "換為")
    has_chart = any(k in normalized or k in prompt for k in chart_keywords)
    has_change = any(k in normalized or k in prompt for k in change_keywords)
    # Also match "bar" or "line" with explicit change intent
    if has_chart and has_change:
        return True
    # Chinese patterns: 把...改成長條圖
    if re.search(r"(改|換|轉)(成|為|做)\s*(長條圖|折線圖|bar|line)", prompt):
        return True
    return False


def _extract_chart_type(prompt: str, normalized: str) -> VisualType | None:
    """Extract the target chart type from a change request."""
    for keyword, vtype in _CHART_TYPE_KEYWORDS.items():
        if keyword in normalized or keyword in prompt:
            return vtype
    return None


def _looks_like_dimension_change(prompt: str, normalized: str) -> bool:
    """Detect requests to change date grouping: 月份, week, daily, etc."""
    granularity_terms = list(_DIMENSION_DATE_KEYWORDS.keys())
    group_terms = ("group by", "groupby", "按", "改用", "以", "用", "分組", "分析")
    has_granularity = any(k in normalized or k in prompt for k in granularity_terms)
    has_group = any(k in normalized or k in prompt for k in group_terms)
    return has_granularity and has_group


def _extract_date_granularity(prompt: str, normalized: str) -> str | None:
    """Extract date truncation value: 'month', 'week', 'day', 'quarter', 'year'."""
    for keyword, granularity in _DIMENSION_DATE_KEYWORDS.items():
        if keyword in normalized or keyword in prompt:
            return granularity
    return None


def _find_time_column(visual: ReportVisualSpec) -> str | None:
    """Find the first dimension column that looks like a time/date column."""
    time_suffixes = ("date", "time", "day", "month", "year", "ts", "at", "_dt",
                     "日期", "時間", "日", "月", "年")
    for dim in visual.query.dimensions:
        col = dim.column_name.lower()
        if any(col.endswith(s) or s in col for s in time_suffixes):
            return dim.column_name
    # If no obvious time column, return the first dimension column
    if visual.query.dimensions:
        return visual.query.dimensions[0].column_name
    return None


def _extract_add_metric_name(prompt: str, normalized: str) -> str | None:
    """Extract a metric name from an add-metric request."""
    for pattern in _METRIC_ADD_PATTERNS:
        match = re.search(pattern, prompt, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    # Also try: "也顯示 move_count"
    match = re.search(r"也\s*(顯示|加入|加)\s*(\w+)", prompt)
    if match:
        return match.group(2).strip()
    return None


def _blocked_terms(normalized: str) -> list[str]:
    terms = []
    for term in ("sql", "join", "yield", "detail", "raw"):
        if term in normalized:
            terms.append(term)
    return terms


# ---------------------------------------------------------------------------
# Round 020: Date filter detection helpers
# ---------------------------------------------------------------------------

def _looks_like_date_filter(prompt: str, normalized: str) -> bool:
    """Detect relative date period requests."""
    # Direct keyword match (fast path)
    for keyword in _DATE_FILTER_PERIOD_MAP:
        if keyword.lower() in normalized or keyword in prompt:
            return True
    # Trigger term match (broader)
    return any(term.lower() in normalized or term in prompt for term in _DATE_FILTER_TRIGGER_TERMS)


def _extract_date_period(prompt: str, normalized: str) -> str | None:
    """Extract the canonical period key from a date filter request."""
    # Check exact keyword match first (longest match wins)
    best_match: str | None = None
    best_len = 0
    for keyword, period in _DATE_FILTER_PERIOD_MAP.items():
        kw_lower = keyword.lower()
        if kw_lower in normalized or keyword in prompt:
            if len(keyword) > best_len:
                best_match = period
                best_len = len(keyword)
    return best_match
