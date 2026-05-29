"""Time-intelligence helpers — Round 047.

Period-over-period comparison (WoW / MoM / YoY) for KPI cards.

Design
------
We use *trailing-window* comparison anchored on the latest date present in the
data, not the calendar boundary:

    period="week"    last 7 days   vs the 7 days before that
    period="month"   last 30 days  vs the 30 days before that
    period="quarter" last 90 days  vs the 90 days before that
    period="year"    last 365 days vs the 365 days before that (YoY)

Trailing windows avoid the "partial current month looks worse than full prior
month" trap that calendar-boundary comparison falls into, and they degrade
gracefully when there is no prior-period data (delta is simply omitted).

The executor has no window-function support, so we compute the two periods as
two ordinary aggregate queries with date filters and diff them in Python. This
keeps the governed single-fact execution path intact.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd

from ai4bi.query_spec import (
    DimensionRef,
    FilterOperator,
    FilterSpec,
    VisualQuerySpec,
)

_PERIOD_DAYS = {"week": 7, "month": 30, "quarter": 90, "year": 365}

_PERIOD_LABELS = {
    "week": ("最近 7 天", "前 7 天"),
    "month": ("最近 30 天", "前 30 天"),
    "quarter": ("最近 90 天", "前 90 天"),
    "year": ("最近 12 個月", "去年同期"),
}


@dataclass
class PeriodComparison:
    """Result of a period-over-period comparison for a single metric."""
    current: Optional[float]
    previous: Optional[float]
    delta_pct: Optional[float]
    current_label: str
    previous_label: str

    @property
    def has_delta(self) -> bool:
        return self.delta_pct is not None


def _coerce_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return pd.to_datetime(value).date()
    except (ValueError, TypeError):
        return None


def latest_date(
    executor,
    base_spec: VisualQuerySpec,
    date_block_id: str,
    date_column: str,
) -> Optional[date]:
    """Return the maximum value of ``date_column`` honouring base_spec filters."""
    probe = replace(
        base_spec,
        spec_id=f"{base_spec.spec_id}__anchor",
        metrics=[],
        dimensions=[DimensionRef(date_block_id, date_column, "__anchor_date")],
        sort=[],
        limit=None,
    )
    try:
        df = executor.run(probe)
    except Exception:  # noqa: BLE001 — anchor is best-effort
        return None
    if df is None or df.empty or "__anchor_date" not in df.columns:
        return None
    series = pd.to_datetime(df["__anchor_date"], errors="coerce").dropna()
    if series.empty:
        return None
    return series.max().date()


def _window_filters(
    block_id: str,
    column: str,
    start: date,
    end: date,
) -> list[FilterSpec]:
    return [
        FilterSpec(block_id, column, FilterOperator.gte, start.isoformat(),
                   inherit_global_filter=False),
        FilterSpec(block_id, column, FilterOperator.lte, end.isoformat(),
                   inherit_global_filter=False),
    ]


def _period_spec(
    base_spec: VisualQuerySpec,
    block_id: str,
    column: str,
    start: date,
    end: date,
    suffix: str,
) -> VisualQuerySpec:
    """Clone base_spec restricted to [start, end] on the date column."""
    kept = [
        f for f in base_spec.filters
        if not (f.block_id == block_id and f.column_name == column)
    ]
    window = _window_filters(block_id, column, start, end)
    return replace(
        base_spec,
        spec_id=f"{base_spec.spec_id}__{suffix}",
        filters=kept + window,
        data_version=f"{base_spec.data_version}:{suffix}:{start}:{end}",
    )


def _scalar(df: Optional[pd.DataFrame], col: str) -> Optional[float]:
    if df is None or df.empty:
        return None
    if col not in df.columns and len(df.columns) == 1:
        col = df.columns[0]
    if col not in df.columns:
        return None
    val = df[col].iloc[0]
    return None if pd.isna(val) else float(val)


def compute_period_comparison(
    executor,
    base_spec: VisualQuerySpec,
    *,
    date_block_id: str,
    date_column: str,
    period: str,
    metric_col: str,
    anchor: Optional[date] = None,
) -> Optional[PeriodComparison]:
    """Compute current vs previous trailing-window values for a single metric.

    Returns None if the period is unknown or no anchor date can be resolved
    (e.g. the data has no usable date column) — callers then fall back to a
    plain KPI.
    """
    days = _PERIOD_DAYS.get(period)
    if days is None:
        return None
    if anchor is None:
        anchor = latest_date(executor, base_spec, date_block_id, date_column)
    if anchor is None:
        return None

    cur_start = anchor - timedelta(days=days - 1)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)

    cur_spec = _period_spec(base_spec, date_block_id, date_column, cur_start, anchor, "cur")
    prev_spec = _period_spec(base_spec, date_block_id, date_column, prev_start, prev_end, "prev")

    try:
        cur_df = executor.run(cur_spec)
        prev_df = executor.run(prev_spec)
    except Exception:  # noqa: BLE001
        return None

    current = _scalar(cur_df, metric_col)
    previous = _scalar(prev_df, metric_col)

    delta_pct: Optional[float] = None
    if current is not None and previous not in (None, 0):
        delta_pct = (current - previous) / abs(previous) * 100.0

    cur_label, prev_label = _PERIOD_LABELS.get(period, (period, f"prev {period}"))
    return PeriodComparison(
        current=current,
        previous=previous,
        delta_pct=delta_pct,
        current_label=cur_label,
        previous_label=prev_label,
    )
