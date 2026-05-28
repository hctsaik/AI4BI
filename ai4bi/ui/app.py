"""Streamlit report canvas for editable semiconductor report drafts."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import streamlit as st

from ai4bi.analysis.executor import Executor
from ai4bi.blocks.loader import BlockLoader
from ai4bi.blocks.contracts import DataBlockContract
from ai4bi.report.builder import (
    build_add_visual_proposal,
    build_reorder_visual_proposal,
    build_visual_from_selection,
)
from ai4bi.report.catalog import build_catalog
from ai4bi.report.models import (
    DraftReportStore,
    ExecutableReportSpec,
    PublishedReportStore,
    ReportProposal,
)
from ai4bi.blocks.registry import FilesystemBlockRegistry, BlockNotFoundError, NoCertifiedVersionError
from ai4bi.report.proposals import controls_to_proposal, pin_block_version_proposal, prompt_to_proposal, unpin_block_version_proposal
from ai4bi.report.publication import GateCheckResult, run_publication_gate
from ai4bi.report.templates import build_semiconductor_queue_time_report
from ai4bi.query_spec import VisualType
from ai4bi.ui.cache import QueryCache
from ai4bi.ui.render_visual import render_visual
from ai4bi.ui import workspace
from ai4bi.ui.viewer import get_draft_path_from_params, is_readonly_mode, render_readonly_banner

_DEMO_ROOT = Path(__file__).parents[2] / "data" / "semiconductor_demo"
_BLOCKS_DIR = _DEMO_ROOT / "blocks"
_SEMANTIC_MODEL = _DEMO_ROOT / "semantic_model.json"
_DRAFT_STORE = _DEMO_ROOT / "draft_reports"
_REGISTRY_DIR = _DEMO_ROOT / "registry"
_PROJECT_ROOT = Path(__file__).parent.parent.parent


def _load_all_contracts() -> dict[str, DataBlockContract]:
    """Load all block contracts from the demo blocks directory."""
    loader = BlockLoader()
    contracts: dict[str, DataBlockContract] = {}
    if _BLOCKS_DIR.exists():
        for path in _BLOCKS_DIR.glob("*.json"):
            try:
                contract = loader.load_json(str(path))
                contracts[contract.block_id] = contract
            except Exception:  # noqa: BLE001
                pass
    return contracts


def _gate_check_icon(check: GateCheckResult) -> str:
    if check.passed:
        return "✅"
    if check.blocking:
        return "❌"
    return "⚠️"


def _render_pin_versions_panel(report: ExecutableReportSpec) -> None:
    """Render the 'Pin versions' expander in the sidebar."""
    with st.expander("Pin versions", expanded=False):
        if report.read_only:
            st.warning("Read-only mode — pinning is disabled.")
            return
        registry = FilesystemBlockRegistry(_REGISTRY_DIR)
        page = report.pages.get("main")
        if page is None:
            st.info("No 'main' page found in report.")
            return
        for visual_id in page.visual_order:
            visual = page.visuals[visual_id]
            for block_ref in visual.query.block_refs:
                block_id = block_ref.block_id
                if block_ref.pinned_version is None:
                    btn_key = f"pin_{visual_id}_{block_id}"
                    if st.button(f"Pin {block_id}", key=btn_key):
                        try:
                            certified_version = registry.get_certified_latest(block_id)
                        except (BlockNotFoundError, NoCertifiedVersionError):
                            st.warning(f"{block_id}: no certified version found")
                            continue
                        current_report = workspace.current_report()
                        proposal = pin_block_version_proposal(
                            current_report, "main", visual_id, block_id, certified_version
                        )
                        workspace.stage_proposal(proposal)
                        st.rerun()
                else:
                    st.markdown(
                        f"`{block_id}` pinned @ `{block_ref.pinned_version}`"
                    )
                    unpin_key = f"unpin_{visual_id}_{block_id}"
                    if st.button("Unpin", key=unpin_key):
                        current_report = workspace.current_report()
                        proposal = unpin_block_version_proposal(
                            current_report, "main", visual_id, block_id
                        )
                        workspace.stage_proposal(proposal)
                        st.rerun()


def _render_publication_readiness(report: ExecutableReportSpec) -> None:
    """Render the Publication Readiness expander in the sidebar."""
    with st.expander("Publication Readiness", expanded=False):
        contracts = _load_all_contracts()
        semantic_model = json.loads(_SEMANTIC_MODEL.read_text(encoding="utf-8"))
        gate = run_publication_gate(report, contracts, semantic_model)

        if gate.can_publish:
            st.success("All blocking checks passed — report may be published.")
        else:
            st.error("One or more blocking checks failed — not ready to publish.")

        for check in gate.checks:
            icon = _gate_check_icon(check)
            label = check.check_name.replace("_", " ").title()
            st.markdown(f"{icon} **{label}**")
            st.caption(check.message)

        if gate.can_publish:
            if st.button("Publish & Share", type="primary", key="publish_share_btn"):
                # Re-run gate fail-closed before writing
                final_gate = run_publication_gate(report, contracts, semantic_model)
                pub_store = PublishedReportStore(_PROJECT_ROOT / "published")
                _, share_url = pub_store.publish(report, final_gate)
                st.success(f"Published! Share URL: {share_url}")
                st.session_state["last_share_url"] = share_url
        else:
            st.button(
                "Publish & Share",
                disabled=True,
                key="publish_share_btn",
                help="Fix failing checks before publishing",
            )


# ---------------------------------------------------------------------------
# Add Visual panel
# ---------------------------------------------------------------------------

_VISUAL_TYPE_OPTIONS: list[str] = ["kpi_card", "line_chart", "bar_chart", "table"]
_VISUAL_TYPE_LABELS: dict[str, str] = {
    "kpi_card": "KPI Card",
    "line_chart": "Line Chart",
    "bar_chart": "Bar Chart",
    "table": "Table",
}


def _render_add_visual_panel(
    report: ExecutableReportSpec,
    cache: QueryCache,
) -> None:
    """Render the '+ Add Visual' expander in the sidebar.

    Steps
    -----
    1. Select block (primary fact block from semantic model).
    2. Select metrics (multiselect, max 2).
    3. Select dimensions (multiselect, max 2, optional).
    4. Select visual type.
    5. Preview VisualQuerySpec as JSON.
    6. 'Add to Report' → adds visual to current page and increments revision.
    """
    with st.expander("＋ Add Visual", expanded=False):
        if report.read_only:
            st.warning("Read-only mode — adding visuals is disabled.")
            return

        # Load contracts and semantic model once (cached by Streamlit widget state
        # — reloaded on each rerun, acceptable for a demo draft tool).
        contracts = _load_all_contracts()
        try:
            semantic_model = json.loads(_SEMANTIC_MODEL.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not load semantic model: {exc}")
            return

        catalog = build_catalog(semantic_model, contracts)
        if not catalog:
            st.info("No fact blocks with metrics are available in the loaded contracts.")
            return

        # --- Step 1: Select block ---
        block_display_names = {bc.block_id: bc.display_name for bc in catalog}
        selected_block_id = st.selectbox(
            "1. Select block",
            list(block_display_names.keys()),
            format_func=lambda bid: block_display_names[bid],
            key="add_visual_block",
        )
        block_catalog = next((bc for bc in catalog if bc.block_id == selected_block_id), None)
        if block_catalog is None:
            return

        # --- Step 2: Select metrics (max 2) ---
        metric_options = [m.metric_name for m in block_catalog.metrics]
        metric_labels = {
            m.metric_name: f"{m.display_name} [{m.aggregation}]"
            for m in block_catalog.metrics
        }
        selected_metrics = st.multiselect(
            "2. Select metric(s) — max 2",
            metric_options,
            format_func=lambda mn: metric_labels.get(mn, mn),
            max_selections=2,
            key="add_visual_metrics",
        )

        # --- Step 3: Select dimensions (max 2, optional) ---
        # Build dimension option keys as "block_id.column_name"
        dim_options: list[str] = []
        dim_labels: dict[str, str] = {}
        for de in block_catalog.dimensions:
            key = f"{de.block_id}.{de.column_name}"
            dim_options.append(key)
            dim_labels[key] = de.display_name

        selected_dims = st.multiselect(
            "3. Select dimension(s) — max 2, optional",
            dim_options,
            format_func=lambda dk: dim_labels.get(dk, dk),
            max_selections=2,
            key="add_visual_dims",
        )

        # --- Step 4: Select visual type ---
        selected_vtype_str = st.selectbox(
            "4. Select visual type",
            _VISUAL_TYPE_OPTIONS,
            format_func=lambda vt: _VISUAL_TYPE_LABELS.get(vt, vt),
            key="add_visual_type",
        )
        visual_type = VisualType(selected_vtype_str)

        # --- Validate & show Step 5: preview ---
        validation_error: str | None = None
        query_spec = None
        viz_spec = None

        if selected_metrics:
            try:
                # Generate a candidate visual_id (not yet in the report).
                existing_ids = set(report.pages["main"].visuals.keys())
                base_id = f"user_{selected_block_id}_{selected_vtype_str}"
                visual_id = base_id
                counter = 1
                while visual_id in existing_ids:
                    visual_id = f"{base_id}_{counter}"
                    counter += 1

                query_spec, viz_spec = build_visual_from_selection(
                    visual_id=visual_id,
                    block_id=selected_block_id,
                    metric_names=selected_metrics,
                    dimension_names=selected_dims,
                    visual_type=visual_type,
                    contracts=contracts,
                    semantic_model=semantic_model,
                )
            except ValueError as exc:
                validation_error = str(exc)

        if validation_error:
            st.warning(f"Cannot add visual: {validation_error}")

        if query_spec is not None:
            with st.expander("5. Preview VisualQuerySpec (JSON)", expanded=False):
                from ai4bi.report.models import query_to_dict
                st.json(query_to_dict(query_spec))

        # --- Step 6: Add to Report button ---
        add_disabled = (
            not selected_metrics
            or validation_error is not None
            or query_spec is None
        )
        if st.button(
            "Add to Report",
            type="primary",
            disabled=add_disabled,
            key="add_visual_submit",
        ):
            if query_spec is not None and viz_spec is not None:
                # Carry matching active filters into the new visual's query spec.
                current_report = workspace.current_report()
                active = current_report.active_filters()
                from ai4bi.query_spec import FilterSpec, FilterOperator
                inherited_filters = []
                for filter_key, filter_value in active.items():
                    key_block_id = filter_key.split(".")[0] if "." in filter_key else ""
                    if key_block_id == selected_block_id:
                        col_name = filter_key.split(".", 1)[1] if "." in filter_key else filter_key
                        inherited_filters.append(
                            FilterSpec(
                                block_id=key_block_id,
                                column_name=col_name,
                                operator=FilterOperator.in_,
                                value=filter_value if isinstance(filter_value, list) else [filter_value],
                                inherit_global_filter=True,
                            )
                        )
                if inherited_filters:
                    from dataclasses import replace as _replace
                    query_spec = _replace(query_spec, filters=inherited_filters)

                proposal = build_add_visual_proposal(
                    page_id="main",
                    visual_id=visual_id,
                    query_spec=query_spec,
                    viz_spec=viz_spec,
                )
                workspace.stage_proposal(proposal)
                workspace.set_message(
                    f"Visual '{viz_spec.title or visual_id}' staged — confirm in the proposal panel."
                )
                st.rerun()


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

        st.markdown("---")
        _render_add_visual_panel(report, cache)

        st.markdown("---")
        _render_pin_versions_panel(report)

        st.markdown("---")
        _render_publication_readiness(report)

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


def _render_reorder_buttons(
    report: ExecutableReportSpec,
    page_id: str,
    visual_id: str,
    idx: int,
    order_len: int,
) -> None:
    """Render inline up/down arrow buttons for reordering a visual."""
    if report.read_only:
        return
    btn_cols = st.columns([1, 1, 10])
    with btn_cols[0]:
        if st.button(
            "↑",
            key=f"reorder_up_{visual_id}",
            disabled=(idx == 0),
            help="Move visual up",
        ):
            current_order = list(report.pages[page_id].visual_order)
            proposal = build_reorder_visual_proposal(
                page_id=page_id,
                visual_id=visual_id,
                direction="up",
                current_order=current_order,
            )
            workspace.stage_proposal(proposal)
            workspace.set_message(f"Staged: move '{visual_id}' up.")
            st.rerun()
    with btn_cols[1]:
        if st.button(
            "↓",
            key=f"reorder_down_{visual_id}",
            disabled=(idx == order_len - 1),
            help="Move visual down",
        ):
            current_order = list(report.pages[page_id].visual_order)
            proposal = build_reorder_visual_proposal(
                page_id=page_id,
                visual_id=visual_id,
                direction="down",
                current_order=current_order,
            )
            workspace.stage_proposal(proposal)
            workspace.set_message(f"Staged: move '{visual_id}' down.")
            st.rerun()


def _render_canvas(
    report: ExecutableReportSpec,
    cache: QueryCache,
    executor: Executor,
    active_filters: dict[str, object],
) -> None:
    page = report.pages["main"]
    visuals = page.visuals

    def render(component_id: str, idx: int, order_len: int) -> None:
        visual = visuals[component_id]
        title = visual.visualization.title or component_id
        header_cols = st.columns([8, 1, 1])
        with header_cols[0]:
            st.markdown(f"**{title}**")
        if not report.read_only:
            with header_cols[1]:
                if st.button(
                    "↑",
                    key=f"reorder_up_{component_id}",
                    disabled=(idx == 0),
                    help="Move visual up",
                ):
                    current_order = list(report.pages["main"].visual_order)
                    proposal = build_reorder_visual_proposal(
                        page_id="main",
                        visual_id=component_id,
                        direction="up",
                        current_order=current_order,
                    )
                    workspace.stage_proposal(proposal)
                    workspace.set_message(f"Staged: move '{component_id}' up.")
                    st.rerun()
            with header_cols[2]:
                if st.button(
                    "↓",
                    key=f"reorder_down_{component_id}",
                    disabled=(idx == order_len - 1),
                    help="Move visual down",
                ):
                    current_order = list(report.pages["main"].visual_order)
                    proposal = build_reorder_visual_proposal(
                        page_id="main",
                        visual_id=component_id,
                        direction="down",
                        current_order=current_order,
                    )
                    workspace.stage_proposal(proposal)
                    workspace.set_message(f"Staged: move '{component_id}' down.")
                    st.rerun()
        query = replace(visual.query, data_version=f"draft-r{report.revision}")
        render_visual(query, visual.visualization, cache, executor, active_filters)

    # Render visuals in visual_order, pairing adjacent kpi_cards into two columns.
    order = page.visual_order
    i = 0
    while i < len(order):
        vid = order[i]
        visual = visuals[vid]
        from ai4bi.query_spec import VisualType as _VT
        if visual.visualization.visual_type == _VT.kpi_card and i + 1 < len(order):
            next_vid = order[i + 1]
            next_visual = visuals[next_vid]
            if next_visual.visualization.visual_type == _VT.kpi_card:
                cols = st.columns(2)
                with cols[0]:
                    render(vid, i, len(order))
                with cols[1]:
                    render(next_vid, i + 1, len(order))
                i += 2
                continue
        render(vid, i, len(order))
        i += 1


def main() -> None:
    st.set_page_config(page_title="AI for BI - Fab Explorer", page_icon="BI", layout="wide")

    # Determine read-only mode from URL query parameters (?mode=readonly&draft=<path>)
    readonly = is_readonly_mode()
    draft_path_param = get_draft_path_from_params()

    workspace.init_report(build_semiconductor_queue_time_report())

    # If a draft path is provided via URL, load it once per session
    if draft_path_param and "readonly_draft_loaded" not in st.session_state:
        _store = DraftReportStore(_DRAFT_STORE)
        try:
            loaded = _store.load(Path(draft_path_param))
            workspace.replace_with_loaded(loaded)
            st.session_state["readonly_draft_loaded"] = True
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    report = workspace.current_report()

    # Enforce read_only flag when URL mode=readonly
    if readonly and not report.read_only:
        report = replace(report, read_only=True)
        workspace.replace_with_loaded(report)
        report = workspace.current_report()

    force_sync = st.session_state.pop("_sync_widgets_from_report", False)
    _sync_widget_values(report, force=force_sync)
    cache = QueryCache(use_l1=False)
    store = DraftReportStore(_DRAFT_STORE)
    executor = Executor(registry_root=_BLOCKS_DIR, semantic_model_path=_SEMANTIC_MODEL)

    active_filters = _render_draft_controls(report, cache, store)
    report = workspace.current_report()

    st.title(report.title)

    # Show read-only banner or normal caption
    if readonly:
        render_readonly_banner()
    else:
        st.caption(
            "Editable validated demo draft: process movement facts use a certified direct "
            "relationship path to tool dimensions."
        )

    if workspace.message():
        st.info(workspace.message())

    _trusted_markdown = (
        "- Demo status: data blocks are validated fixtures, not a published certified report.\n"
        "- Relationship path: `process_move_fact -> tool_dim`, certified direct `many_to_one` left join.\n"
        "- Metric rule: `queue_time_hr` uses approved `AVG`; `move_count` uses approved `SUM`.\n"
        "- Deliberately unavailable: fact-to-fact yield comparison, weighted-yield KPI and formal sharing."
    )

    if readonly:
        # Read-only layout: full-width canvas, Visual Assistant panel hidden
        _render_canvas(report, cache, executor, active_filters)
        with st.expander("Why this result is trusted"):
            st.markdown(_trusted_markdown)
    else:
        canvas, assistant = st.columns([3, 2])
        with assistant:
            _render_visual_assistant(report, cache)
        with canvas:
            _render_canvas(report, cache, executor, active_filters)
            with st.expander("Why this result is trusted"):
                st.markdown(_trusted_markdown)


if __name__ == "__main__":
    main()
