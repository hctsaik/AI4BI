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
    "map": VisualType.map,           # Round 083
    "地圖": VisualType.map,
    "地圖視覺": VisualType.map,
    "small multiples": VisualType.small_multiples,  # Round 094
    "small multiple": VisualType.small_multiples,
    "小倍數": VisualType.small_multiples,
    "小倍數圖": VisualType.small_multiples,
    "分面": VisualType.small_multiples,
    "分面圖": VisualType.small_multiples,
    "trellis": VisualType.small_multiples,
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

        if intent == "panel_analysis":  # Round 086
            panel = self._run_panel_analysis(prompt, normalized, contracts)
            if panel is not None:
                return panel

        if intent == "segment_count":  # Round 091
            seg = self._answer_segment_count(prompt, normalized, report, contracts)
            if seg is not None:
                return seg

        if intent == "entity_compare":  # Round 108
            cmp = self._answer_entity_compare(prompt, normalized, report, contracts)
            if cmp is not None:
                return cmp

        if intent == "analytics_chart":  # Round 105
            ac = self._answer_analytics_chart(prompt, normalized, report, contracts)
            if ac is not None:
                return ac

        if intent == "calendar_yoy":  # Round 100
            yoy = self._answer_calendar_yoy(prompt, normalized, report, contracts)
            if yoy is not None:
                return yoy

        if intent == "insights":  # Round 097
            ins = self._answer_insights(prompt, normalized, report, contracts)
            if ins is not None:
                return ins

        if intent == "seasonality":  # Round 096
            season = self._answer_seasonality(prompt, normalized, report, contracts)
            if season is not None:
                return season

        if intent == "grouped_topn":  # Round 090
            gt = self._answer_grouped_topn(prompt, normalized, report, contracts)
            if gt is not None:
                return gt

        if intent == "ranking":  # Round 087
            ranked = self._answer_ranking(prompt, normalized, report, contracts)
            if ranked is not None:
                return ranked

        if intent == "crossfact":  # Round 116
            cf = self._answer_crossfact(prompt, normalized, report, contracts)
            if cf is not None:
                return cf

        if intent == "breakdown":  # Round 114
            bd = self._answer_breakdown(prompt, normalized, report, contracts)
            if bd is not None:
                return bd

        if intent == "pacing_question":  # Round 088
            pace = self._answer_pacing(prompt, normalized, report, contracts)
            if pace is not None:
                return pace

        if intent == "explain_change":  # Round 081
            decomp = self._explain_change(prompt, normalized, report, contracts)
            if decomp is not None:
                return decomp

        if intent == "answer_metric":  # Round 078
            answer = self._answer_metric(prompt, normalized, report, semantic_model, contracts)
            if answer is not None:
                return answer

        if intent == "measure_filter":  # Round 080
            mf = self._measure_filter_change(prompt, normalized, report, selected_component_id)
            if mf is not None:
                return mf

        if intent == "queue_analysis":
            return self._queue_time_plan(prompt, report, selected_component_id, semantic_model, contracts)

        if intent == "add_visual":
            return self._add_visual_nl(params, report, semantic_model, contracts)

        if intent == "highlight_outliers":
            return self._highlight_outliers(params, report, selected_component_id)

        if intent == "add_trend_line":
            return self._add_trend_line(params, report, selected_component_id)

        if intent == "unsupported":
            # Round 095: critical reachability fix. The LLM's intent enum does not
            # include the R078-091 answer-engine intents, so a metric question
            # ("上個月營收多少？") is classified "unsupported". Rather than refuse,
            # fall through to the deterministic keyword router — which DOES handle
            # the answer engine and every edit intent. Only short-circuit with a
            # refusal when the LLM supplied a clarifying disambiguation to show.
            disam = getattr(classification, "disambiguation", None)
            if disam:
                reason = params.get("reason", "No supported governed BI intent was detected.")
                return self._unsupported(
                    reason, target_scope=_target_scope(selected_component_id),
                    disambiguation=disam,
                )
            return None  # fall through to keyword routing (answer engine + edits)

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
        # Round 086: route churn / declining-streak / basket questions to the
        # pre-built pandas analytics engines. Checked early — these are specific
        # named analyses, more specific than a plain metric question.
        if _detect_panel_analysis(prompt, normalized) is not None:
            panel = self._run_panel_analysis(prompt, normalized, contracts)
            if panel is not None:
                return panel

        # Round 097: "給我本週摘要 / 有什麼異常嗎" → digest / anomaly engines.
        if _looks_like_insights(prompt, normalized) is not None:
            ins = self._answer_insights(prompt, normalized, report, contracts)
            if ins is not None:
                return ins

        # Round 108: "比較台北和台中" → two-entity side-by-side comparison.
        if _looks_like_entity_compare(prompt, normalized):
            cmp = self._answer_entity_compare(prompt, normalized, report, contracts)
            if cmp is not None:
                return cmp

        # Round 105: Pareto/ABC, %-of-total, moving-average, forecast charts.
        if _detect_analytics_chart(f"{prompt.lower()} {normalized}") is not None:
            ac = self._answer_analytics_chart(prompt, normalized, report, contracts)
            if ac is not None:
                return ac

        # Round 116: cross-fact analytics (correlation/cohort/ratio across two
        # facts). Checked before ranking/seasonality so "最長...有關聯" and "前 20%
        # ...良率" route to the cross-fact engine, not single-fact ranking.
        if _looks_like_crossfact(prompt, normalized):
            cf = self._answer_crossfact(prompt, normalized, report, contracts)
            if cf is not None:
                return cf

        # Round 096: "哪幾天最忙 / busiest day of week / 哪個時段" → weekday/hour
        # seasonality. Checked before ranking since it carries a date-bucket cue.
        if _looks_like_seasonality(prompt, normalized):
            season = self._answer_seasonality(prompt, normalized, report, contracts)
            if season is not None:
                return season

        # Round 090: "每個門市最暢銷的 3 個商品" → per-group Top-N. Checked before
        # plain ranking since it is the more specific (two-dimension) pattern.
        if _looks_like_grouped_topn(prompt, normalized):
            gt = self._answer_grouped_topn(prompt, normalized, report, contracts)
            if gt is not None:
                return gt

        # Round 087: "我最賺的 5 個商品" / "賣最差的品類" → ranked table. Checked
        # before the plain-answer engine; falls through if no dimension resolves.
        if _looks_like_ranking(prompt, normalized):
            ranked = self._answer_ranking(prompt, normalized, report, contracts)
            if ranked is not None:
                return ranked

        # Round 081: "why did <metric> change? decompose by <dim>" — checked
        # before the plain-answer engine so a "why" question decomposes instead
        # of returning a single total. Falls through if no dimension resolves.
        if _looks_like_explain_change(prompt, normalized):
            decomp = self._explain_change(prompt, normalized, report, contracts)
            if decomp is not None:
                return decomp

        # Round 100: calendar YoY ("本月 vs 去年同月") — checked before the plain
        # answer engine so '去年同期' uses calendar boundaries, not a trailing year.
        if _looks_like_calendar_yoy(prompt, normalized):
            yoy = self._answer_calendar_yoy(prompt, normalized, report, contracts)
            if yoy is not None:
                return yoy

        # Round 114: plain "metric by dimension" breakdown ("各製程站的移動次數").
        # After ranking/decompose (so superlatives/why still win), before the
        # generic single-number answer.
        if _looks_like_breakdown(prompt, normalized):
            bd = self._answer_breakdown(prompt, normalized, report, contracts)
            if bd is not None:
                return bd

        if _looks_like_metric_question(prompt, normalized):
            answer = self._answer_metric(prompt, normalized, report, semantic_model, contracts)
            if answer is not None:
                return answer

        # Round 088: "達標了嗎 / are we on track?" — read back KPI pacing. Checked
        # before set-target (a question, not a set command).
        if _looks_like_pacing_question(prompt, normalized):
            pace = self._answer_pacing(prompt, normalized, report, contracts)
            if pace is not None:
                return pace

        # Round 084: set a KPI goal/target. "把營收目標設為 100 萬". Checked before
        # measure-filter since "目標" + a number is goal-setting, not a HAVING.
        if _looks_like_set_target(prompt, normalized):
            st_res = self._set_target(prompt, normalized, report, selected_component_id)
            if st_res is not None:
                return st_res

        # Round 091: cold-start grouped measure filter — "買超過 3 次的客戶" builds
        # the entity×count grouped HAVING query from scratch (no existing visual
        # needed). Checked before the on-visual measure filter.
        if _looks_like_segment_count(prompt, normalized):
            seg = self._answer_segment_count(prompt, normalized, report, contracts)
            if seg is not None:
                return seg

        # Round 080: measure (post-aggregate) filter → HAVING. "把營收超過 500 的列出",
        # edits an *existing* grouped visual's HAVING. Carries a comparison + number
        # against a projected metric.
        if _looks_like_measure_filter(prompt, normalized):
            mf = self._measure_filter_change(prompt, normalized, report, selected_component_id)
            if mf is not None:
                return mf

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
        if vtype == VisualType.map:
            # Round 089: a map needs a *location* dimension — prefer a geo column
            # (city / 縣市 / region / store) over an arbitrary categorical.
            loc_col = _find_location_col(contract) or cat_col
            if loc_col:
                dimensions = [DimensionRef(block_id, loc_col, loc_col)]
                sort = [SortSpec(metric_alias, SortDirection.desc)]
        elif vtype == VisualType.small_multiples:
            # Round 094: facet by a category, x-axis over time → one mini trend
            # per category. Falls back to a single facet dimension if no date.
            if cat_col and date_col:
                dimensions = [DimensionRef(block_id, cat_col, cat_col),
                              DimensionRef(block_id, date_col, date_col, truncate_date_to="week")]
                sort = [SortSpec(date_col, SortDirection.asc)]
            elif cat_col:
                dimensions = [DimensionRef(block_id, cat_col, cat_col)]
                sort = [SortSpec(metric_alias, SortDirection.desc)]
        elif vtype == VisualType.pivot and len(cat_cols) >= 2:
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
            VisualType.pivot: "樞紐表", VisualType.map: "地圖",
            VisualType.small_multiples: "小倍數圖",
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

    def _answer_entity_compare(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 108: "比較台北和台中" / "Taipei vs Taichung" — two-entity compare.

        Resolves two dimension *values*, finds the categorical column holding
        both, and compares a metric between them. Returns None (declines) when
        the operands or column can't be resolved — never guesses.
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None
        ops = _extract_compare_operands(prompt, normalized)
        if ops is None:
            return None
        a, b = ops

        from ai4bi.blocks.contracts import BlockType
        from ai4bi.blocks.datastore import materialize_dataframe

        # Find a fact block + categorical column whose values include both operands.
        target = None
        for bid, c in contracts.items():
            if getattr(c, "block_type", None) not in (
                BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact):
                continue
            try:
                df = materialize_dataframe(c)
            except Exception:  # noqa: BLE001
                continue
            for col in [cc.name for cc in c.columns
                        if cc.data_type in ("string", "str", "object")]:
                vals = set(df[col].astype(str).unique()) if col in df.columns else set()
                if a in vals and b in vals:
                    target = (bid, col)
                    break
            if target:
                break
        if target is None:
            return None
        block_id, col = target

        idx = SchemaIndex.build(contracts)
        match = idx.best_metric_match(prompt, normalized)
        if match is not None and match.block_id == block_id:
            metric_name, alias = match.metric_name, match.alias
        else:
            dm = _default_count_metric(contracts, block_id)
            if dm is None:
                return None
            metric_name, alias = dm

        from ai4bi.query_spec import (
            BlockRef, DimensionRef, FilterOperator, FilterSpec, VisualQuerySpec,
        )
        spec = VisualQuerySpec(
            spec_id=f"cmp_{metric_name}", block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            dimensions=[DimensionRef(block_id, col, col)],
            filters=[FilterSpec(block_id, col, FilterOperator.in_, [a, b], False)],
            inherit_global_filter=False)
        try:
            df = executor.run(spec)
        except Exception:  # noqa: BLE001
            return None
        if df is None or df.empty or col not in df.columns or alias not in df.columns:
            return None

        vals = {str(r[col]): float(r[alias]) for _, r in df.iterrows()}
        va, vb = vals.get(a), vals.get(b)
        unit = _metric_unit(contracts, block_id, metric_name)
        if va is not None and vb is not None:
            hi, lo = (a, b) if va >= vb else (b, a)
            hv, lv = (va, vb) if va >= vb else (vb, va)
            diff_pct = ((hv - lv) / abs(lv) * 100) if lv else None
            sentence = (f"{a} {alias} {_format_metric_value(va, unit)}　vs　"
                        f"{b} {_format_metric_value(vb, unit)}。{hi} 較高"
                        + (f"，多 {diff_pct:.1f}%。" if diff_pct is not None else "。"))
        else:
            sentence = f"比較 {a} 與 {b} 的 {alias}。"
        notes = [f"比較「{col}」中 {a} 與 {b} 的「{alias}」（治理查詢路徑），來源：{block_id}。"]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence, result_table=df,
                                 trust_notes=notes, risk_level="low")

    def _answer_analytics_chart(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 105: NL on-ramp for the postprocess / forecast engines.

        Pareto/ABC, %-of-total, moving-average and forecast were render-wired but
        only reachable from the canned demo. This builds a new visual with the
        right extra config so the ask box can request them. Returns None to fall
        through.
        """
        if not contracts:
            return None
        kind = _detect_analytics_chart(f"{prompt.lower()} {normalized}")
        if kind is None:
            return None
        idx = SchemaIndex.build(contracts)
        match = idx.best_metric_match(prompt, normalized)
        if match is None:
            return None
        block_id, metric_name, alias = match.block_id, match.metric_name, match.alias

        from ai4bi.report.builder import build_add_visual_proposal
        from ai4bi.query_spec import (
            BlockRef, DimensionRef, SortDirection, SortSpec, VisualizationSpec, VisualQuerySpec,
        )

        page_id = "main" if "main" in report.pages else next(iter(report.pages), None)
        if page_id is None:
            return None
        existing = {vid for p in report.pages.values() for vid in p.visuals}

        n = _extract_analytics_n(prompt, normalized)
        if kind in ("pareto", "share"):
            dim_col = _resolve_decomp_dimension(idx, prompt, normalized, contracts, block_id)
            if dim_col is None:
                return None
            vid = _unique_id(f"{kind}_{metric_name}", existing)
            q = VisualQuerySpec(vid, [BlockRef(block_id)],
                                metrics=[MetricRef(block_id, metric_name, alias)],
                                dimensions=[DimensionRef(block_id, dim_col, dim_col)],
                                sort=[SortSpec(alias, SortDirection.desc)],
                                inherit_global_filter=False)
            mode = "pareto" if kind == "pareto" else "share_of_total"
            title = (f"{alias} Pareto/ABC（依{dim_col}）" if kind == "pareto"
                     else f"{alias} 佔比（依{dim_col}）")
            viz = VisualizationSpec(VisualType.bar_chart, title=title,
                                    extra={"postprocess": mode, "data_labels": True})
            msg = f"已準備{('Pareto/ABC' if kind=='pareto' else '佔比')}分析：{alias} 依 {dim_col}。"
        else:  # moving_avg or forecast → time series
            date_col = _find_date_column(contracts, block_id)
            if date_col is None:
                return None
            vid = _unique_id(f"{kind}_{metric_name}", existing)
            q = VisualQuerySpec(vid, [BlockRef(block_id)],
                                metrics=[MetricRef(block_id, metric_name, alias)],
                                dimensions=[DimensionRef(block_id, date_col, date_col,
                                                         truncate_date_to="week")],
                                sort=[SortSpec(date_col, SortDirection.asc)],
                                inherit_global_filter=False)
            if kind == "moving_avg":
                extra = {"postprocess": "moving_avg", "postprocess_window": n or 4}
                title = f"{alias} 趨勢 + {n or 4} 期移動平均"
                msg = f"已準備 {alias} 的移動平均平滑趨勢。"
            else:  # forecast
                extra = {"trend_line": {"method": "linear", "forecast_periods": n or 4}}
                title = f"{alias} 趨勢 + 未來 {n or 4} 期預測"
                msg = f"已準備 {alias} 的趨勢預測（外推 {n or 4} 期）。"
            viz = VisualizationSpec(VisualType.line_chart, title=title, extra=extra)

        proposal = build_add_visual_proposal(page_id, vid, q, viz)
        notes = [msg, f"指標：{alias}（{metric_name} @ {block_id}）；套用後重新查詢。"]
        intent = AIIntent(intent_kind="add_visual", target_scope=f"page:{page_id}",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=msg, proposal=proposal,
                                 trust_notes=notes, risk_level="low")

    def _answer_calendar_yoy(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 100: "本月 vs 去年同月" / "same month last year" — calendar YoY.

        Compares period-to-date this year against the same dates last year
        (calendar boundaries), unlike the trailing-window comparison. Returns
        None to fall through.
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None
        hay = f"{prompt.lower()} {normalized}"
        grain = ("year" if any(t in hay for t in ("今年", "年增", "全年", "ytd", "this year"))
                 else "quarter" if any(t in hay for t in ("本季", "這季", "季")) else "month")

        idx = SchemaIndex.build(contracts)
        match = idx.best_metric_match(prompt, normalized)
        if match is None:
            return None
        block_id, metric_name, alias = match.block_id, match.metric_name, match.alias
        date_col = _find_date_column(contracts, block_id)
        if date_col is None:
            return None

        from ai4bi.analysis.time_intelligence import compute_calendar_comparison
        from ai4bi.query_spec import BlockRef, VisualQuerySpec

        base = VisualQuerySpec(
            spec_id=f"yoy_{metric_name}", block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)], inherit_global_filter=False)
        comp = compute_calendar_comparison(
            executor, base, date_block_id=block_id, date_column=date_col,
            grain=grain, metric_col=alias)
        if comp is None or comp.current is None:
            return None

        unit = _metric_unit(contracts, block_id, metric_name)
        cur_txt = _format_metric_value(comp.current, unit)
        sentence = f"{comp.current_label}「{alias}」為 {cur_txt}。"
        if comp.delta_pct is not None and comp.previous is not None:
            arrow = "↑" if comp.delta_pct >= 0 else "↓"
            sentence += (f"　較{comp.previous_label} {_format_metric_value(comp.previous, unit)} "
                         f"{arrow}{abs(comp.delta_pct):.1f}%（年增率）。")
        else:
            sentence += "　（去年同期無可比資料。）"
        notes = [f"日曆同期比較（{comp.current_label} vs {comp.previous_label}），治理查詢路徑。",
                 f"指標：{alias}（{metric_name} @ {block_id}）。"]
        answer = DirectAnswer(
            question=prompt.strip(), metric_block_id=block_id, metric_name=metric_name,
            metric_alias=alias, sentence=sentence, value=comp.current, period=grain,
            previous=comp.previous, delta_pct=comp.delta_pct,
            current_label=comp.current_label, previous_label=comp.previous_label,
            unit=unit, trust_notes=notes)
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence, direct_answer=answer,
                                 trust_notes=notes, risk_level="low")

    def _answer_insights(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 097: "給我本週摘要" / "有什麼異常嗎？".

        Routes to the already-built generate_summary / detect_anomalies engines
        (previously sidebar-only) and returns the result as a table. Returns None
        to fall through.
        """
        if not contracts:
            return None
        kind = _looks_like_insights(prompt, normalized)
        if kind is None:
            return None
        import pandas as pd

        if kind == "anomaly":
            from ai4bi.ai.suggestions import detect_anomalies
            try:
                obs = detect_anomalies(contracts, max_observations=5)
            except Exception:  # noqa: BLE001
                return None
            if not obs:
                notes = ["已掃描各資料集的離群與波動，未發現明顯異常。"]
                intent = AIIntent(intent_kind="analysis_request", target_scope="report",
                                  trust_notes=notes, risk_level="low")
                return NL2ProposalResult(intent=intent, message="目前沒有發現明顯異常 👍",
                                         trust_notes=notes, risk_level="low")
            df = pd.DataFrame([{"嚴重度": {"high": "🔴 高", "medium": "🟡 中"}.get(o.severity, "ℹ️"),
                                "重點": f"{o.icon} {o.headline}", "說明": o.detail} for o in obs])
            sentence = f"發現 {len(obs)} 個值得注意的重點。"
            notes = ["以離群（z-score）、波動（變異係數）等檢查掃描各資料集。"]
            intent = AIIntent(intent_kind="analysis_request", target_scope="report",
                              trust_notes=notes, risk_level="low")
            return NL2ProposalResult(intent=intent, message=sentence, result_table=df,
                                     trust_notes=notes, risk_level="low")

        # kind == "digest"
        executor = getattr(self, "_executor", None)
        if executor is None:
            return None
        from ai4bi.analysis.summary import generate_summary
        try:
            rep = generate_summary(executor, contracts)
        except Exception:  # noqa: BLE001
            return None
        rows = [{"類別": sec.heading, "重點": line} for sec in rep.sections for line in sec.lines]
        if not rows:
            return None
        df = pd.DataFrame(rows)
        notes = ["整合期間重點、Top 排名與已觸發的提醒（與側欄『業務摘要』同源）。"]
        intent = AIIntent(intent_kind="analysis_request", target_scope="report",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=rep.title, result_table=df,
                                 trust_notes=notes, risk_level="low")

    def _answer_seasonality(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 096: "哪幾天最忙？" / "busiest day of week" / "哪個時段" .

        Groups a metric by weekday (DAYNAME) or hour (EXTRACT) — date buckets the
        single-GROUP-BY executor now supports — and ranks busiest-first. Surfaces
        the day-of-week / hour seasonality that was previously un-askable.
        Returns None to fall through.
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None
        hay = f"{prompt.lower()} {normalized}"
        bucket = "hour" if _is_hour_seasonality(hay) else "dow"
        label = "時段" if bucket == "hour" else "星期"

        idx = SchemaIndex.build(contracts)
        match = idx.best_metric_match(prompt, normalized)
        block_id = metric_name = alias = None
        if match is not None:
            block_id, metric_name, alias = match.block_id, match.metric_name, match.alias
        else:
            # No metric word ("最忙") → a count-like metric on a dated fact block.
            from ai4bi.blocks.contracts import BlockType
            for bid, c in contracts.items():
                if getattr(c, "block_type", None) not in (
                    BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact):
                    continue
                if _find_date_column(contracts, bid) and (m := _default_count_metric(contracts, bid)):
                    block_id, (metric_name, alias) = bid, m
                    break
        if block_id is None:
            return None
        date_col = _find_date_column(contracts, block_id)
        if date_col is None:
            return None

        from ai4bi.query_spec import (
            BlockRef, DimensionRef, SortDirection, SortSpec, VisualQuerySpec,
        )
        spec = VisualQuerySpec(
            spec_id=f"season_{metric_name}",
            block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            dimensions=[DimensionRef(block_id, date_col, label, truncate_date_to=bucket)],
            sort=[SortSpec(alias, SortDirection.desc)],
            inherit_global_filter=False,
        )
        try:
            df = executor.run(spec)
        except Exception:  # noqa: BLE001
            return None
        if df is None or df.empty or label not in df.columns:
            return None

        top = df.iloc[0]
        sentence = (f"依「{label}」看「{alias}」，最高的是 {top[label]}"
                    f"（最忙排前；共 {len(df)} 個{label}）。")
        notes = [f"依 {label} 分組彙總「{alias}」並排序（治理查詢路徑），來源：{block_id}。"]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence, result_table=df,
                                 trust_notes=notes, risk_level="low")

    def _answer_segment_count(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 091: cold-start grouped measure filter.

        "買超過 3 次的客戶" / "customers who bought more than 3 times" — builds a
        grouped query (entity × count-metric) with a HAVING from scratch, even
        when no such visual exists, and returns the qualifying list. Returns None
        to fall through (e.g. to the on-visual measure filter).
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None

        operator = _measure_operator(f"{prompt.lower()} {normalized}")
        if operator is None:
            return None
        num = re.search(r"(\d[\d,]*\.?\d*)", f"{prompt} {normalized}")
        if num is None:
            return None
        try:
            threshold = float(num.group(1).replace(",", ""))
            if threshold.is_integer():
                threshold = int(threshold)
        except ValueError:
            return None

        idx = SchemaIndex.build(contracts)
        entity_col, block_id = _resolve_entity_dimension(idx, prompt, normalized, contracts)
        if entity_col is None or block_id is None:
            return None

        # Resolve the count/measure metric on this block: an explicit metric word
        # wins; otherwise a count-like metric (購買次數 / orders) is the default.
        metric_match = idx.best_metric_match(prompt, normalized)
        metric = None
        if metric_match is not None and metric_match.block_id == block_id:
            metric = (metric_match.metric_name, metric_match.alias)
        if metric is None:
            metric = _default_count_metric(contracts, block_id)
        if metric is None:
            return None
        metric_name, alias = metric

        from ai4bi.query_spec import (
            BlockRef, DimensionRef, HavingSpec, SortDirection, SortSpec, VisualQuerySpec,
        )

        spec = VisualQuerySpec(
            spec_id=f"segcount_{metric_name}",
            block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            dimensions=[DimensionRef(block_id, entity_col, entity_col)],
            having=[HavingSpec(block_id, metric_name, operator, threshold)],
            sort=[SortSpec(alias, SortDirection.desc)],
            inherit_global_filter=False,
        )
        try:
            df = executor.run(spec)
        except Exception:  # noqa: BLE001
            return None
        if df is None:
            return None

        op_sym = {"gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "eq": "=", "neq": "≠"}.get(
            operator.value, operator.value)
        sentence = (f"「{entity_col}」中，{alias} {op_sym} {threshold} 的共 {len(df)} 筆。"
                    if not df.empty else
                    f"沒有「{entity_col}」符合 {alias} {op_sym} {threshold}。")
        notes = [
            f"分組：{entity_col}；指標：{alias}；彙總後篩選 {alias} {op_sym} {threshold}（HAVING）。",
            f"治理查詢路徑（認證語意層），來源：{block_id}。",
        ]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence,
                                 result_table=df if not df.empty else None,
                                 direct_answer=None, trust_notes=notes, risk_level="low")

    def _answer_grouped_topn(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 090: "每個門市最暢銷的 3 個商品" / "top 3 products per store".

        Runs a two-dimension grouped query (outer group × inner entity) and keeps
        the top-N inner rows within each outer group — emulating a partitioned
        window function as a pandas post-pass. Returns None to fall through.
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None

        idx = SchemaIndex.build(contracts)
        metric = idx.best_metric_match(prompt, normalized)
        if metric is None:
            return None
        block_id, metric_name, alias = metric.block_id, metric.metric_name, metric.alias

        outer_col, inner_col = _resolve_two_dims(idx, prompt, normalized, contracts, block_id)
        if outer_col is None or inner_col is None or outer_col == inner_col:
            return None

        n = _extract_rank_n(prompt, normalized, default=3)
        ascending = _ranking_is_ascending(prompt, normalized)

        from ai4bi.analysis.postprocess import top_n_per_group
        from ai4bi.query_spec import BlockRef, DimensionRef, VisualQuerySpec

        spec = VisualQuerySpec(
            spec_id=f"grouptopn_{metric_name}",
            block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            dimensions=[DimensionRef(block_id, outer_col, outer_col),
                        DimensionRef(block_id, inner_col, inner_col)],
            inherit_global_filter=False,
        )
        try:
            df = executor.run(spec)
        except Exception:  # noqa: BLE001
            return None
        if df is None or df.empty or alias not in df.columns:
            return None

        table = top_n_per_group(df, outer_col, alias, n=n, ascending=ascending)
        if table is None or table.empty:
            return None

        superlative = "最低" if ascending else "最高"
        n_groups = table[outer_col].nunique()
        sentence = (f"每個「{outer_col}」中{alias}{superlative}的前 {n} 個「{inner_col}」"
                    f"（共 {n_groups} 組）。")
        notes = [
            f"先依「{outer_col}」「{inner_col}」分組彙總，再於每組內取前 {n}"
            f"（分區 Top-N，pandas 後處理；治理查詢路徑）。",
            f"來源：{block_id}。",
        ]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence, result_table=table,
                                 trust_notes=notes, risk_level="low")

    def _answer_crossfact(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 116: cross-fact analytics (correlation / cohort / ratio).

        Aligns two facts on a shared key and answers questions that span them —
        "is high queue time linked to low yield (by lot)?", "worst-cycle-time 20%
        of lots — yield drop?", "yield per rework by product". Returns None when
        it isn't a resolvable two-fact question.
        """
        if not contracts:
            return None
        from ai4bi.blocks.contracts import BlockType
        facts = {b: c for b, c in contracts.items()
                 if getattr(c, "block_type", None) in (
                     BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact)}
        if len(facts) < 2:
            return None
        # A numeric column the prompt references, per fact.
        cols = {}
        for bid, c in facts.items():
            col = _resolve_numeric_column(prompt, normalized, c)
            if col:
                cols[bid] = col
        if len(cols) < 2:
            return None
        (ba, ca), (bb, cb) = list(cols.items())[:2]
        shared = ({x.name for x in facts[ba].columns}
                  & {x.name for x in facts[bb].columns})
        key = _pick_join_key(prompt, normalized, shared)
        if key is None:
            return None

        def _agg(col: str) -> str:
            low = col.lower()
            return "AVG" if any(t in low for t in ("pct", "rate", "ratio", "_hr", "_min", "avg", "yield", "density")) else "SUM"

        from ai4bi.analysis.crossfact import align_two_facts, cohort_by_quantile, correlate_facts
        try:
            merged = align_two_facts(
                contracts, block_a=ba, col_a=ca, agg_a=_agg(ca), alias_a=ca,
                block_b=bb, col_b=cb, agg_b=_agg(cb), alias_b=cb, join_key=key)
        except Exception:  # noqa: BLE001
            return None
        if merged is None or merged.empty:
            return None

        hay = f"{prompt.lower()} {normalized}"
        is_cohort = bool(re.search(r"前\s*\d+\s*%|\d+\s*%|分位|cohort|quantile|四分位", hay))
        is_corr = any(t in hay for t in ("關聯", "相關", "關係", "correlat", "linked", "有沒有關"))

        if is_corr and not is_cohort:
            stat = correlate_facts(merged, ca, cb)
            if stat is None:
                return None
            sentence = (f"「{ca}」與「{cb}」（依 {key} 對齊，n={stat['n']}）相關係數 r={stat['r']}"
                        f"（{stat['direction']}相關，{stat['strength']}）。")
            notes = [f"跨表分析：各自彙總到 {key} 後對齊計算 Pearson 相關（非明細 join）。"]
            intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                              trust_notes=notes, risk_level="low")
            return NL2ProposalResult(intent=intent, message=sentence, result_table=merged,
                                     trust_notes=notes, risk_level="low")
        if is_cohort:
            # bucket by the move-side metric (cycle/queue proxy), outcome = the other
            table = cohort_by_quantile(merged, ca, cb, q=5)
            if table is None or table.empty:
                return None
            sentence = f"依「{ca}」分位分組，看各組「{cb}」（共 {len(table)} 組）。"
            notes = [f"跨表 cohort：依 {key} 對齊後，用 {ca} 分位分桶，平均 {cb}。"]
            intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                              trust_notes=notes, risk_level="low")
            return NL2ProposalResult(intent=intent, message=sentence, result_table=table,
                                     trust_notes=notes, risk_level="low")
        # default: ratio A/B per key
        merged = merged.copy()
        merged[f"{ca}/{cb}"] = (merged[ca] / merged[cb].replace(0, float("nan"))).round(3)
        sentence = f"依「{key}」計算「{ca} ÷ {cb}」（跨表比值，共 {len(merged)} 列）。"
        notes = [f"跨表比值：各自彙總到 {key} 後相除（非明細 join）。"]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence, result_table=merged,
                                 trust_notes=notes, risk_level="low")

    def _answer_breakdown(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 114: plain "metric BY dimension" breakdown ("各製程站的移動次數").

        Like ranking but without a superlative — groups a metric by a categorical
        dimension and returns every group (sorted desc). Returns None to fall
        through when no metric/dimension resolves.
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None
        idx = SchemaIndex.build(contracts)
        match = idx.best_metric_match(prompt, normalized)
        if match is None:
            return None
        block_id, metric_name, alias = match.block_id, match.metric_name, match.alias
        dim_col = _resolve_decomp_dimension(idx, prompt, normalized, contracts, block_id)
        if dim_col is None:
            return None

        from ai4bi.query_spec import BlockRef, DimensionRef, SortDirection, SortSpec, VisualQuerySpec
        spec = VisualQuerySpec(
            spec_id=f"by_{metric_name}", block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            dimensions=[DimensionRef(block_id, dim_col, dim_col)],
            sort=[SortSpec(alias, SortDirection.desc)], inherit_global_filter=False)
        try:
            df = executor.run(spec)
        except Exception:  # noqa: BLE001
            return None
        if df is None or df.empty:
            return None
        sentence = f"「{alias}」依「{dim_col}」分組（共 {len(df)} 組）。"
        notes = [f"依「{dim_col}」分組彙總「{alias}」（治理查詢路徑），來源：{block_id}。"]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence, result_table=df,
                                 trust_notes=notes, risk_level="low")

    def _answer_ranking(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 087: "我最賺的 5 個商品" / "賣最差的品類" → ranked table answer.

        Resolves a metric + a categorical dimension, runs a grouped query with
        the executor's existing sort+limit, and returns the ranked rows. Returns
        None to fall through when metric/dimension/executor can't be resolved.
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None

        idx = SchemaIndex.build(contracts)
        metric = idx.best_metric_match(prompt, normalized)
        if metric is None:
            return None
        block_id, metric_name, alias = metric.block_id, metric.metric_name, metric.alias

        dim_col = _resolve_decomp_dimension(idx, prompt, normalized, contracts, block_id)
        if dim_col is None:
            return None

        n = _extract_rank_n(prompt, normalized)
        ascending = _ranking_is_ascending(prompt, normalized)
        unit = _metric_unit(contracts, block_id, metric_name)

        from ai4bi.query_spec import BlockRef, DimensionRef, SortDirection, SortSpec, VisualQuerySpec

        spec = VisualQuerySpec(
            spec_id=f"rank_{metric_name}",
            block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            dimensions=[DimensionRef(block_id, dim_col, dim_col)],
            sort=[SortSpec(alias, SortDirection.asc if ascending else SortDirection.desc)],
            limit=n,
            inherit_global_filter=False,
        )
        try:
            df = executor.run(spec)
        except Exception:  # noqa: BLE001
            return None
        if df is None or df.empty:
            return None

        superlative = "最低" if ascending else "最高"
        top = df.iloc[0]
        top_val = _format_metric_value(float(top[alias]) if alias in df.columns else None, unit) \
            if alias in df.columns else ""
        sentence = (f"{alias}{superlative}的前 {len(df)} 個「{dim_col}」。"
                    f"第一名：{top[dim_col]}（{top_val}）。")
        notes = [
            f"依「{alias}」對「{dim_col}」排序取前 {n}（治理查詢 sort+limit，認證語意層）。",
            f"來源：{block_id}。",
        ]
        intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(
            intent=intent, message=sentence, result_table=df,
            trust_notes=notes, risk_level="low",
        )

    def _run_panel_analysis(
        self,
        prompt: str,
        normalized: str,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 086: route a question to a pre-built pandas analytics engine.

        Churn/RFM, declining-streaks and market-basket are fully implemented and
        tested but were sidebar-only. This bridges them to the ask box: it picks
        the analysis from keywords, auto-guesses the columns (same heuristics the
        panels use), materialises the fact, runs the engine, and returns a
        summary sentence + the result table. Returns None to fall through.
        """
        if not contracts:
            return None
        kind = _detect_panel_analysis(prompt, normalized)
        if kind is None:
            return None

        from ai4bi.blocks.contracts import BlockType
        from ai4bi.blocks.datastore import materialize_dataframe

        # Pick the fact block whose columns best fit this analysis.
        facts = {
            bid: c for bid, c in contracts.items()
            if getattr(c, "block_type", None) in (
                BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact)
        }
        if not facts:
            return None

        best = _pick_fact_for_analysis(facts, kind)
        if best is None:
            return None
        block_id, contract, cols_map = best

        # Round 115: prompt-aware override for entity×value analyses. Prefer the
        # block where the dimension the user NAMED (機台/製程/product) and the
        # measure they NAMED (良率/等待/缺陷) both resolve, instead of guessing
        # from column order (which picked lot_id / queue_time for '機台良率').
        if kind in ("decline", "dormant", "newproduct"):
            idx = SchemaIndex.build(contracts)
            for bid, c in facts.items():
                ent = _resolve_decomp_dimension(idx, prompt, normalized, contracts, bid)
                val = _resolve_numeric_column(prompt, normalized, c)
                date = _find_date_column(contracts, bid)
                if ent and val and date:
                    block_id, contract, cols_map = bid, c, {
                        "entity": ent, "date": date, "value": val}
                    break

        if kind in ("decline", "dormant", "newproduct"):
            # Period: explicit word wins; default monthly for dormancy/launches,
            # weekly for streaks (more periods available).
            period = _extract_answer_period(normalized, prompt)
            default = "week" if kind == "decline" else "month"
            cols_map["period"] = {"all": default, "year": "month"}.get(period, period)
        if kind == "decline":
            sm = re.search(r"連續\s*(\d+)|(\d+)\s*(?:期|個月|個週|週|周|months?)", f"{prompt} {normalized}")
            cols_map["min_streak"] = int(next(g for g in sm.groups() if g)) if sm else 3

        try:
            df = materialize_dataframe(contract)
        except Exception:  # noqa: BLE001 — external connectors aren't materialisable
            return None
        if df is None or df.empty:
            return None

        table, sentence = _execute_panel_analysis(kind, df, cols_map)
        if table is None or table.empty:
            # Round 115: the analysis ran but found nothing qualifying. Report
            # that honestly instead of falling through to "unsupported intent".
            msg = f"沒有符合「{_PANEL_LABELS[kind]}」條件的結果。"
            intent = AIIntent(intent_kind="analysis_request", target_scope="semantic_model",
                              trust_notes=[msg], risk_level="low")
            return NL2ProposalResult(intent=intent, message=msg,
                                     trust_notes=[msg], risk_level="low")

        notes = [
            f"使用「{_PANEL_LABELS[kind]}」分析（純 pandas，於記憶體資料計算）。",
            f"自動選用欄位：{', '.join(f'{k}={v}' for k, v in cols_map.items() if v)}。",
            f"來源資料集：{block_id}。",
        ]
        intent = AIIntent(
            intent_kind="analysis_request", target_scope="semantic_model",
            trust_notes=notes, risk_level="low",
        )
        return NL2ProposalResult(
            intent=intent, message=sentence, result_table=table,
            trust_notes=notes, risk_level="low",
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

    def _explain_change(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Round 081: answer "why did <metric> change?" by decomposing the
        period-over-period delta across a dimension.

        Reuses time_intelligence.compute_grouped_comparison (today only reachable
        from the sidebar panel) to rank the biggest contributors to the change,
        and returns them as a sentence. Returns None to fall through when a
        metric/dimension/date can't be resolved.
        """
        executor = getattr(self, "_executor", None)
        if executor is None or not contracts:
            return None

        idx = SchemaIndex.build(contracts)
        metric = idx.best_metric_match(prompt, normalized)
        if metric is None:
            return None
        block_id, metric_name, alias = metric.block_id, metric.metric_name, metric.alias

        dim_col = _resolve_decomp_dimension(idx, prompt, normalized, contracts, block_id)
        if dim_col is None:
            return None
        date_col = _find_date_column(contracts, block_id)
        if date_col is None or date_col == dim_col:
            return None

        period = _extract_answer_period(normalized, prompt)
        if period == "all":
            period = "month"  # decomposition needs two comparable windows

        from ai4bi.analysis.time_intelligence import compute_grouped_comparison
        from ai4bi.query_spec import BlockRef, VisualQuerySpec

        base = VisualQuerySpec(
            spec_id=f"explain_{metric_name}",
            block_refs=[BlockRef(block_id)],
            metrics=[MetricRef(block_id, metric_name, alias)],
            inherit_global_filter=False,
        )
        try:
            df = compute_grouped_comparison(
                executor, base, date_block_id=block_id, date_column=date_col,
                dimension_col=dim_col, period=period, metric_col=alias,
            )
        except Exception:  # noqa: BLE001
            return None
        if df is None or df.empty:
            return None

        unit = _metric_unit(contracts, block_id, metric_name)
        total = float(df["delta"].sum())
        cur_total = float(df["current"].sum())
        prev_total = float(df["previous"].sum())
        delta_pct = ((cur_total - prev_total) / abs(prev_total) * 100.0) if prev_total else None
        scope = _PERIOD_TITLE.get(period, period)

        sentence = _compose_decomposition_sentence(
            alias, dim_col, df, total, unit, scope
        )
        notes = [
            f"指標「{alias}」依「{dim_col}」拆解（{scope} vs 前一期），重用治理查詢路徑。",
            "依各維度對總變化的貢獻排序，未產生自由 SQL。",
        ]
        answer = DirectAnswer(
            question=prompt.strip(),
            metric_block_id=block_id,
            metric_name=metric_name,
            metric_alias=alias,
            sentence=sentence,
            value=cur_total,
            period=period,
            previous=prev_total,
            delta_pct=delta_pct,
            unit=unit,
            trust_notes=notes,
        )
        intent = AIIntent(
            intent_kind="analysis_request",
            target_scope="semantic_model",
            selection=SemanticSelection(metric_block_id=block_id, metric_name=metric_name),
            trust_notes=notes,
            risk_level="low",
        )
        return NL2ProposalResult(
            intent=intent, message=sentence, direct_answer=answer,
            trust_notes=notes, risk_level="low",
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
    # Round 080: measure (post-aggregate) filter → HAVING
    # ------------------------------------------------------------------

    def _measure_filter_change(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
    ) -> "NL2ProposalResult | None":
        """Turn "customers who bought more than 3 times" into a HAVING predicate.

        Adds a post-aggregate measure filter to a target visual. The measure
        must already be projected by the visual (visual-level measure filter),
        which the executor enforces — so we resolve the threshold against the
        visual's own metrics. Returns None to fall through when no target/metric
        can be resolved.
        """
        found = _find_visual(report, selected_component_id)
        if found is None:
            # Fall back to the first visual that both groups and aggregates —
            # HAVING is only meaningful on a grouped, aggregated visual.
            for pid, page in report.pages.items():
                for vid, v in page.visuals.items():
                    if v.query.metrics and v.query.dimensions:
                        found = (pid, vid, v)
                        break
                if found:
                    break
        if found is None:
            return None
        page_id, visual_id, visual = found
        if not visual.query.metrics:
            return None

        parsed = _extract_measure_filter(prompt, normalized, visual)
        if parsed is None:
            return None
        metric, operator, value = parsed

        before = [
            {"block_id": h.block_id, "metric_name": h.metric_name,
             "operator": h.operator.value, "value": h.value}
            for h in visual.query.having
        ]
        # Replace any existing predicate on the same metric+operator, then append.
        after = [
            h for h in before
            if not (h["metric_name"] == metric.metric_name and h["operator"] == operator.value)
        ]
        after.append({
            "block_id": metric.block_id,
            "metric_name": metric.metric_name,
            "operator": operator.value,
            "value": value,
        })
        label_name = metric.alias or metric.metric_name
        op_sym = {"gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "eq": "=", "neq": "≠"}.get(operator.value, operator.value)
        notes = [
            f"在彙總後篩選「{label_name}」{op_sym} {value}（HAVING，逐組篩選）。",
            "僅篩選此圖已投影的指標，仍走認證語意層；套用後重新查詢。",
        ]
        path = f"pages/{page_id}/visuals/{visual_id}/query/having"
        proposal = ReportProposal(
            description=f"Measure filter: {label_name} {op_sym} {value}",
            changes=[ReportChange(
                path=path, label=f"HAVING: {label_name} {op_sym} {value}",
                before=before, after=after, affects_data=True,
            )],
            target_component_id=visual_id,
        )
        intent = AIIntent(
            intent_kind="analysis_request", target_scope=f"visual:{visual_id}",
            suggested_visuals=[visual_id], trust_notes=notes, risk_level="medium",
        )
        return NL2ProposalResult(
            intent=intent,
            message=f"已建立彙總後篩選：{label_name} {op_sym} {value}。",
            proposal=proposal, trust_notes=notes, risk_level="medium",
        )

    # ------------------------------------------------------------------
    # Round 088: "are we on track?" — read back KPI pacing
    # ------------------------------------------------------------------

    def _answer_pacing(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        contracts: dict[str, Any] | None,
    ) -> "NL2ProposalResult | None":
        """Answer "達標了嗎 / are we on track?" by reading each KPI's target.

        Computes the KPI's current value the same way the card does (trailing
        window when compare_period is set, else the plain aggregate) and reports
        on-track / behind. Returns None when no executor; a guiding message when
        no KPI has a target.
        """
        executor = getattr(self, "_executor", None)
        if executor is None:
            return None

        from ai4bi.ui.components.kpi_card import _pacing_status

        targets = []
        for pid, page in report.pages.items():
            for vid, v in page.visuals.items():
                if v.visualization.visual_type != VisualType.kpi_card:
                    continue
                tgt = v.visualization.extra.get("target")
                if tgt is None or not v.query.metrics:
                    continue
                targets.append((pid, vid, v, float(tgt)))

        if not targets:
            return self._unsupported(
                "目前沒有任何 KPI 設定目標。試試「把營收目標設為 100 萬」之後再問達標進度。",
                target_scope="report",
            )

        lines: list[str] = []
        headline_value = None
        for _pid, _vid, v, tgt in targets:
            value = self._kpi_current_value(executor, v)
            if value is None:
                continue
            if headline_value is None:
                headline_value = value
            good_if = v.visualization.extra.get("target_good_if") or _infer_target_good_if(v)
            pacing = _pacing_status(value, tgt, good_if)
            label = v.visualization.title or v.query.metrics[0].alias or v.query.metrics[0].metric_name
            if pacing:
                _frac, cap, _ok = pacing
                lines.append(f"「{label}」：{cap}")
        if not lines:
            return None

        sentence = "　|　".join(lines)
        notes = ["依各 KPI 設定的目標即時計算進度（與儀表板 KPI 同源）。"]
        answer = DirectAnswer(
            question=prompt.strip(),
            metric_block_id=targets[0][2].query.metrics[0].block_id,
            metric_name=targets[0][2].query.metrics[0].metric_name,
            metric_alias="達標進度",
            sentence=sentence,
            value=headline_value,
            period="all",
            trust_notes=notes,
        )
        intent = AIIntent(intent_kind="analysis_request", target_scope="report",
                          trust_notes=notes, risk_level="low")
        return NL2ProposalResult(intent=intent, message=sentence, direct_answer=answer,
                                 trust_notes=notes, risk_level="low")

    def _kpi_current_value(self, executor, visual) -> float | None:
        """Current value of a KPI visual — trailing window if compare_period set."""
        from ai4bi.query_spec import BlockRef, VisualQuerySpec
        metric = visual.query.metrics[0]
        alias = metric.alias or metric.metric_name
        extra = visual.visualization.extra or {}
        compare_period = extra.get("compare_period")
        date_col = extra.get("compare_date_column")
        base = VisualQuerySpec(
            spec_id=f"pace_{metric.metric_name}",
            block_refs=[BlockRef(metric.block_id)],
            metrics=[MetricRef(metric.block_id, metric.metric_name, alias)],
            inherit_global_filter=False,
        )
        if compare_period and date_col:
            from ai4bi.analysis.time_intelligence import compute_period_comparison
            comp = compute_period_comparison(
                executor, base, date_block_id=metric.block_id, date_column=date_col,
                period=compare_period, metric_col=alias)
            if comp is not None and comp.current is not None:
                return comp.current
        try:
            df = executor.run(base)
        except Exception:  # noqa: BLE001
            return None
        return _first_scalar(df, alias)

    # ------------------------------------------------------------------
    # Round 084: set a KPI goal / target (pacing)
    # ------------------------------------------------------------------

    def _set_target(
        self,
        prompt: str,
        normalized: str,
        report: ExecutableReportSpec,
        selected_component_id: str | None,
    ) -> "NL2ProposalResult | None":
        """"把營收目標設為 100 萬" → set a KPI card's target for pacing.

        Resolves a KPI-card visual (the selected one, or the KPI whose metric
        keyword appears in the prompt, else the first KPI) and stages a
        display-only change to visualization.extra["target"].
        """
        value = _extract_target_value(prompt, normalized)
        if value is None:
            return None

        # Resolve the target KPI visual.
        found = _find_visual(report, selected_component_id)
        target_tuple = None
        if found is not None and found[2].visualization.visual_type == VisualType.kpi_card:
            target_tuple = found
        if target_tuple is None:
            hay = f"{prompt.lower()} {normalized}"
            first_kpi = None
            for pid, page in report.pages.items():
                for vid, v in page.visuals.items():
                    if v.visualization.visual_type != VisualType.kpi_card or not v.query.metrics:
                        continue
                    if first_kpi is None:
                        first_kpi = (pid, vid, v)
                    m = v.query.metrics[0]
                    for kw in {m.metric_name.lower(), (m.alias or "").lower()}:
                        if kw and kw in hay:
                            target_tuple = (pid, vid, v)
                            break
                    if target_tuple:
                        break
                if target_tuple:
                    break
            if target_tuple is None:
                target_tuple = first_kpi
        if target_tuple is None:
            return self._unsupported(
                "找不到可設定目標的 KPI 卡。請先選擇一張 KPI 卡。",
                target_scope=_target_scope(selected_component_id),
            )

        page_id, visual_id, visual = target_tuple
        metric_label = visual.visualization.title or (
            visual.query.metrics[0].alias or visual.query.metrics[0].metric_name
        )
        before = visual.visualization.extra.get("target")
        path = f"pages/{page_id}/visuals/{visual_id}/visualization/extra/target"
        # Honesty fix (Round 088): also set good_if so a lower-is-better KPI
        # (return rate / cost / churn) doesn't render an inverted progress bar.
        good_if = _infer_target_good_if(visual)
        good_if_before = visual.visualization.extra.get("target_good_if")
        good_if_path = f"pages/{page_id}/visuals/{visual_id}/visualization/extra/target_good_if"
        sense = "越低越好" if good_if == "lte" else "越高越好"
        notes = [
            f"為「{metric_label}」設定目標 {value:,.0f}（{sense}），顯示達成進度條。",
            "顯示用變更，不影響查詢數字。",
        ]
        changes = [ReportChange(path=path, label=f"KPI 目標：{metric_label}",
                                before=before, after=value, affects_data=False)]
        if good_if_before != good_if:
            changes.append(ReportChange(
                path=good_if_path, label="目標方向（越高/越低越好）",
                before=good_if_before, after=good_if, affects_data=False))
        proposal = ReportProposal(
            description=f"Set target for '{metric_label}' = {value:,.0f}",
            changes=changes,
            target_component_id=visual_id,
        )
        intent = AIIntent(intent_kind="analysis_request", target_scope=f"visual:{visual_id}",
                          suggested_visuals=[visual_id], trust_notes=notes, risk_level="low")
        return NL2ProposalResult(
            intent=intent, message=f"已為「{metric_label}」設定目標 {value:,.0f}（{sense}）。",
            proposal=proposal, trust_notes=notes, risk_level="low",
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
            "pivot": VisualType.pivot, "matrix": VisualType.pivot,
            "map": VisualType.map, "geo": VisualType.map,  # Round 089
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


# --- Round 087: Top-N ranking ("best / worst") parsing -----------------------

_RANK_TRIGGERS: tuple[str, ...] = (
    "最高", "最低", "最多", "最少", "最賺", "最好", "最差", "最大", "最小",
    "最長", "最久", "最短", "最快", "最慢", "最忙", "最閒", "最嚴重", "最常",
    "賣最", "排名", "排行", "前幾", "前十", "前五", "前三",
    "top ", "bottom ", "best ", "worst ", "highest", "lowest", "ranking", "rank ",
    "longest", "shortest", "slowest", "fastest", "most ", "least ",
)
_RANK_ASC_WORDS: tuple[str, ...] = (
    "最低", "最少", "最差", "最小", "最短", "最快", "最閒", "賣最差", "賣最少", "最不", "墊底",
    "bottom", "worst", "lowest", "least", "fewest", "shortest", "fastest",
)


_BREAKDOWN_MARKERS: tuple[str, ...] = (
    "各", "每個", "每一", "每種", "每類", "依", "按", "照", "分布", "分佈", "分組",
    " by ", " per ", "breakdown", "group by", "分別",
)
_EDIT_VERBS: tuple[str, ...] = ("改成", "換成", "改為", "改用", "變成", "change to", "switch to")


def _looks_like_breakdown(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    if any(v in hay for v in _EDIT_VERBS):
        return False  # "改成依月份" is an edit, not a breakdown answer
    return any(m in hay for m in _BREAKDOWN_MARKERS)


def _looks_like_ranking(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    if any(t in hay for t in _RANK_TRIGGERS):
        return True
    # "前 5 名 / top 5" expressed with a number.
    return bool(re.search(r"(前\s*\d+|top\s*\d+|bottom\s*\d+)", hay))


def _ranking_is_ascending(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    return any(w in hay for w in _RANK_ASC_WORDS)


def _extract_rank_n(prompt: str, normalized: str, default: int = 5) -> int:
    hay = f"{prompt.lower()} {normalized}"
    m = re.search(r"(?:前|top|bottom|前面|頭)\s*(\d+)", hay)
    if m is None:
        m = re.search(r"(\d+)\s*(?:個|名|筆|項|大|個商品|個地區)", hay)
    if m:
        try:
            n = int(m.group(1))
            return max(1, min(n, 100))
        except ValueError:
            pass
    return default


# --- Round 108: two-entity comparison ----------------------------------------

# Unambiguous compare cues (so "營收和訂單" — a list, not a comparison — is ignored).
_COMPARE_CUES = ("比較", "對比", "相比", "比一比", " vs ", " versus ", " v.s ", "對上", "比起")
_COMPARE_CONNECTORS = (" vs ", " versus ", " v.s ", "對上", "對比", "相比", "比起",
                       "跟", "和", "與", "還是", "、", "對")


def _looks_like_entity_compare(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    return any(c in hay for c in _COMPARE_CUES)


def _clean_operand(s: str, side: str) -> str | None:
    s = s.strip(" ,。，?？!！的")
    for w in ("請比較", "幫我比較", "比較一下", "比一比", "比較", "看看", "對比一下",
              "對比", "誰的", "哪個", "哪一個", "compare", "誰", "的"):
        s = s.replace(w, " ")
    parts = [p for p in re.split(r"[的\s,，、]+", s) if p]
    if not parts:
        return None
    return parts[-1] if side == "left" else parts[0]


def _extract_compare_operands(prompt: str, normalized: str) -> "tuple[str, str] | None":
    text = prompt.strip()
    for conn in _COMPARE_CONNECTORS:
        i = text.find(conn)
        if i > 0:
            a = _clean_operand(text[:i], "left")
            b = _clean_operand(text[i + len(conn):], "right")
            if a and b and a != b and len(a) >= 1 and len(b) >= 1:
                return a, b
    return None


# --- Round 105: postprocess / forecast analytics charts ----------------------

_PARETO_TRIGGERS = ("pareto", "柏拉圖", "柏拉图", "abc 分析", "abc分析", "80/20", "80-20",
                    "關鍵少數", "关键少数", "重要少數", "80%的營收", "8 成", "八成")
_SHARE_TRIGGERS = ("佔總比", "占總比", "佔比", "占比", "百分比", "% of total", "share of total",
                   "占總", "佔總", "比重", "佔多少比例", "占多少比例")
_MOVING_AVG_TRIGGERS = ("移動平均", "移动平均", "moving average", "moving avg", "平滑", "smooth",
                        "均線", "ma 線", "ma線")
_FORECAST_TRIGGERS = ("預測", "预测", "forecast", "未來幾", "未来几", "推估", "外推",
                      "下個月會", "預估", "project")


def _detect_analytics_chart(hay: str) -> str | None:
    if any(t in hay for t in _PARETO_TRIGGERS):
        return "pareto"
    if any(t in hay for t in _MOVING_AVG_TRIGGERS):
        return "moving_avg"
    if any(t in hay for t in _FORECAST_TRIGGERS):
        return "forecast"
    if any(t in hay for t in _SHARE_TRIGGERS):
        return "share"
    return None


def _extract_analytics_n(prompt: str, normalized: str) -> int | None:
    m = re.search(r"(\d+)\s*(?:期|個月|個週|週|周|months?|weeks?|points?)", f"{prompt} {normalized}")
    if m:
        try:
            return max(1, min(int(m.group(1)), 52))
        except ValueError:
            return None
    return None


def _unique_id(base: str, existing: set) -> str:
    vid, c = base, 1
    while vid in existing:
        vid = f"{base}_{c}"; c += 1
    existing.add(vid)
    return vid


# --- Round 100: calendar YoY (same period last year) -------------------------

_CALENDAR_YOY_TRIGGERS: tuple[str, ...] = (
    "同期", "去年同月", "去年同季", "去年同期", "同月去年", "年增率", "年增",
    "same month last year", "same period last year", "same quarter last year",
    "year over year", "year-over-year", "vs last year", "yoy vs",
)


def _looks_like_calendar_yoy(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    return any(t in hay for t in _CALENDAR_YOY_TRIGGERS)


# --- Round 097: digest / anomaly insight routing -----------------------------

_DIGEST_TRIGGERS: tuple[str, ...] = (
    "摘要", "總結", "重點", "概況", "整體狀況", "本週如何", "近況", "給我重點",
    "summary", "digest", "overview", "tldr", "recap", "how are we doing",
)
_ANOMALY_TRIGGERS: tuple[str, ...] = (
    "異常", "不對勁", "怪怪", "有什麼問題", "哪裡有問題", "可疑", "outlier",
    "anomaly", "anomalies", "anything wrong", "what's off", "unusual",
)


def _looks_like_insights(prompt: str, normalized: str) -> str | None:
    hay = f"{prompt.lower()} {normalized}"
    if any(t in hay for t in _ANOMALY_TRIGGERS):
        return "anomaly"
    if any(t in hay for t in _DIGEST_TRIGGERS):
        return "digest"
    return None


# --- Round 096: weekday / hour seasonality parsing ---------------------------

_DOW_TRIGGERS: tuple[str, ...] = (
    "星期幾", "週幾", "周幾", "禮拜幾", "星期", "哪一天", "哪幾天", "哪天最",
    "day of week", "weekday", "busiest day", "which day", "by day of week",
)
_HOUR_TRIGGERS: tuple[str, ...] = (
    "時段", "幾點", "哪個小時", "哪個時間", "哪個時段", "busiest hour",
    "what hour", "time of day", "by hour", "peak hour",
)


def _looks_like_seasonality(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    return any(t in hay for t in _DOW_TRIGGERS) or any(t in hay for t in _HOUR_TRIGGERS)


def _is_hour_seasonality(hay: str) -> bool:
    return any(t in hay for t in _HOUR_TRIGGERS)


# --- Round 091: cold-start grouped measure filter ("buyers with > N orders") -

_ENTITY_CUE_HINTS: tuple[str, ...] = (
    "客戶", "顧客", "會員", "customer", "member", "buyer", "client",
    "商品", "產品", "品項", "product", "item", "sku", "門市", "store",
)
_COUNT_CUE_HINTS: tuple[str, ...] = (
    "次", "筆", "訂單", "下單", "購買", "買", "回購", "單",
    "times", "orders", "order", "purchase", "bought", "transactions",
)


def _looks_like_segment_count(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    if _measure_operator(hay) is None or re.search(r"\d", hay) is None:
        return False
    return (any(h in hay for h in _ENTITY_CUE_HINTS)
            and any(h in hay for h in _COUNT_CUE_HINTS))


def _resolve_entity_dimension(idx, prompt: str, normalized: str, contracts):
    """Pick the categorical entity dimension to group by (customer / product …)."""
    hay = f"{prompt.lower()} {normalized}"
    best, best_block, best_len = None, None, 0
    for kw, e in idx._dims.items():
        if (kw in hay and _is_categorical_col(contracts, e.block_id, e.column_name)
                and len(kw) > best_len):
            best, best_block, best_len = e.column_name, e.block_id, len(kw)
    return best, best_block


def _default_count_metric(contracts, block_id: str):
    """A count-like metric on the block (orders/count), else the first SUM metric."""
    contract = (contracts or {}).get(block_id)
    metrics = getattr(contract, "metrics", None) or []
    for m in metrics:
        nm = m.name.lower()
        meth = getattr(getattr(m, "disaggregation_method", None), "value", "")
        if meth == "count" or any(t in nm for t in ("count", "order", "orders", "qty", "quantity", "次", "筆")):
            return m.name, m.name.replace("_", " ").title()
    for m in metrics:
        if getattr(getattr(m, "disaggregation_method", None), "value", "") == "sum":
            return m.name, m.name.replace("_", " ").title()
    return None


# --- Round 090: per-group Top-N parsing --------------------------------------

_PER_GROUP_MARKERS: tuple[str, ...] = (
    "每個", "每一個", "每家", "每間", "每位", "各個", "各家", "各",
    "per ", "each ", "within each", "by each", "for each",
)


def _looks_like_grouped_topn(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    if not any(m in hay for m in _PER_GROUP_MARKERS):
        return False
    # Needs a ranking cue too (最/暢銷/賺/top/best/前N) — otherwise it's a plain
    # "show each store's revenue", not a per-group ranking.
    return (any(t in hay for t in _RANK_TRIGGERS)
            or any(w in hay for w in ("暢銷", "熱賣", "賺", "賣最"))
            or bool(re.search(r"(前\s*\d+|top\s*\d+)", hay)))


def _is_categorical_col(contracts, block_id: str, col: str) -> bool:
    contract = (contracts or {}).get(block_id)
    for c in getattr(contract, "columns", None) or []:
        if c.name == col:
            return getattr(c, "data_type", "") in ("string", "str", "object", "text", "varchar")
    return False


def _resolve_two_dims(idx, prompt: str, normalized: str, contracts, block_id: str):
    """Resolve (outer_group_col, inner_entity_col) for a per-group Top-N.

    Outer = the dimension after a per/each marker; inner = the best other
    categorical dimension keyword. Both must be categorical columns on
    ``block_id``. Returns (None, None) when they can't be resolved.
    """
    hay = f"{prompt.lower()} {normalized}"
    outer = None
    for marker in _PER_GROUP_MARKERS:
        i = hay.find(marker)
        if i < 0:
            continue
        # Chinese has no word spaces, so match the longest dimension keyword the
        # text right after the marker *starts with* (handles "每個地區營收..." and
        # the spaced English "per store").
        tail = hay[i + len(marker):].lstrip(" 的")
        cand, clen = None, 0
        for kw, e in idx._dims.items():
            if (e.block_id == block_id and tail.startswith(kw) and len(kw) > clen
                    and _is_categorical_col(contracts, block_id, e.column_name)):
                cand, clen = e.column_name, len(kw)
        if cand:
            outer = cand
            break
    if outer is None:
        return None, None

    inner = None
    best_len = 0
    for kw, e in idx._dims.items():
        if (e.block_id == block_id and e.column_name != outer
                and _is_categorical_col(contracts, block_id, e.column_name)
                and kw in hay and len(kw) > best_len):
            inner = e.column_name
            best_len = len(kw)
    return outer, inner


# --- Round 089: location-column detection for map visuals --------------------

# Strong hints resolve to coordinates (city/region/縣市); weak hints (store/門市)
# are usually too granular for the geo lookup, so they're only a fallback.
_STRONG_LOCATION_HINTS: tuple[str, ...] = (
    "city", "region", "country", "state", "province", "county",
    "市", "縣", "省", "城市", "縣市", "地區", "國家", "geo",
)
_WEAK_LOCATION_HINTS: tuple[str, ...] = (
    "store", "branch", "location", "area", "district", "門市", "分店",
    "據點", "地點", "區",
)


def _find_location_col(contract) -> str | None:
    """Return the best string column that looks like a geographic location.

    Prefers coordinate-resolvable levels (city/region/縣市) over store-level
    names, since the map's geo lookup keys on administrative names.
    """
    if contract is None:
        return None
    cols = [
        c.name for c in (getattr(contract, "columns", []) or [])
        if getattr(c, "data_type", "") in ("string", "str", "object", "text", "varchar")
        and not c.name.lower().endswith(("_id", "_code"))
    ]
    for hints in (_STRONG_LOCATION_HINTS, _WEAK_LOCATION_HINTS):
        for name in cols:
            if any(h in name.lower() for h in hints):
                return name
    return None


# --- Round 086: NL routing to pandas analytics engines -----------------------

_PANEL_LABELS = {
    "churn": "客戶流失風險 / RFM",
    "decline": "連續下滑偵測",
    "basket": "商品關聯（常一起買）",
    "repeat": "回頭客 vs 一次性客",
    "dormant": "滯銷 / 停售商品",
    "newproduct": "新品上市表現",
    "basketsize": "客單品項數 / 籃子大小",
}
_BASKETSIZE_TRIGGERS = ("客單品項", "一單幾", "一次買幾", "平均幾件", "平均幾樣", "每單幾",
                        "籃子大小", "購物籃大小", "平均購買數", "items per order",
                        "items per basket", "basket size", "average basket", "每筆幾件",
                        "每單", "一單", "每筆", "買幾樣", "買幾件", "幾樣商品", "幾件商品")
_NEWPRODUCT_TRIGGERS = ("新品", "新商品", "新產品", "新上市", "最近上架", "這季新", "本季新",
                        "new product", "newly launched", "new arrival", "just launched",
                        "上新", "新推出")
_REPEAT_TRIGGERS = ("回頭客", "回購客", "回頭率", "一次性客", "一次性顧客", "回頭還是",
                    "多少回頭", "repeat customer", "repeat vs", "one-time", "one time customer",
                    "repeat or", "returning vs")
_DORMANT_TRIGGERS = ("滯銷", "賣不動", "沒在賣", "停售", "停止銷售", "不再賣", "賣不出去",
                     "沉睡商品", "呆料", "dead stock", "dormant", "stopped selling",
                     "no longer selling", "slow-moving", "slow moving")
_CHURN_TRIGGERS = ("流失", "churn", "rfm", "快走", "要走", "好久沒來", "沉睡", "回購率", "誰快不來", "快不來")
_DECLINE_TRIGGERS = ("連續下滑", "連續下跌", "一直下滑", "持續下滑", "持續下跌", "持續衰退",
                     "連續衰退", "一直在掉", "越來越差", "走弱", "連續成長", "持續成長",
                     "keeps declining", "declining", "consecutive", "months in a row",
                     "in a row", "streak")
_BASKET_TRIGGERS = ("一起買", "一起購買", "常買在一起", "搭配", "連帶", "商品關聯", "組合銷售",
                    "bought together", "market basket", "affinity", "cross-sell", "cross sell")

_CUSTOMER_HINTS = ("customer", "member", "client", "user", "客戶", "顧客", "會員")
_DATE_COL_HINTS = ("date", "_at", "time", "日期", "時間")
_MONEY_HINTS = ("revenue", "amount", "sales", "spend", "price", "total", "營收", "金額", "銷售", "消費")
_ENTITY_HINTS = ("product", "sku", "item", "store", "category", "商品", "品項", "門市", "品類",
                 # Round 114: fab entities
                 "tool", "step", "lot", "wafer", "vendor", "機台", "設備", "製程", "站",
                 "批", "晶圓", "供應商", "product_family", "tool_group", "tool_id", "step_name")
_VALUE_HINTS = ("revenue", "amount", "sales", "qty", "quantity", "count", "營收", "金額", "銷售", "數量",
                # Round 114: fab measures
                "yield", "queue", "move", "defect", "die", "rework", "良率", "等待",
                "移動", "缺陷", "晶粒", "重工", "time", "process")
_PRODUCT_HINTS = ("product", "item", "sku", "商品", "品項")
_BASKET_KEY_HINTS = ("customer", "member", "date", "_at", "store", "客戶", "門市", "日期")


def _detect_panel_analysis(prompt: str, normalized: str) -> str | None:
    hay = f"{prompt.lower()} {normalized}"
    if any(t in hay for t in _BASKETSIZE_TRIGGERS):
        return "basketsize"
    if any(t in hay for t in _NEWPRODUCT_TRIGGERS):
        return "newproduct"
    if any(t in hay for t in _DORMANT_TRIGGERS):
        return "dormant"
    if any(t in hay for t in _REPEAT_TRIGGERS):
        return "repeat"
    if any(t in hay for t in _CHURN_TRIGGERS):
        return "churn"
    if any(t in hay for t in _DECLINE_TRIGGERS):
        return "decline"
    if any(t in hay for t in _BASKET_TRIGGERS):
        return "basket"
    return None


_CROSSFACT_CUES: tuple[str, ...] = (
    "關聯", "相關", "關係", "有沒有關", "correlat", "linked",
    "比值", "換來", "每次", "分位", "四分位", "cohort", "quantile",
    "前20%", "前 20%", "前10%", "前 10%", "前30%", "前 30%",
)


def _looks_like_crossfact(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    if any(c in hay for c in _CROSSFACT_CUES):
        return True
    return bool(re.search(r"前\s*\d+\s*%", hay))


def _pick_join_key(prompt: str, normalized: str, shared: set) -> str | None:
    """Pick a shared join key, preferring one the prompt mentions."""
    if not shared:
        return None
    hay = f"{prompt.lower()} {normalized}"
    # prompt-mentioned key wins (lot/批, product/產品, week/週, wafer/晶圓)
    pref = [
        (("lot", "批", "批號"), "lot_id"),
        (("product", "產品", "品項", "family"), "product_family"),
        (("week", "週", "周"), "week"),
        (("wafer", "晶圓"), "wafer_id"),
    ]
    for words, col in pref:
        if col in shared and any(w in hay for w in words):
            return col
    # sensible defaults present in both facts
    for col in ("lot_id", "product_family", "wafer_id", "week"):
        if col in shared:
            return col
    return sorted(shared)[0]


def _resolve_numeric_column(prompt: str, normalized: str, contract) -> str | None:
    """Round 115: match the prompt to a NUMERIC column via tokens + ZH synonyms.

    So '良率' resolves the yield_pct column, '等待' the queue_time_hr column, etc.
    Used to make panel analyses (decline/dormant/launch) prompt-aware instead of
    guessing from column order. Returns None when nothing matches.
    """
    from ai4bi.ai.schema_index import _EN_TO_ZH
    hay = f"{prompt.lower()} {normalized}"
    best, best_len = None, 0
    for c in getattr(contract, "columns", []) or []:
        if getattr(c, "data_type", "") not in ("integer", "float", "int", "number",
                                               "numeric", "double", "bigint"):
            continue
        low = c.name.lower()
        if low.endswith(("_id", "_code", "_no")):
            continue
        kws: set[str] = set()
        for tok in re.split(r"[_\s]+", low):
            if tok:
                kws.add(tok)
                for zh in _EN_TO_ZH.get(tok, []):
                    kws.add(zh)
        for kw in kws:
            if len(kw) >= 2 and kw in hay and len(kw) > best_len:
                best, best_len = c.name, len(kw)
    return best


def _guess_col(cols: list[str], hints: tuple[str, ...], exclude: set[str] | None = None) -> str | None:
    exclude = exclude or set()
    for c in cols:
        if c in exclude:
            continue
        if any(h in c.lower() for h in hints):
            return c
    return None


def _pick_fact_for_analysis(facts: dict, kind: str):
    """Choose the fact block whose columns best satisfy ``kind`` + its column map."""
    best = None
    best_score = 0
    for bid, contract in facts.items():
        cols = [c.name for c in getattr(contract, "columns", [])]
        if kind == "churn":
            cmap = {
                "customer": _guess_col(cols, _CUSTOMER_HINTS),
                "date": _guess_col(cols, _DATE_COL_HINTS),
                "money": _guess_col(cols, _MONEY_HINTS),
            }
            required = ("customer", "date", "money")
        elif kind == "repeat":
            cmap = {
                "customer": _guess_col(cols, _CUSTOMER_HINTS),
                "date": _guess_col(cols, _DATE_COL_HINTS),
            }
            required = ("customer", "date")
        elif kind in ("decline", "dormant", "newproduct"):
            # value must be a NUMERIC, non-id column — else 'move' matches move_id
            # (a string) and the streak math crashes. (Round 114)
            numeric = {c.name for c in contract.columns
                       if getattr(c, "data_type", "") in ("integer", "float", "int", "number",
                                                          "numeric", "double", "bigint")}
            num_cols = [c for c in cols
                        if c in numeric and not c.lower().endswith(("_id", "_code", "_no"))]
            entity = _guess_col(cols, _ENTITY_HINTS)
            date = _guess_col(cols, _DATE_COL_HINTS)
            value = _guess_col(num_cols, _VALUE_HINTS, exclude={entity} if entity else set())
            cmap = {"entity": entity, "date": date, "value": value}
            required = ("entity", "date", "value")
        elif kind == "basketsize":
            item = _guess_col(cols, _PRODUCT_HINTS)
            keys = [c for c in cols
                    if any(h in c.lower() for h in _BASKET_KEY_HINTS) and c != item]
            qty = _guess_col(cols, ("qty", "quantity", "數量", "件數", "pcs"))
            cmap = {"item": item, "basket": keys[:3], "qty": qty}
            required = ("item", "basket")
        else:  # basket
            product = _guess_col(cols, _PRODUCT_HINTS)
            keys = [c for c in cols
                    if any(h in c.lower() for h in _BASKET_KEY_HINTS) and c != product]
            cmap = {"product": product, "basket": keys[:3]}
            required = ("product", "basket")
        score = sum(1 for r in required if cmap.get(r))
        if score == len(required) and score > best_score:
            best, best_score = (bid, contract, cmap), score
    return best


def _execute_panel_analysis(kind: str, df, cols_map: dict):
    """Run the chosen analysis; return (result_table, summary_sentence)."""
    if kind == "churn":
        from ai4bi.analysis.rfm import compute_rfm
        table = compute_rfm(df, cols_map["customer"], cols_map["date"], cols_map["money"])
        if table is None or table.empty:
            return table, ""
        at_risk = int(table["流失風險"].sum())
        top = table[table["流失風險"]].head(3)
        names = "、".join(str(x) for x in top[cols_map["customer"]].tolist())
        sentence = (f"共 {len(table)} 位客戶，其中 ⚠️ {at_risk} 位有流失風險。"
                    + (f"最該優先聯繫（高價值且久未回購）：{names}。" if names else ""))
        return table.head(25), sentence
    if kind == "basketsize":
        from ai4bi.analysis.basket import basket_size_distribution
        dist, summary = basket_size_distribution(
            df, cols_map["basket"], cols_map["item"], cols_map.get("qty"))
        if dist is None or dist.empty:
            return dist, ""
        sentence = (f"平均每籃 {summary['avg']} 項（中位數 {summary['median']}，"
                    f"最多 {summary['max']}），共 {summary['baskets']} 籃。")
        return dist, sentence
    if kind == "newproduct":
        from ai4bi.analysis.trends import new_products
        table = new_products(df, cols_map["entity"], cols_map["date"], cols_map["value"],
                             period=cols_map.get("period", "month"))
        if table is None or table.empty:
            return table, ""
        best = table.iloc[0]
        sentence = (f"{len(table)} 個新上市對象。表現最好："
                    f"{best[cols_map['entity']]}（上市以來 {best['上市以來']}）。")
        return table.head(25), sentence
    if kind == "dormant":
        from ai4bi.analysis.trends import dormant_products
        period = cols_map.get("period", "month")
        table = dormant_products(df, cols_map["entity"], cols_map["date"], cols_map["value"],
                                 period=period)
        if table is None or table.empty:
            return table, ""
        worst = table.iloc[0]
        sentence = (f"{len(table)} 個對象已停止銷售（沉睡）。"
                    f"最該注意：{worst[cols_map['entity']]}"
                    f"（最後售出 {worst['最後售出']}，已沉睡 {worst['沉睡期數']} 期）。")
        return table.head(25), sentence
    if kind == "repeat":
        from ai4bi.analysis.segments import repeat_vs_onetime
        table = repeat_vs_onetime(df, cols_map["customer"], cols_map["date"])
        if table is None or table.empty:
            return table, ""
        rep_rows = table[table["客戶類型"].str.startswith("回頭")]
        rep_pct = float(rep_rows["佔比%"].iloc[0]) if not rep_rows.empty else 0.0
        sentence = f"回頭客佔 {rep_pct}%，共 {int(table['人數'].sum())} 位客戶。"
        return table, sentence
    if kind == "decline":
        from ai4bi.analysis.trends import declining_streaks
        period = cols_map.get("period", "month")
        min_streak = cols_map.get("min_streak", 3)
        table = declining_streaks(df, cols_map["entity"], cols_map["date"], cols_map["value"],
                                  period=period, min_streak=min_streak)
        if table is None or table.empty:
            return table, ""
        worst = table.iloc[0]
        sentence = (f"{len(table)} 個對象連續下滑 ≥ {min_streak} 期。"
                    f"最嚴重：{worst[cols_map['entity']]}（連續 {worst['連續期數']} 期，"
                    f"最新一期 {worst['變化%']}%）。")
        return table.head(25), sentence
    # basket
    from ai4bi.analysis.basket import basket_affinity
    table = basket_affinity(df, cols_map["product"], cols_map["basket"])
    if table is None or table.empty:
        return table, ""
    top = table.iloc[0]
    sentence = (f"找到 {len(table)} 組常一起購買的商品。最強關聯："
                f"「{top['商品A']}」＋「{top['商品B']}」（提升度 {top['提升度']}）。")
    return table.head(25), sentence


# --- Round 084: KPI target / pacing parsing ----------------------------------

_TARGET_MARKERS: tuple[str, ...] = ("目標", "達標", "target", "goal", "objective")


def _looks_like_set_target(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    if not any(t in hay for t in _TARGET_MARKERS):
        return False
    # Needs a number and a "set" verb (設/設定/set/=) — "達標了嗎" is a question,
    # not a set-target command, so require an assignment cue.
    has_set = any(v in hay for v in ("設", "設定", "設為", "訂", "定為", "set", "="))
    return has_set and re.search(r"\d", hay) is not None


_LOWER_IS_BETTER_WORDS: tuple[str, ...] = (
    "退貨", "退款", "退回", "成本", "費用", "流失", "churn", "cost", "return",
    "error", "錯誤", "缺貨", "客訴", "抱怨", "complaint", "defect", "瑕疵", "延遲", "delay",
)


def _infer_target_good_if(visual) -> str:
    """Infer whether higher or lower is better for a KPI's target/pacing.

    Prefers an existing RAG config; otherwise reads the metric/title text for
    lower-is-better signals (return rate, cost, churn, ...). Defaults to "gte".
    """
    extra = visual.visualization.extra or {}
    rag = extra.get("rag") or {}
    if rag.get("good_if") in ("gte", "lte"):
        return rag["good_if"]
    text = " ".join(filter(None, [
        visual.visualization.title or "",
        *(m.alias or m.metric_name for m in visual.query.metrics),
    ])).lower()
    return "lte" if any(w in text for w in _LOWER_IS_BETTER_WORDS) else "gte"


_PACING_TRIGGERS: tuple[str, ...] = (
    "達標了嗎", "達標嗎", "有沒有達標", "達成了嗎", "達成率", "進度如何", "進度怎樣",
    "離目標", "達標進度", "on track", "on-track", "hit the target", "hit target",
    "reach the goal", "progress to target", "進度多少",
)


def _looks_like_pacing_question(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    return any(t in hay for t in _PACING_TRIGGERS)


def _extract_target_value(prompt: str, normalized: str) -> float | None:
    """Parse a target number, honouring 萬/億/k/m/百萬 multipliers."""
    hay = f"{prompt} {normalized}"
    m = re.search(r"(\d[\d,]*\.?\d*)\s*(億|百萬|萬|千|k|m|b)?", hay, re.IGNORECASE)
    if m is None:
        return None
    try:
        val = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    mult = {"億": 1e8, "百萬": 1e6, "萬": 1e4, "千": 1e3,
            "k": 1e3, "m": 1e6, "b": 1e9}.get((m.group(2) or "").lower())
    if mult:
        val *= mult
    return val


# --- Round 081: explain-change (decomposition) parsing -----------------------

_EXPLAIN_TRIGGERS: tuple[str, ...] = (
    "為何", "為什麼", "為甚麼", "原因", "怎麼會", "怎會",
    "變化分解", "拆解", "分解", "貢獻",
    "why did", "why is", "why has", "what caused", "what drove",
    "decompose", "break down", "breakdown", "contribut",
)
_CHANGE_WORDS: tuple[str, ...] = (
    "變", "升", "降", "增", "減", "漲", "跌", "掉", "成長", "衰退",
    "change", "changed", "dip", "drop", "fell", "fall", "rose", "rise",
    "grew", "grow", "increase", "decrease", "decline", "down", "up",
)
# "by <dim>" / "依/按/照 <dim>" decomposition-axis markers.
_DECOMP_BY_MARKERS: tuple[str, ...] = ("依", "按", "照", "以", "by ", "per ", "across ")


def _looks_like_explain_change(prompt: str, normalized: str) -> bool:
    hay = f"{prompt.lower()} {normalized}"
    has_trigger = any(t in hay for t in _EXPLAIN_TRIGGERS)
    if not has_trigger:
        return False
    # A "why" / "原因" needs an accompanying change word; explicit decompose
    # verbs ("拆解", "decompose", "break down") stand on their own.
    explicit = any(t in hay for t in ("變化分解", "拆解", "分解", "decompose", "break down", "breakdown"))
    return explicit or any(c in hay for c in _CHANGE_WORDS)


def _resolve_decomp_dimension(idx, prompt: str, normalized: str, contracts, block_id: str):
    """Pick a categorical column on ``block_id`` to decompose by.

    Prefers an explicit "by <dim>" phrase, else the best dimension keyword
    match; rejects date columns (decomposition needs a categorical axis).
    """
    hay = f"{prompt.lower()} {normalized}"

    def _is_categorical(col: str) -> bool:
        contract = contracts.get(block_id)
        for c in getattr(contract, "columns", None) or []:
            if c.name == col:
                if getattr(c, "data_type", "") in ("string", "str", "object", "text", "varchar"):
                    return True
                return False
        return False

    # Try the token right after a "by"/"依" marker first. Note: we check the
    # column exists & is categorical ON THE METRIC'S BLOCK rather than requiring
    # SchemaIndex to have attributed the dim to that block — denormalized facts
    # share column names (e.g. product_family on both move & yield facts), and
    # SchemaIndex only records the first block, which would otherwise block a
    # "yield by product" ranking. (Round 114)
    for marker in _DECOMP_BY_MARKERS:
        i = hay.find(marker)
        if i >= 0:
            tail = hay[i + len(marker):].strip()
            token = re.split(r"[\s,。.，?？]+", tail)[0] if tail else ""
            if token:
                entry = idx.find_dim(token)
                if entry and _is_categorical(entry.column_name):
                    return entry.column_name

    # Pick the LONGEST categorical-on-block keyword match. (Round 114: don't just
    # take best_dim_match's single longest — that can be a non-categorical column
    # like a duration measure, causing the resolver to give up instead of falling
    # back to a real categorical dimension like step_name.)
    best_col, best_len = None, 0
    for kw, entry in idx._dims.items():
        if (kw in hay) and len(kw) > best_len and _is_categorical(entry.column_name):
            best_col, best_len = entry.column_name, len(kw)
    return best_col


def _compose_decomposition_sentence(alias, dim_col, df, total, unit, scope) -> str:
    """Build the ranked-contributor answer sentence for a change decomposition."""
    arrow = "成長" if total >= 0 else "下降"
    head = f"{scope}「{alias}」整體{arrow} {_format_metric_value(abs(total), unit)}，依「{dim_col}」拆解："
    dim_name = df.columns[0]
    # df is sorted by delta ascending (biggest decliners first).
    decliners = df[df["delta"] < 0].head(2)
    risers = df[df["delta"] > 0].sort_values("delta", ascending=False).head(2)
    parts: list[str] = []
    for _, row in decliners.iterrows():
        parts.append(f"{row[dim_name]} ↓{_format_metric_value(abs(row['delta']), unit)}"
                     f"（佔{abs(row['contribution_pct']):.0f}%）")
    for _, row in risers.iterrows():
        parts.append(f"{row[dim_name]} ↑{_format_metric_value(abs(row['delta']), unit)}"
                     f"（佔{abs(row['contribution_pct']):.0f}%）")
    if not parts:
        return head + "各維度變化不顯著。"
    return head + "；".join(parts) + "。"


# --- Round 080: measure-filter (HAVING) parsing -----------------------------

# Comparison phrase → FilterOperator. Longer/more-specific phrases first so
# "至少" wins over "少" and "no less than" isn't read as "less than".
_MEASURE_OP_PHRASES: tuple[tuple[str, str], ...] = (
    ("at least", "gte"), ("no less than", "gte"), ("不少於", "gte"), ("至少", "gte"),
    ("at most", "lte"), ("no more than", "lte"), ("不超過", "lte"), ("不多於", "lte"), ("至多", "lte"),
    ("greater than or equal", "gte"), ("less than or equal", "lte"),
    ("more than", "gt"), ("greater than", "gt"), ("over", "gt"), ("above", "gt"),
    ("超過", "gt"), ("大於", "gt"), ("多於", "gt"), ("高於", "gt"),
    ("less than", "lt"), ("fewer than", "lt"), ("below", "lt"), ("under", "lt"),
    ("低於", "lt"), ("少於", "lt"), ("小於", "lt"), ("不到", "lt"),
    (">=", "gte"), ("<=", "lte"), (">", "gt"), ("<", "lt"),
)


def _looks_like_measure_filter(prompt: str, normalized: str) -> bool:
    """True when the prompt is a post-aggregate threshold on a measure."""
    hay = f"{prompt.lower()} {normalized}"
    if not any(phrase in hay for phrase, _ in _MEASURE_OP_PHRASES):
        return False
    return re.search(r"\d", hay) is not None


def _measure_operator(hay: str):
    from ai4bi.query_spec import FilterOperator
    for phrase, opname in _MEASURE_OP_PHRASES:
        if phrase in hay:
            return getattr(FilterOperator, opname if opname != "in" else "in_")
    return None


def _extract_measure_filter(prompt: str, normalized: str, visual):
    """Resolve (MetricRef, operator, numeric_value) against a visual's metrics.

    Returns None when no operator, number, or projected metric can be found.
    The metric must be one the visual already projects (the executor requires a
    HAVING to reference a projected measure).
    """
    hay = f"{prompt.lower()} {normalized}"
    operator = _measure_operator(hay)
    if operator is None:
        return None

    num_match = re.search(r"(\d[\d,]*\.?\d*)", hay)
    if num_match is None:
        return None
    raw = num_match.group(1).replace(",", "")
    try:
        value: float = float(raw)
        if value.is_integer():
            value = int(value)
    except ValueError:
        return None

    metrics = visual.query.metrics
    if not metrics:
        return None

    # Match the threshold to one of the visual's projected metrics by keyword.
    def _metric_keywords(m) -> list[str]:
        kws = {m.metric_name.lower(), (m.alias or "").lower()}
        for tok in re.split(r"[_\s]+", m.metric_name.lower()):
            if tok:
                kws.add(tok)
                for zh in _METRIC_SYNONYMS.get(tok, []):
                    kws.add(zh)
        return [k for k in kws if k]

    chosen = None
    best_len = 0
    for m in metrics:
        for kw in _metric_keywords(m):
            if kw and kw in hay and len(kw) > best_len:
                chosen = m
                best_len = len(kw)
    if chosen is None:
        # No explicit metric word — default to the sole/first projected metric.
        chosen = metrics[0]

    return chosen, operator, value


# Light ZH/EN synonyms for matching a metric word in a measure-filter prompt.
_METRIC_SYNONYMS: dict[str, list[str]] = {
    "revenue": ["營收", "收入", "業績", "銷售額"],
    "sales": ["銷售", "業績"],
    "orders": ["訂單", "次", "次數", "筆數", "購買"],
    "order": ["訂單", "次"],
    "count": ["次數", "筆數", "數量"],
    "quantity": ["數量", "件數"],
    "amount": ["金額"],
    "profit": ["利潤", "獲利"],
    "margin": ["毛利", "利潤率"],
    "headcount": ["員工", "人數"],
}


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
