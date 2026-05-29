"""Result post-processing — Round 054.

The executor emits a single GROUP BY (no window functions), so cumulative /
running-total / Pareto analytics are computed here, on the already-aggregated
result DataFrame, in the render layer. Pure pandas, no executor changes.

Driven by VisualizationSpec.extra:
    extra["postprocess"]        = "running_total" | "pareto" | "moving_avg"
    extra["postprocess_column"] = metric alias (defaults to the first metric)
    extra["postprocess_window"] = int (moving_avg window, default 3)
"""

from __future__ import annotations

from typing import Optional

import pandas as pd


def _value_col(df: pd.DataFrame, query_spec, style) -> Optional[str]:
    col = style.extra.get("postprocess_column")
    if col and col in df.columns:
        return col
    if query_spec.metrics:
        alias = query_spec.metrics[0].alias or query_spec.metrics[0].metric_name
        if alias in df.columns:
            return alias
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    return numeric[-1] if numeric else None


def add_running_total(df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    out = df.copy()
    out[f"{value_col}（累計）"] = out[value_col].cumsum()
    return out


def add_moving_average(df: pd.DataFrame, value_col: str, window: int = 3) -> pd.DataFrame:
    out = df.copy()
    out[f"{value_col}（{window}期移動平均）"] = (
        out[value_col].rolling(window=window, min_periods=1).mean().round(2)
    )
    return out


def add_pareto(df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """Sort by value desc and add cumulative-% + ABC class (80/95 cutoffs)."""
    out = df.sort_values(value_col, ascending=False).reset_index(drop=True)
    total = out[value_col].sum()
    if total:
        out["累計占比(%)"] = (out[value_col].cumsum() / total * 100).round(1)
    else:
        out["累計占比(%)"] = 0.0

    def _cls(p: float) -> str:
        if p <= 80:
            return "A"
        if p <= 95:
            return "B"
        return "C"

    out["ABC"] = out["累計占比(%)"].apply(_cls)
    return out


def apply_postprocess(df: pd.DataFrame, query_spec, style) -> pd.DataFrame:
    """Apply the configured post-processing to a result DataFrame (no-op if none)."""
    mode = (style.extra or {}).get("postprocess")
    if not mode or df is None or df.empty:
        return df
    value_col = _value_col(df, query_spec, style)
    if value_col is None:
        return df
    try:
        if mode == "running_total":
            return add_running_total(df, value_col)
        if mode == "moving_avg":
            window = int(style.extra.get("postprocess_window", 3))
            return add_moving_average(df, value_col, window)
        if mode == "pareto":
            return add_pareto(df, value_col)
    except Exception:  # noqa: BLE001 — never break a chart over post-processing
        return df
    return df
