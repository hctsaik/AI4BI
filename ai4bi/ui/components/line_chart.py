"""
ai4bi.ui.components.line_chart — Line chart visual component using Plotly.

Features
--------
- Multi-series: each MetricRef in query_spec.metrics becomes a separate line.
- Cross-filter: ``on_select="rerun"`` captures point selections and writes
  them into ``st.session_state["cross_filter"]``.  Other visuals that declare
  the same dimension column as a filter will re-render with the selected value.
- Empty / null handling: missing metric columns are skipped with a warning;
  if the DataFrame is fully empty a No-Data placeholder is shown.

Cross-filter protocol
---------------------
When the user clicks a data point:
  st.session_state["cross_filter"] is updated as:
  {
      "source_spec_id": str,          # which chart fired the event
      "column": str,                  # x-axis dimension column name
      "value": Any,                   # selected x-axis value
      "timestamp": float,             # time.time() for de-duplication
  }

Visuals that inherit global filters should observe this dict in their
render_visual wrapper and translate it into an active filter before
calling the executor.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ai4bi.query_spec import DimensionRef, MetricRef, VisualQuerySpec, VisualizationSpec

logger = logging.getLogger(__name__)

_CROSS_FILTER_KEY = "cross_filter"
_PLOTLY_COLORS = [
    "#636EFA", "#EF553B", "#00CC96", "#AB63FA",
    "#FFA15A", "#19D3F3", "#FF6692", "#B6E880",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_x_column(query_spec: VisualQuerySpec, df: pd.DataFrame) -> Optional[str]:
    """
    Determine the x-axis column name.

    Priority:
    1. First DimensionRef that has ``truncate_date_to`` set (time-series intent).
    2. First DimensionRef's column_name.
    3. DataFrame index if it has a name.
    4. None (caller shows error).
    """
    for dim in query_spec.dimensions:
        col = dim.alias or dim.column_name
        if col in df.columns:
            return col
    if df.index.name and df.index.name in df.columns:
        return df.index.name
    return None


def _build_figure(
    df: pd.DataFrame,
    x_col: str,
    metrics: list[MetricRef],
    style: VisualizationSpec,
) -> go.Figure:
    """Construct a Plotly Figure with one trace per metric."""
    fig = go.Figure()

    for idx, metric in enumerate(metrics):
        y_col = metric.alias or metric.metric_name
        if y_col not in df.columns:
            y_col = metric.metric_name
        if y_col not in df.columns:
            logger.warning("[line_chart] metric column '%s' not in DataFrame — skipping", y_col)
            continue

        prompted_color = style.extra.get("line_color") if idx == 0 else None
        color = prompted_color or _PLOTLY_COLORS[idx % len(_PLOTLY_COLORS)]
        fig.add_trace(
            go.Scatter(
                x=df[x_col],
                y=df[y_col],
                mode="lines+markers",
                name=metric.alias or metric.metric_name,
                line=dict(color=color, width=2),
                marker=dict(size=6),
                hovertemplate=f"<b>{y_col}</b>: %{{y:,.0f}}<extra></extra>",
            )
        )

    fig.update_layout(
        title=style.title or "",
        xaxis_title=style.x_axis_label or x_col,
        yaxis_title=style.y_axis_label or "",
        height=style.height_px,
        showlegend=style.show_legend and len(metrics) > 1,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=40, r=20, t=40, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        dragmode="select",  # enables box/lasso selection for cross-filter
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(128,128,128,0.15)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(128,128,128,0.15)")
    return fig


def _handle_selection(
    event: Any,
    spec_id: str,
    x_col: str,
) -> None:
    """
    Translate a Plotly selection event into a cross-filter update.

    ``event`` is the dict returned by ``st.plotly_chart(..., on_select="rerun")``.
    Streamlit populates ``event["selection"]["points"]`` on a click/box-select.
    """
    if not event:
        return
    points = (event.get("selection") or {}).get("points", [])
    if not points:
        return

    # Use the first selected point's x-value
    x_value = points[0].get("x")
    if x_value is None:
        return

    st.session_state[_CROSS_FILTER_KEY] = {
        "source_spec_id": spec_id,
        "column": x_col,
        "value": x_value,
        "timestamp": time.time(),
    }
    logger.debug(
        "[line_chart] cross-filter set: column=%s value=%s source=%s",
        x_col, x_value, spec_id,
    )


# ---------------------------------------------------------------------------
# Public component
# ---------------------------------------------------------------------------

def render_line_chart(
    query_spec: VisualQuerySpec,
    df: pd.DataFrame,
    style: VisualizationSpec,
) -> None:
    """
    Render a multi-series Plotly line chart with cross-filter support.

    Parameters
    ----------
    query_spec : VisualQuerySpec
        Query specification; metrics become series, first dimension is x-axis.
    df : pd.DataFrame
        Result DataFrame from the executor.  Must contain one column per metric
        (named by ``metric.alias or metric.metric_name``) and one column for
        the x-axis dimension.
    style : VisualizationSpec
        Presentation hints: title, axis labels, height, color scheme.

    Cross-filter
    ------------
    Clicking a data point writes to ``st.session_state["cross_filter"]``.
    A subsequent Streamlit rerun causes other visuals to pick up the new filter.
    To clear the cross-filter, set ``st.session_state["cross_filter"] = None``.
    """
    title = style.title or query_spec.spec_id

    # ------------------------------------------------------------------ #
    # Empty state
    # ------------------------------------------------------------------ #
    if df is None or df.empty:
        with st.container(border=True):
            st.caption(title)
            st.info("No Data", icon="📭")
        logger.debug("[line_chart] spec=%s empty DataFrame", query_spec.spec_id)
        return

    if not query_spec.metrics:
        st.warning(f"[{query_spec.spec_id}] No metrics defined — cannot render line chart.")
        return

    # ------------------------------------------------------------------ #
    # Resolve x-axis column
    # ------------------------------------------------------------------ #
    x_col = _resolve_x_column(query_spec, df)
    if x_col is None:
        st.error(
            f"[{query_spec.spec_id}] Cannot determine x-axis column. "
            "Add a DimensionRef to VisualQuerySpec."
        )
        return

    # ------------------------------------------------------------------ #
    # Build and render figure
    # ------------------------------------------------------------------ #
    fig = _build_figure(df, x_col, query_spec.metrics, style)

    event = st.plotly_chart(
        fig,
        width="stretch",
        on_select="rerun",
        key=f"line_chart_{query_spec.spec_id}",
    )

    # ------------------------------------------------------------------ #
    # Cross-filter handling
    # ------------------------------------------------------------------ #
    _handle_selection(event, query_spec.spec_id, x_col)

    # Surface active cross-filter badge
    active_cf = st.session_state.get(_CROSS_FILTER_KEY)
    if active_cf and active_cf.get("source_spec_id") == query_spec.spec_id:
        col1, col2 = st.columns([6, 1])
        with col1:
            st.caption(
                f"Cross-filter active: **{active_cf['column']}** = `{active_cf['value']}`"
            )
        with col2:
            if st.button("Clear", key=f"cf_clear_{query_spec.spec_id}"):
                st.session_state[_CROSS_FILTER_KEY] = None
                st.rerun()

    logger.debug(
        "[line_chart] spec=%s rendered %d series x=%s rows=%d",
        query_spec.spec_id, len(query_spec.metrics), x_col, len(df),
    )
