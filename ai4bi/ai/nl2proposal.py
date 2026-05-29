"""NL-to-proposal service for governed BI workflows.

Routing modes
-------------
LLM_MODE=mock (default)
    Deterministic keyword routing — no API calls, works in CI/offline.

LLM_MODE=anthropic + ANTHROPIC_API_KEY set
    Claude classifies the intent; the existing handler methods enforce
    governance (no SQL, certified-only metrics, etc.).  Falls back to
    keyword routing if the API call fails.
"""

from __future__ import annotations

import re
from typing import Any

from ai4bi.ai.intent_models import (
    AIIntent,
    AnalysisPlan,
    DirectAnswer,
    GovernanceRefusal,
    NL2ProposalResult,
    SemanticSelection,
)
from ai4bi.ai.llm_adapter import LLMAdapter
from ai4bi.ai.schema_index import SchemaIndex  # Round 035: dynamic schema lookup
from ai4bi.query_spec import AggFunction, DimensionRef, MetricRef, VisualType
from ai4bi.report.models import ExecutableReportSpec, ReportChange, ReportProposal, ReportVisualSpec

# ---------------------------------------------------------------------------
# Round 027: Visual Composer — dimension keyword → (block_id, column, alias, truncate)
# ---------------------------------------------------------------------------
_DIM_KEYWORD_MAP: dict[str, tuple[str, str, str, str | None]] = {
    "月份": ("process_move_fact", "event_date", "Month", "month"),
    "月": ("process_move_fact", "event_date", "Month", "month"),
    "month": ("process_move_fact", "event_date", "Month", "month"),
    "weekly": ("process_move_fact", "event_date", "Week", "week"),
    "week": ("process_move_fact", "event_date", "Week", "week"),
    "週": ("process_move_fact", "event_date", "Week", "week"),
    "day": ("process_move_fact", "event_date", "Date", "day"),
    "daily": ("process_move_fact", "event_date", "Date", "day"),
    "日": ("process_move_fact", "event_date", "Date", "day"),
    "date": ("process_move_fact", "event_date", "Date", None),
    "vendor": ("tool_dim", "vendor", "Vendor", None),
    "供應商": ("tool_dim", "vendor", "Vendor", None),
    "廠商": ("tool_dim", "vendor", "Vendor", None),
    "tool": ("tool_dim", "tool_id", "Tool ID", None),
    "tool_id": ("tool_dim", "tool_id", "Tool ID", None),
    "工具": ("tool_dim", "tool_id", "Tool ID", None),
    "機台": ("tool_dim", "tool_id", "Tool ID", None),
    "step": ("process_step_dim", "step_name", "Step", None),
    "step_id": ("process_move_fact", "step_id", "Step ID", None),
    "製程": ("process_step_dim", "step_name", "Step", None),
    "product": ("lot_dim", "product_family", "Product Family", None),
    "product_family": ("lot_dim", "product_family", "Product Family", None),
    "產品": ("lot_dim", "product_family", "Product Family", None),
}

# ---------------------------------------------------------------------------
# Round 019: Chart-type change mappings
# Safe transitions: bar ↔ line only. table/kpi_card require different query
# contracts and are blocked (design-council 003-E safety review).
# ---------------------------------------------------------------------------

_CHART_TYPE_SAFE_TRANSITIONS: dict[VisualType, VisualType] = {
    VisualType.bar_chart:  VisualType.line_chart,
    VisualType.line_chart: VisualType.bar_chart,
    VisualType.pie_chart:  VisualType.bar_chart,
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
    "pie": VisualType.pie_chart,
    "pie chart": VisualType.pie_chart,
    "donut": VisualType.pie_chart,
    "圓餅圖": VisualType.pie_chart,
    "甜甜圈圖": VisualType.pie_chart,
    "scatter": VisualType.scatter,
    "scatter chart": VisualType.scatter,
    "散點圖": VisualType.scatter,
    "散佈圖": VisualType.scatter,
}

# Round 067: keyword → type for the *add a new visual* path (superset of
# _CHART_TYPE_KEYWORDS; KPI/table aren't valid in-place chart-type *changes*,
# but you can add them as new visuals). Kept separate so chart_type_change is
# unaffected.
_ADD_VISUAL_TYPE_KEYWORDS: dict[str, VisualType] = {
    **_CHART_TYPE_KEYWORDS,
    "kpi": VisualType.kpi_card,
    "kpi card": VisualType.kpi_card,
    "kpi 卡": VisualType.kpi_card,
    "看板": VisualType.kpi_card,
    "指標卡": VisualType.kpi_card,
    "table": VisualType.table,
    "資料表": VisualType.table,
    "表格": VisualType.table,
    "明細表": VisualType.table,
    "pivot": VisualType.pivot,
    "matrix": VisualType.pivot,
    "樞紐": VisualType.pivot,
    "樞紐表": VisualType.pivot,
    "交叉表": VisualType.pivot,
    "矩陣": VisualType.pivot,
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
    r"也顯示\s*(\w+)",
    r"add\s+metric\s+(\w+)",
    r"add\s+(\w+)\s*metric",
    r"add\s+the\s+(\w+)\s*metric",
    r"add\s+(\w+)\s+to\s+(?:this|the)\s+(?:chart|visual|graph)",
    r"include\s+(\w+)\s*metric",
    r"also\s+show\s+(\w+)",
    r"show\s+(?:also\s+)?(\w+)\s*metric",
    # Simple "add X" where X looks like a metric name (snake_case or known term)
    r"^add\s+(\w+(?:_\w+)+)$",           # "add move_count" (snake_case)
    r"^add\s+(move_count|queue_time|process_time|failed_wafer|weighted_yield)\b",
)

_REMOVE_METRIC_PATTERNS = (
    r"remove\s+(\w+)",
    r"delete\s+(\w+)\s*metric",
    r"移除\s*(\w+)",
    r"刪除\s*(\w+)\s*指標",
    r"drop\s+(\w+)\s*metric",
    r"取消\s*(\w+)\s*指標",
    r"hide\s+(\w+)\s*metric",
)

_RENAME_VISUAL_PATTERNS = (
    r"rename\s+(?:this\s+)?(?:chart|visual|graph)\s+to\s+[\"']?(.+?)[\"']?$",
    r"把[這这](?:張|个)?圖(?:改名|命名)(?:叫|為|成)\s*[\"']?(.+?)[\"']?$",
    r"change\s+(?:the\s+)?title\s+to\s+[\"']?(.+?)[\"']?$",
    r"set\s+title\s+(?:to\s+)?[\"']?(.+?)[\"']?$",
    r"名稱改成\s*[\"']?(.+?)[\"']?$",
    r"改名叫\s*[\"']?(.+?)[\"']?$",
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

    When LLM_MODE=anthropic and ANTHROPIC_API_KEY is set, Claude is used to
    classify the intent; the existing handler methods still enforce all
    governance rules (no SQL, certified-only paths, etc.).

    In all other cases the service falls back to the deterministic keyword
    router, ensuring offline / CI operation with zero external dependencies.
    """

    def propose(
        self,
        prompt: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None = None,
        semantic_model: dict[str, Any] | None = None,
        contracts: dict[str, Any] | None = None,
        executor: Any = None,
    ) -> NL2ProposalResult:
        # Round 078: an executor lets the answer-engine compute a real number
        # through the governed query path. Stashed on self for the duration of
        # this call so the existing handler signatures stay untouched.
        self._executor = executor
        normalized = _normalize(prompt)
        if not normalized:
            return self._unsupported(
                "Enter a governed BI request.",
                target_scope=_target_scope(selected_component_id),
            )

        # Governance hard-block runs before any routing (LLM or keyword).
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

        # --- LLM-assisted intent classification (when enabled) ---
        try:
            classification = LLMAdapter().classify(
                prompt, report, selected_component_id, semantic_model=semantic_model
            )
            if classification.mode == "llm":
                result = self._dispatch_llm_intent(
                    classification, prompt, normalized, report,
                    selected_component_id, semantic_model, contracts,
                )
                if result is not None:
                    return result
                # None = LLM returned an intent we couldn't route; fall through
        except Exception:  # noqa: BLE001
            pass  # Any adapter failure → keyword fallback

        return self._keyword_propose(
            prompt, normalized, report, selected_component_id, semantic_model, contracts
        )

    # ------------------------------------------------------------------
    # LLM intent dispatcher
    # ------------------------------------------------------------------

    def _build_single_proposal(
        self,
        intent: str,
        params: dict,
        prompt: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
        semantic_model: dict[str, Any] | None,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Build a single proposal for one intent+params pair (used by mixed dispatch)."""
        clf = type("_C", (), {"intent": intent, "parameters": params, "mode": "llm",
                              "secondary_intent": None, "secondary_parameters": {}})()
        return self._dispatch_llm_intent(
            clf, prompt, _normalize(prompt), report, selected_component_id, semantic_model, contracts
        )

    def _dispatch_llm_intent(
        self,
        classification: Any,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
        semantic_model: dict[str, Any] | None,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Route an LLM IntentClassification to the appropriate handler.

        Returns None to signal the caller should fall through to keyword routing.
        """
        intent = classification.intent
        params = classification.parameters or {}

        # ------------------------------------------------------------------ #
        # Mixed-prompt: split into two proposals when LLM returns secondary_intent
        # ------------------------------------------------------------------ #
        secondary_intent = getattr(classification, "secondary_intent", None)
        if secondary_intent and secondary_intent != intent:
            secondary_params = getattr(classification, "secondary_parameters", {}) or {}
            primary_result = self._build_single_proposal(
                intent, params, prompt, report, selected_component_id, semantic_model, contracts
            )
            secondary_result = self._build_single_proposal(
                secondary_intent, secondary_params, prompt, report,
                selected_component_id, semantic_model, contracts
            )
            proposals = tuple(
                r.proposal for r in (primary_result, secondary_result)
                if r is not None and r.proposal is not None
            )
            if len(proposals) == 2:
                style_intents = {"style_change", "chart_type_change", "rename_visual"}
                if intent not in style_intents:
                    proposals = (proposals[1], proposals[0])  # style first
                notes = [
                    "Mixed prompt detected: style and analysis changes separated.",
                    "Apply them individually or together.",
                ]
                mixed_intent = AIIntent(
                    intent_kind="analysis_request",
                    target_scope=_target_scope(selected_component_id),
                    trust_notes=notes,
                    risk_level="medium",
                )
                return NL2ProposalResult(
                    intent=mixed_intent,
                    message="Mixed prompt: style and analysis proposals split. Apply each separately or together.",
                    split_proposals=proposals,
                    trust_notes=notes,
                    risk_level="medium",
                )
            elif len(proposals) == 1:
                result = primary_result if (primary_result and primary_result.proposal) else secondary_result
                return result

        # ------------------------------------------------------------------ #
        # Single intent dispatch
        # ------------------------------------------------------------------ #
        if intent == "style_change":
            color_name = params.get("color", "")
            augmented = f"{prompt} {color_name}" if color_name else prompt
            return self._style_change(augmented, _normalize(augmented), report, selected_component_id)

        if intent == "chart_type_change":
            target = params.get("target_type", "")
            augmented = f"change to {target}" if target else prompt
            return self._chart_type_change(augmented, _normalize(augmented), report, selected_component_id)

        if intent == "dimension_change":
            granularity = params.get("granularity", "")
            augmented = f"group by {granularity}" if granularity else prompt
            return self._dimension_change(augmented, _normalize(augmented), report, selected_component_id)

        if intent == "add_metric":
            metric_name = params.get("metric_name")
            if metric_name:
                return self._add_metric(metric_name, report, selected_component_id, semantic_model)

        if intent == "remove_metric":
            metric_name = params.get("metric_name")
            if metric_name:
                return self._remove_metric(metric_name, report, selected_component_id)

        if intent == "rename_visual":
            new_title = params.get("new_title")
            if new_title:
                augmented = f"rename this chart to \"{new_title}\""
                return self._rename_visual(augmented, _normalize(augmented), report, selected_component_id)

        if intent == "categorical_dimension_change":
            dim_keyword = params.get("dimension_keyword", "")
            cat_dim = _CATEGORICAL_DIM_MAP.get(dim_keyword.lower()) or _extract_categorical_dimension(
                f"group by {dim_keyword}", f"group by {dim_keyword.lower()}"
            )
            if cat_dim:
                return self._categorical_dimension_change(cat_dim, report, selected_component_id, semantic_model)

        if intent == "value_filter_change":
            filter_values = params.get("filter_values")
            if filter_values:
                values_upper = [v.upper() for v in filter_values]
                col_name = "step_id"
                for v in values_upper:
                    if v.lower() in _VALUE_FILTER_MAP:
                        _, col_name = _VALUE_FILTER_MAP[v.lower()]
                        break
                return self._value_filter_change(col_name, values_upper, report, selected_component_id, semantic_model)

        if intent == "date_filter_change":
            period_raw = params.get("period", "")
            augmented = period_raw if period_raw else prompt
            return self._date_filter_change(augmented, _normalize(augmented), report)

        if intent == "answer_metric":  # Round 078
            answer = self._answer_metric(prompt, normalized, report, semantic_model, contracts)
            if answer is not None:
                return answer

        if intent == "queue_analysis":
            return self._queue_time_plan(prompt, report, selected_component_id, semantic_model, contracts)

        if intent == "add_visual":
            return self._add_visual_nl(params, report, semantic_model, contracts)

        if intent == "highlight_outliers":
            return self._highlight_outliers(params, report, selected_component_id)

        if intent == "add_trend_line":
            return self._add_trend_line(params, report, selected_component_id)

        if intent == "unsupported":
            reason = params.get("reason", "No supported governed BI intent was detected.")
            disam = getattr(classification, "disambiguation", None)
            return self._unsupported(
                reason, target_scope=_target_scope(selected_component_id),
                disambiguation=disam,
            )

        return None  # Unknown intent → fall through to keyword routing

    # ------------------------------------------------------------------
    # Keyword-based routing (unchanged from Round 022)
    # ------------------------------------------------------------------

    def _keyword_propose(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
        semantic_model: dict[str, Any] | None,
        contracts: dict[str, Any] | None,
    ) -> NL2ProposalResult:
        # Round 078: direct-answer engine. A *question* ("上個月營收多少？",
        # "how much revenue") asks for a number, not a canvas edit — answer it
        # before any edit-intent routing. Gated on explicit question markers so
        # imperative edit commands ("加一張營收圖") are never intercepted.
        if _looks_like_metric_question(prompt, normalized):
            answer = self._answer_metric(prompt, normalized, report, semantic_model, contracts)
            if answer is not None:
                return answer

        # Round 066: "add a trend line / 趨勢線" overlay (keyword mode). Checked
        # before add_visual since it is a more specific phrase.
        if _looks_like_add_trend_line(prompt, normalized):
            return self._add_trend_line({}, report, selected_component_id)

        # Round 065: "add a pie/bar/line chart" creates a NEW visual (keyword mode).
        # Checked before chart_type_change; the add-verb vs change-verb split keeps
        # them disjoint.
        if _looks_like_add_visual(prompt, normalized):
            return self._add_visual_keyword(
                prompt, normalized, report, selected_component_id, semantic_model, contracts
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

        # Rename must be checked first — "rename this chart to Queue Trend" contains
        # "queue" + "trend" which would otherwise trigger queue_analysis.
        if _looks_like_rename_visual(prompt, normalized):
            return self._rename_visual(prompt, normalized, report, selected_component_id)

        # Queue analysis must be checked BEFORE categorical/value-filter to avoid
        # "analyze queue time drivers by tool" being intercepted by _CAT_DIM_TRIGGERS.
        if _looks_like_queue_analysis(normalized):
            return self._queue_time_plan(prompt, report, selected_component_id, semantic_model, contracts)

        remove_metric_name = _extract_remove_metric_name(prompt, normalized)
        if remove_metric_name is not None:
            return self._remove_metric(remove_metric_name, report, selected_component_id)

        # Round 035: pass contracts for dynamic schema fallback
        cat_dim = _extract_categorical_dimension(prompt, normalized, contracts)
        if cat_dim is not None:
            return self._categorical_dimension_change(cat_dim, report, selected_component_id, semantic_model)

        value_filter = _extract_value_filter(prompt, normalized)
        if value_filter is not None:
            col_name, values = value_filter
            return self._value_filter_change(col_name, values, report, selected_component_id, semantic_model)

        # Round 036: period-over-period comparison
        if _looks_like_period_comparison(prompt, normalized):
            return self._period_comparison(prompt, normalized, report, selected_component_id, contracts)

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

    # ------------------------------------------------------------------
    # Round 036: period_comparison — create two KPI cards for current vs prev period
    # ------------------------------------------------------------------

    def _add_visual_keyword(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
        semantic_model: dict[str, Any] | None,
        contracts: dict[str, Any] | None,
    ) -> NL2ProposalResult:
        """Round 065: add a new chart of the requested type (keyword mode).

        Picks a sensible metric (from the selected/first visual) and dimension
        (date for line, a low-cardinality category for bar/pie) so it works even
        when the user only says "add a pie chart".
        """
        from ai4bi.report.builder import build_add_visual_proposal
        from ai4bi.query_spec import (
            BlockRef, DimensionRef, SortDirection, SortSpec, VisualQuerySpec, VisualizationSpec,
        )

        vtype = VisualType.bar_chart
        for kw, vt in _ADD_VISUAL_TYPE_KEYWORDS.items():
            if kw in normalized or kw in prompt:
                vtype = vt
                break

        # Source metric + block: prefer the selected visual, else the first visual
        # in the report that has a metric.
        found = _find_visual(report, selected_component_id)
        page_id, metric, block_id = "main", None, None
        if found and found[2].query.metrics:
            page_id, _vid, v = found
            metric, block_id = v.query.metrics[0], v.query.metrics[0].block_id
        else:
            for pid, page in report.pages.items():
                for v in page.visuals.values():
                    if v.query.metrics:
                        page_id, metric, block_id = pid, v.query.metrics[0], v.query.metrics[0].block_id
                        break
                if metric:
                    break
        if metric is None or block_id is None:
            return self._unsupported("找不到可用的指標來建立圖表。", target_scope="canvas")

        metric_alias = metric.alias or metric.metric_name

        # Pick dimensions from the block's contract.
        date_col, cat_cols = None, []
        contract = (contracts or {}).get(block_id)
        if contract is not None:
            pk = set(getattr(contract, "primary_keys", []) or [])
            for col in contract.columns:
                nm, dt = col.name, col.data_type
                low = nm.lower()
                if date_col is None and (dt in ("date", "timestamp")
                                         or any(t in low for t in ("date", "time", "_dt", "day"))):
                    date_col = nm
                if (dt in ("string", "str", "object") and nm not in pk
                        and not (low == "id" or low.endswith(("_id", "_code", "_sku")))
                        and len(cat_cols) < 2):
                    cat_cols.append(nm)
        cat_col = cat_cols[0] if cat_cols else None

        dimensions, sort = [], []
        truncate = None
        if vtype == VisualType.pivot and len(cat_cols) >= 2:
            dimensions = [DimensionRef(block_id, cat_cols[0], cat_cols[0]),
                          DimensionRef(block_id, cat_cols[1], cat_cols[1])]
        elif vtype == VisualType.kpi_card:
            pass  # no dimension
        elif vtype == VisualType.line_chart and date_col:
            dimensions = [DimensionRef(block_id, date_col, date_col, truncate_date_to="week")]
            sort = [SortSpec(date_col, SortDirection.asc)]
            truncate = "week"
        elif cat_col:
            dimensions = [DimensionRef(block_id, cat_col, cat_col)]
            sort = [SortSpec(metric_alias, SortDirection.desc)]
        elif date_col:  # fall back to date if no categorical column
            dimensions = [DimensionRef(block_id, date_col, date_col)]

        # Unique visual id
        base_vid = f"{vtype.value}_{metric.metric_name}"
        existing = {vid for p in report.pages.values() for vid in p.visuals}
        vid, c = base_vid, 1
        while vid in existing:
            vid = f"{base_vid}_{c}"; c += 1

        query = VisualQuerySpec(
            spec_id=vid,
            block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric.metric_name, metric_alias)],
            dimensions=dimensions,
            sort=sort,
            inherit_global_filter=True,
        )
        _type_label = {
            VisualType.pie_chart: "圓餅圖", VisualType.bar_chart: "長條圖",
            VisualType.line_chart: "折線圖", VisualType.scatter: "散點圖",
            VisualType.kpi_card: "KPI", VisualType.table: "表格",
            VisualType.pivot: "樞紐表",
        }.get(vtype, vtype.value)
        viz = VisualizationSpec(vtype, title=f"{metric_alias}（{_type_label}）", extra={})
        proposal = build_add_visual_proposal(page_id, vid, query, viz)

        notes = [
            f"新增一個{_type_label}，指標：{metric_alias}（來源：{block_id}）。",
        ]
        if dimensions:
            notes.append(f"維度：{dimensions[0].column_name}" + ("（依週彙總）" if truncate else ""))
        intent = AIIntent(
            intent_kind="add_visual",
            target_scope=f"page:{page_id}",
            trust_notes=notes,
            risk_level="low",
        )
        return NL2ProposalResult(
            intent=intent,
            message=f"已準備新增一個{_type_label}：{metric_alias}。",
            proposal=proposal,
            trust_notes=notes,
            risk_level="low",
        )

    def _period_comparison(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
        contracts: dict[str, Any] | None,
    ) -> NL2ProposalResult:
        """Add two side-by-side KPI cards: current period vs previous period."""
        from ai4bi.report.builder import build_add_visual_proposal
        from ai4bi.query_spec import BlockRef, FilterOperator, FilterSpec, VisualQuerySpec, VisualizationSpec
        from ai4bi.report.models import ReportVisualSpec
        import datetime

        period, period_label, prev_label = _extract_comparison_period(normalized, prompt)

        # Find the primary fact block and first SUM metric from the current visual or report
        found = _find_visual(report, selected_component_id)
        if found is None:
            # Use first visual in report
            for page in report.pages.values():
                for vid, v in page.visuals.items():
                    if v.query.metrics:
                        found = (list(report.pages.keys())[0], vid, v)
                        break
                if found:
                    break
        if found is None:
            return self._unsupported("找不到可以用於比較的圖表，請先選擇一個圖表。", target_scope="canvas")

        page_id, _vid, visual = found
        if not visual.query.metrics:
            return self._unsupported("所選圖表沒有指標，無法建立比較。", target_scope=f"visual:{_vid}")

        metric = visual.query.metrics[0]
        fact_block = metric.block_id
        today = datetime.date.today()

        if period == "week":
            start_curr = today - datetime.timedelta(days=today.weekday())
            start_prev = start_curr - datetime.timedelta(weeks=1)
            end_prev = start_curr - datetime.timedelta(days=1)
        elif period == "month":
            start_curr = today.replace(day=1)
            prev_month = (start_curr - datetime.timedelta(days=1)).replace(day=1)
            start_prev = prev_month
            end_prev = start_curr - datetime.timedelta(days=1)
        else:  # default: last 7 days vs prev 7 days
            start_curr = today - datetime.timedelta(days=6)
            start_prev = start_curr - datetime.timedelta(days=7)
            end_prev = start_curr - datetime.timedelta(days=1)

        # Find the date column in the fact block
        date_col = None
        if contracts and fact_block in contracts:
            for col in contracts[fact_block].columns:
                if col.data_type in ("date", "timestamp") or any(
                    t in col.name.lower() for t in ("date", "time", "dt", "ts", "day")
                ):
                    date_col = col.name
                    break

        existing = set(report.pages.get("main", type("_", (), {"visuals": {}})()).visuals.keys())
        proposals = []
        for label, start, end in [
            (period_label, start_curr, today),
            (prev_label, start_prev, end_prev),
        ]:
            vid = f"kpi_cmp_{metric.metric_name}_{label.replace(' ', '_')}"
            c = 1
            while vid in existing:
                vid = f"kpi_cmp_{metric.metric_name}_{label.replace(' ', '_')}_{c}"; c += 1
            existing.add(vid)

            filters = []
            if date_col:
                filters = [
                    FilterSpec(fact_block, date_col, FilterOperator.gte, str(start), False),
                    FilterSpec(fact_block, date_col, FilterOperator.lte, str(end), False),
                ]

            q = VisualQuerySpec(
                spec_id=vid,
                block_refs=[BlockRef(fact_block)],
                metrics=[MetricRef(fact_block, metric.metric_name, f"{metric.alias or metric.metric_name}")],
                filters=filters,
                inherit_global_filter=False,
            )
            v = VisualizationSpec(VisualType.kpi_card, title=f"{label}", extra={})
            rv = ReportVisualSpec(vid, q, v, col_span=6)
            proposals.append(build_add_visual_proposal(page_id, vid, q, v))

        from dataclasses import replace as _replace
        # Apply both proposals
        notes = [
            f"建立兩個 KPI 看板比較 {period_label} vs {prev_label}。",
            f"指標：{metric.alias or metric.metric_name}（來源：{fact_block}）",
            "日期過濾器已嵌入各 KPI 看板，不影響其他圖表。",
        ]

        # Merge two proposals into one by combining their changes
        all_changes = proposals[0].changes + proposals[1].changes
        merged = ReportProposal(
            description=f"Period comparison: {period_label} vs {prev_label}",
            changes=all_changes,
        )

        intent = AIIntent(
            intent_kind="analysis_request",
            target_scope=f"page:{page_id}",
            trust_notes=notes,
            risk_level="low",
        )
        return NL2ProposalResult(
            intent=intent,
            message=f"已建立 {period_label} vs {prev_label} 的比較 KPI。",
            proposal=merged,
            trust_notes=notes,
            risk_level="low",
        )

    def _answer_metric(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        semantic_model: dict[str, Any] | None,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 078: answer a metric question with a real, sourced number.

        Resolves the metric from the certified schema, runs it through the
        governed executor (whole-period total, or current-vs-previous trailing
        window when a time phrase is present), and returns a one-sentence answer
        plus a one-click "add as KPI" proposal. Returns None to fall through to
        edit-intent routing when no metric resolves or no executor is wired.
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None

        idx = SchemaIndex.build(contracts)
        match = idx.best_metric_match(prompt, normalized)
        if match is None:
            return None

        block_id, metric_name, alias = match.block_id, match.metric_name, match.alias
        unit = _metric_unit(contracts, block_id, metric_name)
        period = _extract_answer_period(normalized, prompt)
        date_col = _find_date_column(contracts, block_id)

        from ai4bi.query_spec import BlockRef, VisualQuerySpec

        base = VisualQuerySpec(
            spec_id=f"nl_answer_{metric_name}",
            block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            inherit_global_filter=False,
        )

        notes = [
            f"指標「{alias}」來自認證語意層（{metric_name} @ {block_id}），未產生自由 SQL。",
            "數字由治理查詢路徑即時計算，與儀表板 KPI 同源。",
        ]

        value: float | None = None
        previous: float | None = None
        delta_pct: float | None = None
        cur_label = prev_label = ""

        if period != "all" and date_col is not None:
            from ai4bi.analysis.time_intelligence import compute_period_comparison

            comp = compute_period_comparison(
                executor, base, date_block_id=block_id, date_column=date_col,
                period=period, metric_col=alias,
            )
            if comp is not None and comp.current is not None:
                value, previous = comp.current, comp.previous
                delta_pct = comp.delta_pct
                cur_label, prev_label = comp.current_label, comp.previous_label
                notes.append(f"比較窗：{cur_label} vs {prev_label}（錨定資料最新日期）。")
            else:
                # No usable date/anchor — degrade to whole-period total.
                period = "all"

        if value is None and period == "all":
            try:
                df = executor.run(base)
            except Exception:  # noqa: BLE001
                return None
            value = _first_scalar(df, alias)

        if value is None:
            return None

        sentence = _compose_answer_sentence(
            alias, value, unit, period, previous, delta_pct, cur_label, prev_label
        )

        answer = DirectAnswer(
            question=prompt.strip(),
            metric_block_id=block_id,
            metric_name=metric_name,
            metric_alias=alias,
            sentence=sentence,
            value=value,
            period=period,
            previous=previous,
            delta_pct=delta_pct,
            current_label=cur_label,
            previous_label=prev_label,
            unit=unit,
            trust_notes=notes,
        )

        # One-click "add as KPI" — reuse the governed add-visual proposal path.
        proposal = self._build_answer_kpi_proposal(report, block_id, metric_name, alias, period, date_col)

        intent = AIIntent(
            intent_kind="analysis_request",
            target_scope="semantic_model",
            selection=SemanticSelection(metric_block_id=block_id, metric_name=metric_name),
            trust_notes=notes,
            risk_level="low",
        )
        return NL2ProposalResult(
            intent=intent,
            message=sentence,
            proposal=proposal,
            direct_answer=answer,
            trust_notes=notes,
            risk_level="low",
        )

    def _build_answer_kpi_proposal(
        self,
        report: ExecutableReportSpec,
        block_id: str,
        metric_name: str,
        alias: str,
        period: str,
        date_col: str | None,
    ) -> "ReportProposal | None":
        """Build an optional 'add this answer as a KPI card' proposal."""
        try:
            from ai4bi.report.builder import build_add_visual_proposal
            from ai4bi.query_spec import BlockRef, VisualQuerySpec, VisualizationSpec

            page_id = "main" if "main" in report.pages else next(iter(report.pages), None)
            if page_id is None:
                return None
            existing = set(report.pages[page_id].visuals.keys())
            vid = f"kpi_answer_{metric_name}"
            c = 1
            while vid in existing:
                vid = f"kpi_answer_{metric_name}_{c}"; c += 1

            q = VisualQuerySpec(
                spec_id=vid,
                block_refs=[BlockRef(block_id)],
                metrics=[MetricRef(block_id, metric_name, alias)],
                inherit_global_filter=False,
            )
            title = f"{alias}" if period == "all" else f"{alias}（{_PERIOD_TITLE.get(period, period)}）"
            v = VisualizationSpec(VisualType.kpi_card, title=title, extra={})
            return build_add_visual_proposal(page_id, vid, q, v)
        except Exception:  # noqa: BLE001 — the answer itself must not depend on this
            return None

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
    # Round 022: rename_visual intent
    # ------------------------------------------------------------------

    def _rename_visual(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
    ) -> NL2ProposalResult:
        found = _find_visual(report, selected_component_id)
        if found is None:
            return self._unsupported(
                "Select a visual before renaming it.",
                target_scope=_target_scope(selected_component_id),
            )
        page_id, visual_id, visual = found
        new_title = _extract_rename_title(prompt, normalized)
        if new_title is None or not new_title.strip():
            return self._unsupported(
                "Specify the new chart name, e.g. 'rename this chart to Queue Trend'.",
                target_scope=f"visual:{visual_id}",
            )
        # XSS-safe: strip HTML tags and limit length
        import html
        new_title = re.sub(r"<[^>]+>", "", new_title).strip()[:80]
        if not new_title:
            return self._unsupported("Chart name must not be empty.", target_scope=f"visual:{visual_id}")
        before_title = visual.visualization.title
        if before_title == new_title:
            return self._unsupported(f"Chart title is already '{new_title}'.", target_scope=f"visual:{visual_id}")
        path = f"pages/{page_id}/visuals/{visual_id}/visualization/title"
        notes = [f"Renaming '{visual_id}' from '{before_title}' to '{new_title}'.", "Display-only change; query is unchanged."]
        proposal = ReportProposal(
            description=f"Rename chart to '{new_title}'",
            changes=[ReportChange(path=path, label="Chart title", before=before_title, after=new_title, affects_data=False)],
            target_component_id=visual_id,
        )
        intent = AIIntent(intent_kind="style_change", target_scope=f"visual:{visual_id}", suggested_visuals=[visual_id], trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=f"Rename proposal created: '{new_title}'.", proposal=proposal, trust_notes=notes, risk_level="low")

    # ------------------------------------------------------------------
    # Round 022: remove_metric intent
    # ------------------------------------------------------------------

    def _remove_metric(
        self,
        metric_name: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
    ) -> NL2ProposalResult:
        found = _find_visual(report, selected_component_id)
        if found is None:
            return self._unsupported("Select a visual before removing a metric.", target_scope=_target_scope(selected_component_id))
        page_id, visual_id, visual = found
        current_names = [m.metric_name for m in visual.query.metrics]
        if metric_name not in current_names:
            return self._unsupported(f"Metric '{metric_name}' is not in this visual.", target_scope=f"visual:{visual_id}")
        if len(visual.query.metrics) <= 1:
            refusal = GovernanceRefusal(
                reason=f"Cannot remove '{metric_name}': a visual must retain at least one metric.",
                blocked_terms=[metric_name],
                trust_notes=["Removing the last metric would create an empty query.", "Add a replacement metric before removing this one."],
                risk_level="medium",
            )
            intent = AIIntent(intent_kind="unsupported", target_scope=f"visual:{visual_id}", trust_notes=refusal.trust_notes, risk_level="medium")
            return NL2ProposalResult(intent=intent, message=refusal.reason, refusal=refusal, trust_notes=refusal.trust_notes, risk_level="medium")
        before = [{"block_id": m.block_id, "metric_name": m.metric_name, "alias": m.alias, "agg_override": m.agg_override.value if m.agg_override else None} for m in visual.query.metrics]
        after = [m for m in before if m["metric_name"] != metric_name]
        path = f"pages/{page_id}/visuals/{visual_id}/query/metrics"
        notes = [f"Removing metric '{metric_name}' from visual '{visual_id}'.", "This change re-queries the visual after approval."]
        proposal = ReportProposal(
            description=f"Remove metric '{metric_name}'",
            changes=[ReportChange(path=path, label=f"Remove metric: {metric_name}", before=before, after=after, affects_data=True)],
            target_component_id=visual_id,
        )
        intent = AIIntent(intent_kind="analysis_request", target_scope=f"visual:{visual_id}", suggested_visuals=[visual_id], trust_notes=notes, risk_level="medium")
        return NL2ProposalResult(intent=intent, message=f"Remove metric proposal created for '{metric_name}'.", proposal=proposal, trust_notes=notes, risk_level="medium")

    # ------------------------------------------------------------------
    # Round 022: categorical_dimension_change intent
    # ------------------------------------------------------------------

    def _categorical_dimension_change(
        self,
        cat_dim: dict,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
        semantic_model: dict[str, Any] | None,
    ) -> NL2ProposalResult:
        found = _find_visual(report, selected_component_id)
        if found is None:
            return self._unsupported("Select a visual before changing the grouping dimension.", target_scope=_target_scope(selected_component_id))
        page_id, visual_id, visual = found
        block_id = cat_dim["block_id"]
        column_name = cat_dim["column_name"]
        alias = cat_dim.get("alias", column_name)
        # Governance: block_id must be in visual's certified dimension targets
        if not visual.query.metrics:
            return self._unsupported("No metrics in this visual; cannot determine dimension block.", target_scope=f"visual:{visual_id}")
        fact_block = visual.query.metrics[0].block_id
        certified = _certified_dim_targets_for_fact(fact_block, semantic_model or {})
        if block_id not in certified and block_id != fact_block:
            refusal = GovernanceRefusal(
                reason=f"Block '{block_id}' is not a certified dimension of '{fact_block}'. Only certified relationships are allowed.",
                blocked_terms=[block_id],
                trust_notes=["Ask your data team to certify this relationship before using it.", "Available certified dimensions: " + ", ".join(sorted(certified))],
                risk_level="high",
            )
            intent = AIIntent(intent_kind="unsupported", target_scope=f"visual:{visual_id}", trust_notes=refusal.trust_notes, risk_level="high")
            return NL2ProposalResult(intent=intent, message=refusal.reason, refusal=refusal, trust_notes=refusal.trust_notes, risk_level="high")
        before_dims = [{"block_id": d.block_id, "column_name": d.column_name, "alias": d.alias, "truncate_date_to": d.truncate_date_to} for d in visual.query.dimensions]
        after_dims = [{"block_id": block_id, "column_name": column_name, "alias": alias, "truncate_date_to": None}]
        path = f"pages/{page_id}/visuals/{visual_id}/query/dimensions"
        notes = [f"Grouping by '{column_name}' from block '{block_id}' (certified).", "This change re-queries the visual after approval."]
        proposal = ReportProposal(
            description=f"Group by {alias} ({block_id}.{column_name})",
            changes=[ReportChange(path=path, label=f"Dimension → {alias}", before=before_dims, after=after_dims, affects_data=True)],
            target_component_id=visual_id,
        )
        intent = AIIntent(intent_kind="analysis_request", target_scope=f"visual:{visual_id}", suggested_visuals=[visual_id], trust_notes=notes, risk_level="medium")
        return NL2ProposalResult(intent=intent, message=f"Dimension change proposal: group by {alias}.", proposal=proposal, trust_notes=notes, risk_level="medium")

    # ------------------------------------------------------------------
    # Round 022: value_filter_change intent
    # ------------------------------------------------------------------

    def _value_filter_change(
        self,
        column_name: str,
        values: list[str],
        report: ExecutableReportSpec,
        selected_component_id: str | None,
        semantic_model: dict[str, Any] | None,
    ) -> NL2ProposalResult:
        found = _find_visual(report, selected_component_id)
        if found is None:
            return self._unsupported("Select a visual before adding a value filter.", target_scope=_target_scope(selected_component_id))
        page_id, visual_id, visual = found
        # Determine block_id: search current block_refs for the column
        block_id = _find_block_for_column(visual, column_name, semantic_model or {})
        if block_id is None:
            return self._unsupported(f"Column '{column_name}' was not found in this visual's blocks.", target_scope=f"visual:{visual_id}")
        before_filters = [
            {"block_id": f.block_id, "column_name": f.column_name, "operator": f.operator.value,
             "value": f.value, "inherit_global_filter": f.inherit_global_filter}
            for f in visual.query.filters
        ]
        # Remove any existing filter for the same column, then append new one
        after_filters = [f for f in before_filters if not (f["block_id"] == block_id and f["column_name"] == column_name)]
        after_filters.append({"block_id": block_id, "column_name": column_name, "operator": "in", "value": values, "inherit_global_filter": False})
        path = f"pages/{page_id}/visuals/{visual_id}/query/filters"
        notes = [f"Filtering '{column_name}' to {values} on block '{block_id}'.", "This change re-queries the visual after approval."]
        proposal = ReportProposal(
            description=f"Filter {column_name} to {values}",
            changes=[ReportChange(path=path, label=f"Filter: {column_name} IN {values}", before=before_filters, after=after_filters, affects_data=True)],
            target_component_id=visual_id,
        )
        intent = AIIntent(intent_kind="analysis_request", target_scope=f"visual:{visual_id}", suggested_visuals=[visual_id], trust_notes=notes, risk_level="medium")
        return NL2ProposalResult(intent=intent, message=f"Value filter proposal: {column_name} IN {values}.", proposal=proposal, trust_notes=notes, risk_level="medium")

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

        # Safety: block kpi_card and table (require different query contracts)
        _UNSUPPORTED_SOURCE = {VisualType.kpi_card, VisualType.table, VisualType.pivot, VisualType.map}
        _UNSUPPORTED_TARGET = {VisualType.kpi_card, VisualType.table, VisualType.pivot, VisualType.map}
        if current_type in _UNSUPPORTED_SOURCE:
            return self._unsupported(
                f"Chart type change is not supported for {current_type.value} visuals.",
                target_scope=f"visual:{visual_id}",
            )
        if target_type in _UNSUPPORTED_TARGET:
            return self._unsupported(
                "Cannot convert to table or kpi_card — they require different query contracts.",
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

    # ------------------------------------------------------------------
    # Round 027: add_visual — create a new visual on the canvas
    # ------------------------------------------------------------------

    def _add_visual_nl(
        self,
        params: dict,
        report: ExecutableReportSpec,
        semantic_model: dict[str, Any] | None,
        contracts: dict[str, Any] | None,
    ) -> NL2ProposalResult:
        from ai4bi.report.builder import build_add_visual_proposal, build_visual_from_selection
        from ai4bi.query_spec import DimensionRef, FilterSpec, FilterOperator
        from dataclasses import replace as _replace

        visual_type_str = (params.get("visual_type") or "bar_chart").lower()
        metric_name = (params.get("metric") or "").strip()
        dimension_kw = (params.get("dimension") or "").strip().lower()
        title = (params.get("title") or "").strip() or None
        step_filter = (params.get("step_filter") or "").strip().upper() or None

        # Map visual_type string to VisualType enum
        _vtype_map = {
            "line_chart": VisualType.line_chart, "line": VisualType.line_chart,
            "bar_chart": VisualType.bar_chart, "bar": VisualType.bar_chart,
            "table": VisualType.table,
            "kpi_card": VisualType.kpi_card, "kpi": VisualType.kpi_card,
            "pie_chart": VisualType.pie_chart, "pie": VisualType.pie_chart,
            "scatter": VisualType.scatter, "scatter_chart": VisualType.scatter,
        }
        vtype = _vtype_map.get(visual_type_str, VisualType.bar_chart)

        # Resolve metric → block_id
        sm_metrics = {m.get("metric_id") or m.get("name", ""): m
                      for m in (semantic_model or {}).get("metrics", [])}
        if metric_name not in sm_metrics and contracts:
            # Fallback: scan all block contracts
            for bid, contract in (contracts or {}).items():
                for m in getattr(contract, "metrics", []):
                    if m.name == metric_name:
                        sm_metrics[metric_name] = {"metric_id": metric_name, "owner_block": bid}
                        break
        if metric_name not in sm_metrics:
            return self._unsupported(
                f"指標 '{metric_name}' 不在語意模型中，無法新增圖表。",
                target_scope="canvas",
            )
        sm_entry = sm_metrics[metric_name]
        owner_block = sm_entry.get("owner_block") or sm_entry.get("base_dataset", "")

        # Resolve semantic-model metric_id → block metric name
        # e.g. "avg_queue_time_hr" (sm) → "queue_time_hr" (block formula column)
        if contracts and owner_block in contracts:
            block_contract = contracts[owner_block]
            block_metric_names = [m.name for m in getattr(block_contract, "metrics", [])]
            if metric_name not in block_metric_names:
                # Try extracting column from formula: AVG(queue_time_hr) → queue_time_hr
                import re as _re
                formula = sm_entry.get("formula", "")
                col_match = _re.search(r'\((\w+)\)', formula)
                if col_match and col_match.group(1) in block_metric_names:
                    metric_name = col_match.group(1)
                else:
                    # Fuzzy: find block metric whose name is contained in the sm metric_id
                    for bm in block_metric_names:
                        if bm in metric_name or metric_name.endswith(bm):
                            metric_name = bm
                            break
        if not owner_block:
            return self._unsupported(
                f"找不到指標 '{metric_name}' 的所屬積木。",
                target_scope="canvas",
            )

        # Resolve dimension keyword → "block_id.column_name"
        # Round 035: static map first, then dynamic SchemaIndex fallback
        dim_spec = _DIM_KEYWORD_MAP.get(dimension_kw)
        dimension_names: list[str] = []
        if dim_spec:
            dim_block, dim_col, _dim_alias, _truncate = dim_spec
            dimension_names = [f"{dim_block}.{dim_col}"]
        elif dimension_kw and contracts:
            _idx = SchemaIndex.build(contracts)
            _entry = _idx.find_dim(dimension_kw) or _idx.best_dim_match(
                dimension_kw, dimension_kw.lower()
            )
            if _entry:
                dimension_names = [f"{_entry.block_id}.{_entry.column_name}"]

        # Generate unique visual_id
        existing = set(report.pages.get("main", type("_", (), {"visuals": {}})()).visuals.keys())
        base_id = f"nl_{vtype.value}_{metric_name}"
        visual_id = base_id
        counter = 1
        while visual_id in existing:
            visual_id = f"{base_id}_{counter}"
            counter += 1

        if not contracts:
            return self._unsupported("合約資料尚未載入，無法新增圖表。", target_scope="canvas")

        try:
            query_spec, viz_spec = build_visual_from_selection(
                visual_id=visual_id,
                block_id=owner_block,
                metric_names=[metric_name],
                dimension_names=dimension_names,
                visual_type=vtype,
                contracts=contracts,
                semantic_model=semantic_model,
            )
        except (ValueError, KeyError) as exc:
            return self._unsupported(
                f"無法建立圖表：{exc}",
                target_scope="canvas",
            )

        # Apply optional step filter
        if step_filter:
            from ai4bi.query_spec import FilterSpec, FilterOperator
            from dataclasses import replace as _r
            new_filter = FilterSpec(
                block_id=owner_block,
                column_name="step_id",
                operator=FilterOperator.in_,
                value=[step_filter],
                inherit_global_filter=False,
            )
            query_spec = _r(query_spec, filters=list(query_spec.filters) + [new_filter])

        # Override title if provided
        if title:
            from dataclasses import replace as _r
            viz_spec = _r(viz_spec, title=title)

        proposal = build_add_visual_proposal(
            page_id="main",
            visual_id=visual_id,
            query_spec=query_spec,
            viz_spec=viz_spec,
        )
        notes = [
            f"新增圖表 '{visual_id}' ({vtype.value})，指標：{metric_name}，積木：{owner_block}。",
            f"維度：{dimension_names or '無'}。",
            "確認後圖表會加入報表畫布。",
        ]
        intent = AIIntent(
            intent_kind="analysis_request",
            target_scope="canvas",
            trust_notes=notes,
            risk_level="medium",
        )
        return NL2ProposalResult(
            intent=intent,
            message=f"新增圖表提案已建立：{title or visual_id}。確認後加入畫布。",
            proposal=proposal,
            trust_notes=notes,
            risk_level="medium",
        )

    # ------------------------------------------------------------------
    # Round 027: highlight_outliers — conditional formatting on tables
    # ------------------------------------------------------------------

    def _highlight_outliers(
        self,
        params: dict,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
    ) -> NL2ProposalResult:
        visual_id = params.get("visual_id") or selected_component_id
        if not visual_id:
            # Auto-detect: find first table visual
            for page in report.pages.values():
                for vid, visual in page.visuals.items():
                    if visual.visualization.visual_type == VisualType.table:
                        visual_id = vid
                        break
                if visual_id:
                    break
        if not visual_id:
            return self._unsupported("找不到表格圖表，請先選擇一個表格。", target_scope="canvas")

        found = _find_visual(report, visual_id)
        if found is None:
            return self._unsupported(f"找不到圖表 '{visual_id}'。", target_scope=f"visual:{visual_id}")
        page_id, visual_id, visual = found

        if visual.visualization.visual_type != VisualType.table:
            return self._unsupported("離群值標色只支援表格類型的圖表。", target_scope=f"visual:{visual_id}")

        column = params.get("column") or None
        method = params.get("method") or "iqr"
        color = params.get("color") or "#FF4444"

        before_extra = dict(visual.visualization.extra)
        after_extra = dict(visual.visualization.extra)
        after_extra["conditional_formats"] = [
            {"column": column, "method": method, "color": color}
        ]
        path = f"pages/{page_id}/visuals/{visual_id}/visualization/extra/conditional_formats"
        notes = [
            f"對表格 '{visual_id}' 的 {'所有數值欄位' if column is None else column} 套用離群值標色。",
            f"方法：{method}，顏色：{color}。",
            "這是視覺化效果，不影響原始資料。",
        ]
        proposal = ReportProposal(
            description=f"離群值標色（{method}）",
            changes=[ReportChange(
                path=path,
                label="條件格式：離群值",
                before=before_extra.get("conditional_formats"),
                after=after_extra["conditional_formats"],
                affects_data=False,
            )],
            target_component_id=visual_id,
        )
        intent = AIIntent(intent_kind="style_change", target_scope=f"visual:{visual_id}", trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message="離群值標色提案已建立。", proposal=proposal, trust_notes=notes, risk_level="low")

    # ------------------------------------------------------------------
    # Round 027: add_trend_line — Plotly trend-line overlay
    # ------------------------------------------------------------------

    def _add_trend_line(
        self,
        params: dict,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
    ) -> NL2ProposalResult:
        visual_id = params.get("visual_id") or selected_component_id
        if not visual_id:
            for page in report.pages.values():
                for vid, visual in page.visuals.items():
                    if visual.visualization.visual_type in (VisualType.line_chart, VisualType.bar_chart):
                        visual_id = vid
                        break
                if visual_id:
                    break
        if not visual_id:
            return self._unsupported("找不到折線圖，請先選擇一個圖表。", target_scope="canvas")

        found = _find_visual(report, visual_id)
        if found is None:
            return self._unsupported(f"找不到圖表 '{visual_id}'。", target_scope=f"visual:{visual_id}")
        page_id, visual_id, visual = found

        if visual.visualization.visual_type not in (VisualType.line_chart, VisualType.bar_chart):
            return self._unsupported("趨勢線只支援折線圖和長條圖。", target_scope=f"visual:{visual_id}")

        method = params.get("method") or "linear"
        window = int(params.get("window") or 3)
        before_extra = dict(visual.visualization.extra)
        after_extra = dict(before_extra)
        after_extra["trend_line"] = {"method": method, "window": window, "color": "#888888", "dash": "dot"}

        path = f"pages/{page_id}/visuals/{visual_id}/visualization/extra/trend_line"
        notes = [
            f"在圖表 '{visual_id}' 上加入趨勢線（方法：{method}）。",
            "趨勢線是視覺化覆蓋，不影響查詢資料。",
        ]
        proposal = ReportProposal(
            description=f"加入趨勢線（{method}）",
            changes=[ReportChange(
                path=path,
                label="趨勢線",
                before=before_extra.get("trend_line"),
                after=after_extra["trend_line"],
                affects_data=False,
            )],
            target_component_id=visual_id,
        )
        intent = AIIntent(intent_kind="style_change", target_scope=f"visual:{visual_id}", trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=f"趨勢線提案已建立（{method}）。", proposal=proposal, trust_notes=notes, risk_level="low")

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
        disambiguation: str | None = None,
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
            disambiguation=disambiguation,
        )


def _normalize(prompt: str) -> str:
    return " ".join(prompt.strip().lower().split())


# ---------------------------------------------------------------------------
# Round 078: direct-answer engine helpers
# ---------------------------------------------------------------------------

# Explicit question markers. An imperative edit ("加一張營收圖") has none of these,
# so gating on them keeps the answer engine from stealing edit commands.
_QUESTION_MARKERS: tuple[str, ...] = (
    "多少", "幾", "是多少", "有多少", "總共", "共有", "平均是", "占比", "佔比",
    "為何", "為什麼", "?", "？",
    "how much", "how many", "what is", "what's", "what was", "what are",
    "tell me", "show me the", "total of", "average of", "sum of",
)

_PERIOD_TITLE: dict[str, str] = {
    "week": "最近 7 天", "month": "最近 30 天", "quarter": "最近 90 天", "year": "最近 12 個月",
}


def _looks_like_metric_question(prompt: str, normalized: str) -> bool:
    """True when the prompt reads as a question asking for a metric value."""
    hay = f"{prompt.lower()} {normalized}"
    return any(marker in hay for marker in _QUESTION_MARKERS)


def _extract_answer_period(normalized: str, prompt: str) -> str:
    """Map a time phrase to a trailing-window period, else 'all' (whole period)."""
    hay = f"{prompt.lower()} {normalized}"
    if any(t in hay for t in ("本週", "這週", "上週", "這周", "上周", "this week", "last week", "wow", "最近 7", "最近7", "近 7", "近7", "7 天", "7天")):
        return "week"
    if any(t in hay for t in ("本月", "這個月", "上個月", "當月", "this month", "last month", "mom", "最近 30", "最近30", "近 30", "近30", "30 天", "30天")):
        return "month"
    if any(t in hay for t in ("本季", "這季", "上季", "季度", "this quarter", "last quarter", "qtd", "qoq", "90 天", "90天")):
        return "quarter"
    if any(t in hay for t in ("今年", "去年", "全年", "年度", "this year", "last year", "yoy", "ytd", "12 個月", "12個月")):
        return "year"
    return "all"


def _find_date_column(contracts: dict[str, Any] | None, block_id: str) -> str | None:
    """Find the best date column on a block's contract for period filtering."""
    if not contracts or block_id not in contracts:
        return None
    contract = contracts[block_id]
    cols = getattr(contract, "columns", None) or []
    for col in cols:
        if getattr(col, "data_type", None) in ("date", "timestamp", "datetime"):
            return col.name
    for col in cols:
        name = col.name.lower()
        if any(t in name for t in ("date", "_at", "time", "_dt", "_ts", "day")):
            return col.name
    return None


def _metric_unit(contracts: dict[str, Any] | None, block_id: str, metric_name: str) -> str:
    """Return the metric's declared unit (e.g. 'NT$', '%') for formatting."""
    if not contracts or block_id not in contracts:
        return ""
    for m in getattr(contracts[block_id], "metrics", None) or []:
        if getattr(m, "name", None) == metric_name:
            return getattr(m, "unit", "") or ""
    return ""


def _first_scalar(df, col: str) -> float | None:
    """Pull the single aggregate value out of a one-row result frame."""
    if df is None or getattr(df, "empty", True):
        return None
    use = col if col in df.columns else (df.columns[-1] if len(df.columns) else None)
    if use is None:
        return None
    try:
        import pandas as pd  # local import keeps module import light
        val = df[use].iloc[0]
        return None if pd.isna(val) else float(val)
    except (ValueError, TypeError, IndexError):
        return None


def _format_metric_value(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "%":
        return f"{value:,.1f}%"
    if unit in ("NT$", "$", "USD", "TWD"):
        prefix = "NT$" if unit in ("NT$", "TWD") else "$"
        return f"{prefix}{value:,.0f}"
    if abs(value - round(value)) < 1e-9:
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def _compose_answer_sentence(
    alias: str,
    value: float | None,
    unit: str,
    period: str,
    previous: float | None,
    delta_pct: float | None,
    cur_label: str,
    prev_label: str,
) -> str:
    """Build the human-readable answer sentence (with delta when available)."""
    vtxt = _format_metric_value(value, unit)
    scope = _PERIOD_TITLE.get(period, "全期間")
    base = f"{scope}「{alias}」為 {vtxt}。"
    if delta_pct is not None and previous is not None:
        arrow = "↑" if delta_pct >= 0 else "↓"
        ptxt = _format_metric_value(previous, unit)
        base += f"　較{prev_label} {ptxt} {arrow}{abs(delta_pct):.1f}%。"
    return base


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
    """Detect requests to change chart type."""
    chart_keywords = (
        "bar chart", "line chart", "pie chart", "scatter chart", "donut",
        "長條圖", "柱狀圖", "折線圖", "trend chart", "圓餅圖", "甜甜圈圖", "散點圖", "散佈圖",
    )
    change_keywords = ("change", "convert", "switch", "改成", "換成", "轉成", "改為", "換為")
    has_chart = any(k in normalized or k in prompt for k in chart_keywords)
    has_change = any(k in normalized or k in prompt for k in change_keywords)
    if has_chart and has_change:
        return True
    if re.search(r"(改|換|轉)(成|為|做)\s*(長條圖|折線圖|圓餅圖|散點圖|bar|line|pie|scatter)", prompt):
        return True
    return False


def _extract_chart_type(prompt: str, normalized: str) -> VisualType | None:
    """Extract the target chart type from a change request."""
    for keyword, vtype in _CHART_TYPE_KEYWORDS.items():
        if keyword in normalized or keyword in prompt:
            return vtype
    return None


_ADD_VISUAL_VERBS = (
    "add", "create", "新增", "加一", "加個", "加上", "加 ", "建立", "做一", "做個", "畫一", "畫個", "畫個",
)


def _looks_like_add_trend_line(prompt: str, normalized: str) -> bool:
    """Detect a request to ADD a trend line / regression overlay.

    Must be an *add* intent — a style request like "make the trend line red"
    is a colour change, not an add, and must fall through to the style handler.
    """
    keys = ("趨勢線", "trend line", "trendline", "迴歸線", "回歸線", "regression")
    if not any(k in normalized or k in prompt for k in keys):
        return False
    has_add = ("加" in prompt or any(v in normalized or v in prompt for v in _ADD_VISUAL_VERBS))
    # exclude colour/style verbs ("make ... red", "改成紅色")
    style_words = ("red", "blue", "green", "color", "colour", "紅", "藍", "綠",
                   "顏色", "make", "改成", "換成", "改為", "換為", "style")
    has_style = any(w in normalized or w in prompt for w in style_words)
    return has_add and not has_style


def _looks_like_add_visual(prompt: str, normalized: str) -> bool:
    """Detect a request to ADD a NEW chart (vs change an existing one).

    Requires an add-verb plus a chart-type keyword; the change-verb path
    (_looks_like_chart_type_change) handles 'change to pie' separately.
    """
    has_chart = any(k in normalized or k in prompt for k in _ADD_VISUAL_TYPE_KEYWORDS)
    if not has_chart:
        return False
    has_add = any(v in normalized or v in prompt for v in _ADD_VISUAL_VERBS)
    has_change = any(k in normalized or k in prompt
                     for k in ("change", "convert", "switch", "改成", "換成", "轉成", "改為", "換為"))
    return has_add and not has_change


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


def _extract_remove_metric_name(prompt: str, normalized: str) -> str | None:
    """Extract a metric name from a remove-metric request."""
    for pattern in _REMOVE_METRIC_PATTERNS:
        match = re.search(pattern, prompt, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _looks_like_remove_metric(prompt: str, normalized: str) -> bool:
    return _extract_remove_metric_name(prompt, normalized) is not None


def _extract_rename_title(prompt: str, normalized: str) -> str | None:
    """Extract the new title from a rename-visual request."""
    for pattern in _RENAME_VISUAL_PATTERNS:
        match = re.search(pattern, prompt, re.IGNORECASE | re.UNICODE)
        if match:
            title = match.group(1).strip().strip("'\"")
            if title:
                return title
    return None


def _looks_like_rename_visual(prompt: str, normalized: str) -> bool:
    rename_triggers = (
        "rename", "change title", "set title", "把這張圖改名", "把这张图改名",
        "名稱改成", "改名叫", "命名為", "命名成",
    )
    has_trigger = any(t.lower() in normalized or t in prompt for t in rename_triggers)
    return has_trigger and _extract_rename_title(prompt, normalized) is not None


def _blocked_terms(normalized: str) -> list[str]:
    terms = []
    for term in ("sql", "join", "yield", "detail", "raw"):
        if term in normalized:
            terms.append(term)
    return terms


# ---------------------------------------------------------------------------
# Round 020: Date filter detection helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Round 022: Categorical dimension detection helpers
# ---------------------------------------------------------------------------

# Known categorical dimension columns in semiconductor demo (and generic aliases)
_CATEGORICAL_DIM_MAP: dict[str, dict] = {
    # product family
    "product family": {"block_id": "lot_dim", "column_name": "product_family", "alias": "Product Family"},
    "product_family": {"block_id": "lot_dim", "column_name": "product_family", "alias": "Product Family"},
    "產品": {"block_id": "lot_dim", "column_name": "product_family", "alias": "Product Family"},
    "產品族": {"block_id": "lot_dim", "column_name": "product_family", "alias": "Product Family"},
    # vendor
    "vendor": {"block_id": "tool_dim", "column_name": "vendor", "alias": "Vendor"},
    "供應商": {"block_id": "tool_dim", "column_name": "vendor", "alias": "Vendor"},
    "廠商": {"block_id": "tool_dim", "column_name": "vendor", "alias": "Vendor"},
    # tool_id
    "tool": {"block_id": "tool_dim", "column_name": "tool_id", "alias": "Tool"},
    "tool id": {"block_id": "tool_dim", "column_name": "tool_id", "alias": "Tool"},
    "tool_id": {"block_id": "tool_dim", "column_name": "tool_id", "alias": "Tool"},
    "設備": {"block_id": "tool_dim", "column_name": "tool_id", "alias": "Tool"},
    "機台": {"block_id": "tool_dim", "column_name": "tool_id", "alias": "Tool"},
    # process step
    "process step": {"block_id": "process_step_dim", "column_name": "step_name", "alias": "Process Step"},
    "step": {"block_id": "process_step_dim", "column_name": "step_name", "alias": "Process Step"},
    "製程": {"block_id": "process_step_dim", "column_name": "step_name", "alias": "Process Step"},
    "製程步驟": {"block_id": "process_step_dim", "column_name": "step_name", "alias": "Process Step"},
    # lot
    "lot": {"block_id": "lot_dim", "column_name": "lot_id", "alias": "Lot"},
    "批次": {"block_id": "lot_dim", "column_name": "lot_id", "alias": "Lot"},
}

_CAT_DIM_TRIGGERS = ("group by", "分組", "按", "group", "breakdown by", "by ", "改用", "按照")


def _extract_categorical_dimension(
    prompt: str,
    normalized: str,
    contracts: dict | None = None,
) -> dict | None:
    """Extract a categorical dimension target from the prompt.

    Round 035: Falls back to SchemaIndex (dynamic lookup from loaded contracts)
    when the static semiconductor map has no match.

    Returns {"block_id": ..., "column_name": ..., "alias": ...} or None.
    Only triggers when a group/dimension change verb is present.
    """
    has_trigger = any(t.lower() in normalized or t in prompt for t in _CAT_DIM_TRIGGERS)
    if not has_trigger:
        return None
    # Longest match wins — static map first
    best: dict | None = None
    best_len = 0
    for keyword, dim in _CATEGORICAL_DIM_MAP.items():
        kw_lower = keyword.lower()
        if kw_lower in normalized or keyword in prompt:
            if len(keyword) > best_len:
                best = dim
                best_len = len(keyword)

    # Round 035: dynamic fallback via SchemaIndex
    if best is None and contracts:
        idx = SchemaIndex.build(contracts)
        entry = idx.best_dim_match(prompt, normalized)
        if entry is not None:
            best = {
                "block_id": entry.block_id,
                "column_name": entry.column_name,
                "alias": entry.alias,
            }
    return best


def _certified_dim_targets_for_fact(fact_block_id: str, semantic_model: dict) -> set[str]:
    """Return block_ids of certified dimension targets reachable from fact_block_id."""
    result: set[str] = set()
    for rel in semantic_model.get("relationships", []):
        if rel.get("from_block") == fact_block_id and rel.get("status") == "certified":
            result.add(rel["to_block"])
    return result


# ---------------------------------------------------------------------------
# Round 022: Value filter detection helpers
# ---------------------------------------------------------------------------

# Known filterable categorical values in the semiconductor demo
_VALUE_FILTER_MAP: dict[str, tuple[str, str]] = {
    # process steps — step_id in process_move_fact
    # (Logic-A/B are handled via report controls, not direct query filter)
    "photo": ("process_move_fact", "step_id"),
    "etch": ("process_move_fact", "step_id"),
    "cvd": ("process_move_fact", "step_id"),
    "cmp": ("process_move_fact", "step_id"),
    "implant": ("process_move_fact", "step_id"),
}

_VALUE_FILTER_TRIGGER_TERMS = (
    "only show", "filter to", "only", "just show", "show only",
    "只看", "只顯示", "只有", "篩選到", "過濾到", "filter",
)


def _extract_value_filter(prompt: str, normalized: str) -> tuple[str, list[str]] | None:
    """
    Extract (column_name, [values]) from a value filter request.
    Returns None if no recognizable filter pattern detected.
    """
    has_trigger = any(t.lower() in normalized or t in prompt for t in _VALUE_FILTER_TRIGGER_TERMS)
    if not has_trigger:
        return None
    matched_values: dict[tuple[str, str], list[str]] = {}  # (block_id, column) → values
    for keyword, (block_id, column) in _VALUE_FILTER_MAP.items():
        if keyword in normalized:
            key = (block_id, column)
            matched_values.setdefault(key, []).append(keyword.upper())
    if not matched_values:
        return None
    # Return the first column group found (most specific match)
    for (block_id, column), values in matched_values.items():
        return column, values
    return None


def _find_block_for_column(visual: ReportVisualSpec, column_name: str, semantic_model: dict) -> str | None:
    """Find which block in the visual's block_refs contains the given column."""
    # Check fact block first (process_move_fact has step_id, product_family)
    for ref in visual.query.block_refs:
        block_id = ref.block_id
        # Check semantic model certified relationships
        if column_name in ("step_id", "product_family", "tool_id", "wafer_id", "lot_id"):
            return block_id  # These are FK columns on the fact block
    # Fallback: return primary block
    if visual.query.block_refs:
        return visual.query.block_refs[0].block_id
    return None


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


# ---------------------------------------------------------------------------
# Round 036: Period comparison detection
# ---------------------------------------------------------------------------

_PERIOD_COMPARISON_KEYWORDS = (
    "vs", "versus", "compare", "comparison", "compared",
    "比較", "對比", "比", "vs.", "相比",
)
_PERIOD_COMPARISON_PERIOD_KEYWORDS = (
    "week", "weekly", "週", "這週", "本週", "上週",
    "month", "monthly", "月", "這月", "本月", "上月",
)


def _looks_like_period_comparison(prompt: str, normalized: str) -> bool:
    has_vs = any(k in normalized or k in prompt for k in _PERIOD_COMPARISON_KEYWORDS)
    has_period = any(k in normalized or k in prompt for k in _PERIOD_COMPARISON_PERIOD_KEYWORDS)
    return has_vs and has_period


def _extract_comparison_period(normalized: str, prompt: str) -> tuple:
    if any(k in normalized or k in prompt for k in ("month", "monthly", "月", "本月", "這月", "上月")):
        return ("month", "本月", "上月")
    if any(k in normalized or k in prompt for k in ("week", "weekly", "週", "本週", "這週", "上週")):
        return ("week", "本週", "上週")
    return ("week", "近 7 天", "前 7 天")
