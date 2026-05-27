"""Streamlit report canvas for editable semiconductor report drafts."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import streamlit as st

from ai4bi.analysis.executor import Executor
from ai4bi.report.models import DraftReportStore, ExecutableReportSpec, ReportProposal
from ai4bi.report.proposals import controls_to_proposal, prompt_to_proposal
from ai4bi.report.templates import build_semiconductor_queue_time_report
from ai4bi.ui.cache import QueryCache
from ai4bi.ui.render_visual import render_visual
from ai4bi.ui import workspace

_DEMO_ROOT = Path(__file__).parents[2] / "data" / "semiconductor_demo"
_BLOCKS_DIR = _DEMO_ROOT / "blocks"
_SEMANTIC_MODEL = _DEMO_ROOT / "semantic_model.json"
_DRAFT_STORE = _DEMO_ROOT / "draft_reports"


def _sync_widget_values(report: ExecutableReportSpec, *, force: bool = False) -> None:
    mappings = {
        "widget_process_step": report.controls["process_step"].value,
        "widget_product_family": report.controls["product_family"].value,
        "widget_breakdown": report.controls["breakdown"].value,
    }
    for key, value in mappings.items():
        if force or key not in st.session_state:
            st.session_state[key] = value


def _request_widget_sync() -> None:
    st.session_state["_sync_widgets_from_report"] = True


def _render_draft_controls(
    report: ExecutableReportSpec,
    cache: QueryCache,
    store: DraftReportStore,
) -> dict[str, object]:
    with st.sidebar:
        st.title("AI for BI")
        st.caption("Validated semiconductor demo draft")
        st.warning("Draft only: relationship path is certified; data blocks are not published.")
        st.markdown("---")
        st.subheader("Slicers")
        steps = st.multiselect(
            report.controls["process_step"].label,
            report.controls["process_step"].options,
            key="widget_process_step",
            disabled=report.read_only,
        )
        products = st.multiselect(
            report.controls["product_family"].label,
            report.controls["product_family"].options,
            key="widget_product_family",
            disabled=report.read_only,
        )
        breakdown = st.selectbox(
            report.controls["breakdown"].label,
            report.controls["breakdown"].options,
            key="widget_breakdown",
            disabled=report.read_only,
        )
        proposal = controls_to_proposal(
            report,
            steps=steps,
            products=products,
            breakdown=breakdown,
        )
        if proposal and not report.read_only:
            if workspace.apply_immediately(proposal):
                cache.invalidate_all()
                st.rerun()

        st.markdown("---")
        st.subheader("Draft Report")
        st.caption(f"Revision {report.revision} | `{report.semantic_model_ref}`")
        button_cols = st.columns(2)
        with button_cols[0]:
            if st.button("Undo", disabled=not workspace.can_undo(), width="stretch"):
                workspace.undo()
                _request_widget_sync()
                cache.invalidate_all()
                st.rerun()
        with button_cols[1]:
            if st.button("Redo", disabled=not workspace.can_redo(), width="stretch"):
                workspace.redo()
                _request_widget_sync()
                cache.invalidate_all()
                st.rerun()
        if st.button("Save Local Draft", width="stretch", disabled=report.read_only):
            path = store.save(report)
            workspace.set_message(f"Saved local draft: {path.name}")
            st.rerun()
        available = store.list_paths()
        if available:
            chosen = st.selectbox("Saved local drafts", available, format_func=lambda path: path.stem)
            if st.button("Load Draft", width="stretch"):
                try:
                    workspace.replace_with_loaded(store.load(chosen))
                    _request_widget_sync()
                    cache.invalidate_all()
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    workspace.set_message(f"Draft load rejected: {exc}")
                st.rerun()
        if st.button("Clear query cache", width="stretch"):
            cache.invalidate_all()
            st.rerun()
    return report.active_filters()


def _proposal_rows(proposal: ReportProposal) -> list[dict[str, str]]:
    return [
        {
            "Change": change.label,
            "Before": str(change.before),
            "After": str(change.after),
            "Data impact": "Re-query after approval" if change.affects_data else "Display only",
        }
        for change in proposal.changes
    ]


def _render_visual_assistant(report: ExecutableReportSpec, cache: QueryCache) -> None:
    with st.container(border=True):
        st.subheader("Visual Assistant")
        st.caption("Prompt changes become a reviewable proposal before they affect the report.")
        display_names = {
            component_id: visual.visualization.title or component_id
            for component_id, visual in report.pages["main"].visuals.items()
        }
        selected = st.selectbox(
            "Selected visual",
            list(display_names),
            format_func=lambda component_id: display_names[component_id],
            key="selected_component_id",
            disabled=report.read_only,
        )
        prompt = st.text_input(
            "Describe a report change",
            placeholder="例如：把趨勢線改成紅色；只看 PHOTO；依供應商比較等待時間",
            disabled=report.read_only,
        )
        if st.button("Create Proposal", type="primary", disabled=report.read_only):
            result = prompt_to_proposal(prompt, report, selected)
            workspace.set_message(result.message)
            if result.proposal is not None:
                workspace.stage_proposal(result.proposal)
            st.rerun()

        pending = workspace.pending_proposal()
        if pending is not None:
            st.markdown("**Pending Proposal**")
            st.dataframe(_proposal_rows(pending), hide_index=True, width="stretch")
            if pending.affects_data:
                st.warning("This change affects filters or grouping. Numbers update only after Apply.")
            else:
                st.success("Presentation-only change: query semantics and numbers stay unchanged.")
            actions = st.columns(2)
            with actions[0]:
                if st.button("Apply Proposal", type="primary", width="stretch"):
                    if workspace.accept_pending():
                        _request_widget_sync()
                        cache.invalidate_all()
                    st.rerun()
            with actions[1]:
                if st.button("Cancel Proposal", width="stretch"):
                    workspace.cancel_pending()
                    st.rerun()


def _render_canvas(
    report: ExecutableReportSpec,
    cache: QueryCache,
    executor: Executor,
    active_filters: dict[str, object],
) -> None:
    visuals = report.pages["main"].visuals

    def render(component_id: str) -> None:
        visual = visuals[component_id]
        query = replace(visual.query, data_version=f"draft-r{report.revision}")
        render_visual(query, visual.visualization, cache, executor, active_filters)

    kpis = st.columns(2)
    with kpis[0]:
        render("kpi_move_count")
    with kpis[1]:
        render("kpi_avg_queue")
    charts = st.columns(2)
    with charts[0]:
        render("line_queue_by_day")
    with charts[1]:
        render("bar_queue_by_tool_dimension")
    render("table_queue_by_tool_dimension")


def main() -> None:
    st.set_page_config(page_title="AI for BI - Fab Explorer", page_icon="BI", layout="wide")
    workspace.init_report(build_semiconductor_queue_time_report())
    report = workspace.current_report()
    force_sync = st.session_state.pop("_sync_widgets_from_report", False)
    _sync_widget_values(report, force=force_sync)
    cache = QueryCache(use_l1=False)
    store = DraftReportStore(_DRAFT_STORE)
    executor = Executor(registry_root=_BLOCKS_DIR, semantic_model_path=_SEMANTIC_MODEL)

    active_filters = _render_draft_controls(report, cache, store)
    report = workspace.current_report()

    st.title(report.title)
    st.caption(
        "Editable validated demo draft: process movement facts use a certified direct "
        "relationship path to tool dimensions."
    )
    if workspace.message():
        st.info(workspace.message())

    canvas, assistant = st.columns([3, 2])
    with assistant:
        _render_visual_assistant(report, cache)
    with canvas:
        _render_canvas(report, cache, executor, active_filters)
        with st.expander("Why this result is trusted"):
            st.markdown(
                "- Demo status: data blocks are validated fixtures, not a published certified report.\n"
                "- Relationship path: `process_move_fact -> tool_dim`, certified direct `many_to_one` left join.\n"
                "- Metric rule: `queue_time_hr` uses approved `AVG`; `move_count` uses approved `SUM`.\n"
                "- Deliberately unavailable: fact-to-fact yield comparison, weighted-yield KPI and formal sharing."
            )


if __name__ == "__main__":
    main()
