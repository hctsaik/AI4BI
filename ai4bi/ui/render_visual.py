"""
ai4bi.ui.render_visual — Top-level visual dispatch with error handling.

This module is the single entry point that render_report() / app.py calls
for each visual on the dashboard.  It handles:

  1. Cache look-up (via QueryCache)
  2. Query execution with fallback (last_valid_result)
  3. Component dispatch based on VisualizationSpec.visual_type
  4. Structured error card (Retry / Undo / Reset) on query failure
  5. Empty result vs query failure distinction

Component dispatch table
------------------------
VisualType.kpi_card   → render_kpi_card
VisualType.line_chart → render_line_chart
VisualType.bar_chart  → render_bar_chart
VisualType.table      → render_data_table
(scatter, pivot, map — placeholder stubs, planned P4+)

Error card anatomy
-------------------
┌──────────────────────────────────────────────┐
│  ⚠ Query failed: <error summary>            │
│  Block: sales_fact | Spec: kpi_total_revenue │
│  [Retry]  [Undo]  [Reset]                    │
└──────────────────────────────────────────────┘

- Retry   → clears cache entry, re-executes immediately.
- Undo    → restores the last_valid_result without re-querying.
- Reset   → clears cache entry AND last_valid_result (shows empty state).
"""

from __future__ import annotations

import logging
import traceback
from typing import TYPE_CHECKING, Any, Callable, Optional

import pandas as pd
import streamlit as st

from ai4bi.query_spec import VisualType, VisualQuerySpec, VisualizationSpec
from ai4bi.ui.cache import QueryCache
from ai4bi.ui.components.bar_chart import render_bar_chart
from ai4bi.ui.components.data_table import render_data_table
from ai4bi.ui.components.kpi_card import render_kpi_card
from ai4bi.ui.components.line_chart import render_line_chart

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Session-state namespace for last-valid results
_LAST_VALID_KEY = "visual_last_valid"


# ---------------------------------------------------------------------------
# Executor protocol (structural typing — no ABC import needed)
# ---------------------------------------------------------------------------

class ExecutorProtocol:  # pragma: no cover
    """
    Structural interface expected of ``executor`` objects.
    Any object with a ``run(spec, active_filters) -> pd.DataFrame`` method qualifies.
    """
    def run(
        self,
        spec: VisualQuerySpec,
        active_filters: Optional[dict[str, Any]] = None,
    ) -> pd.DataFrame: ...


# ---------------------------------------------------------------------------
# Fallback execution
# ---------------------------------------------------------------------------

def _last_valid_store() -> dict[str, pd.DataFrame]:
    """Lazy-init the last-valid result store in session_state."""
    if _LAST_VALID_KEY not in st.session_state:
        st.session_state[_LAST_VALID_KEY] = {}
    return st.session_state[_LAST_VALID_KEY]


def execute_with_fallback(
    query_spec: VisualQuerySpec,
    executor: ExecutorProtocol,
    cache: QueryCache,
    active_filters: Optional[dict[str, Any]] = None,
) -> tuple[pd.DataFrame, Optional[Exception]]:
    """
    Execute a query and return (DataFrame, error).

    On success:
    - Stores the result in cache.
    - Saves a copy as ``last_valid_result`` keyed by spec_id.
    - Returns (df, None).

    On failure:
    - Does NOT update the cache.
    - Returns (last_valid_result_or_empty_df, exception).

    Parameters
    ----------
    query_spec : VisualQuerySpec
    executor   : object with ``run(spec) -> pd.DataFrame``
    cache      : QueryCache instance
    active_filters : dict | None
        Current global filter state; passed through to the executor.

    Returns
    -------
    (pd.DataFrame, Optional[Exception])
        The DataFrame to render and any exception that occurred.
    """
    store = _last_valid_store()

    # Effective global filter values are not encoded in the static spec key.
    # Prefer correctness over reuse for dynamic visuals in this MVP.
    if active_filters is not None and query_spec.inherit_global_filter:
        cache.invalidate(query_spec)

    # Try cache first
    cached = cache.get(query_spec)
    if cached is not None:
        store[query_spec.spec_id] = cached  # keep last-valid in sync
        return cached, None

    # Execute
    try:
        df = executor.run(query_spec, active_filters)
        cache.put(query_spec, df)
        cache.register_key_for_spec(query_spec)
        store[query_spec.spec_id] = df.copy()
        logger.debug(
            "[render_visual] execute_with_fallback spec=%s rows=%d",
            query_spec.spec_id, len(df),
        )
        return df, None

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[render_visual] query failed spec=%s: %s",
            query_spec.spec_id, exc,
            exc_info=True,
        )
        fallback = store.get(query_spec.spec_id, pd.DataFrame())
        return fallback, exc


# ---------------------------------------------------------------------------
# Error card
# ---------------------------------------------------------------------------

def _render_error_card(
    query_spec: VisualQuerySpec,
    exc: Exception,
    cache: QueryCache,
    on_retry: Callable[[], None],
    on_undo: Callable[[], None],
    on_reset: Callable[[], None],
) -> None:
    """
    Render a structured inline error card with Retry / Undo / Reset actions.

    Parameters
    ----------
    query_spec : VisualQuerySpec
    exc        : The exception that caused the failure.
    cache      : QueryCache — used by the Retry handler to clear the entry.
    on_retry   : Called when the user clicks "Retry".
    on_undo    : Called when the user clicks "Undo".
    on_reset   : Called when the user clicks "Reset".
    """
    error_summary = str(exc)[:200]  # truncate very long messages

    with st.container(border=True):
        st.error(
            f"**Query failed** — {error_summary}\n\n"
            f"Block: `{query_spec.primary_block_id}` | "
            f"Spec: `{query_spec.spec_id}`",
            icon="⚠️",
        )

        with st.expander("Stack trace", expanded=False):
            st.code(traceback.format_exc(), language="python")

        btn_cols = st.columns(3)
        with btn_cols[0]:
            if st.button("Retry", key=f"err_retry_{query_spec.spec_id}", type="primary"):
                on_retry()
        with btn_cols[1]:
            has_fallback = bool(_last_valid_store().get(query_spec.spec_id) is not None
                                and not _last_valid_store()[query_spec.spec_id].empty)
            if st.button(
                "Show previous result",
                key=f"err_undo_{query_spec.spec_id}",
                disabled=not has_fallback,
            ):
                on_undo()
        with btn_cols[2]:
            if st.button("Reset", key=f"err_reset_{query_spec.spec_id}"):
                on_reset()


# ---------------------------------------------------------------------------
# Component dispatch
# ---------------------------------------------------------------------------

_COMPONENT_REGISTRY: dict[VisualType, Callable] = {
    VisualType.kpi_card:   render_kpi_card,
    VisualType.line_chart: render_line_chart,
    VisualType.bar_chart:  render_bar_chart,
    VisualType.table:      render_data_table,
}


def _dispatch(
    visual_type: VisualType,
    query_spec: VisualQuerySpec,
    df: pd.DataFrame,
    style: VisualizationSpec,
) -> None:
    """Route to the appropriate component renderer."""
    renderer = _COMPONENT_REGISTRY.get(visual_type)
    if renderer is None:
        st.warning(
            f"[render_visual] Visual type '{visual_type}' is not yet implemented. "
            f"Spec: {query_spec.spec_id}"
        )
        return
    renderer(query_spec, df, style)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def render_visual(
    query_spec: VisualQuerySpec,
    style: VisualizationSpec,
    cache: QueryCache,
    executor: ExecutorProtocol,
    active_filters: Optional[dict[str, Any]] = None,
) -> None:
    """
    Render one visual: cache → execute → dispatch → error handling.

    This is the function called by ``app.py`` / ``analysis/executor.py``
    for each visual in a report layout.

    Parameters
    ----------
    query_spec     : VisualQuerySpec
        Declarative query specification for this visual.
    style          : VisualizationSpec
        Presentation hints (visual_type, title, etc.).
    cache          : QueryCache
        Two-tier cache instance shared across the page render.
    executor       : object with run(spec) -> pd.DataFrame
        Executes the query when there is a cache miss.
    active_filters : dict | None
        Current global filter values from the filter bar.

    Behaviour
    ---------
    - On success with data:  dispatch to component renderer.
    - On success with empty: show "No Results" — distinct from an error.
    - On failure with fallback: show stale data banner + error card.
    - On failure without fallback: show error card only.
    """
    # ------------------------------------------------------------------
    # Execute with fallback
    # ------------------------------------------------------------------
    df, exc = execute_with_fallback(query_spec, executor, cache, active_filters)

    # ------------------------------------------------------------------
    # Error card action callbacks
    # ------------------------------------------------------------------
    def _retry() -> None:
        cache.invalidate(query_spec)
        st.rerun()

    def _undo() -> None:
        # Re-render using the last_valid_result already in df (fallback)
        st.rerun()

    def _reset() -> None:
        cache.invalidate(query_spec)
        store = _last_valid_store()
        store.pop(query_spec.spec_id, None)
        st.rerun()

    # ------------------------------------------------------------------
    # Error state — query failed
    # ------------------------------------------------------------------
    if exc is not None:
        is_stale = not df.empty  # we have a fallback
        if is_stale:
            st.warning(
                f"Showing stale data for **{style.title or query_spec.spec_id}** "
                f"(last successful query). Live query failed.",
                icon="🕐",
            )
            # Render the stale data below the warning
            _dispatch(style.visual_type, query_spec, df, style)

        # Always show the error card (even alongside stale data)
        _render_error_card(query_spec, exc, cache, _retry, _undo, _reset)
        return

    # ------------------------------------------------------------------
    # Empty result — query succeeded but returned no rows
    # ------------------------------------------------------------------
    if df.empty:
        with st.container(border=True):
            title = style.title or query_spec.spec_id
            st.caption(title)
            st.info(
                "No results match the current filters.",
                icon="🔍",
            )
        logger.debug("[render_visual] spec=%s empty result (query succeeded)", query_spec.spec_id)
        return

    # ------------------------------------------------------------------
    # Happy path — dispatch to component
    # ------------------------------------------------------------------
    _dispatch(style.visual_type, query_spec, df, style)
