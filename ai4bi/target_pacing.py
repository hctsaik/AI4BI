"""Shared KPI target-progress semantics for API, AI answers, and legacy UI."""

from __future__ import annotations

from typing import Optional

import pandas as pd


def _pacing_status(value: float, target: float, good_if: str = "gte") -> Optional[tuple[float, str, bool]]:
    """Return progress fraction, caption, and target status for a usable value.

    For ``good_if="gte"`` progress is value/target. For ``good_if="lte"``
    progress is target/value so a smaller actual reads as ahead of goal.
    """
    if target is None or target == 0 or value is None or pd.isna(value):
        return None
    if good_if == "lte":
        frac = target / value if value else 2.0
        on_track = value <= target
        pct = (value / target) * 100.0
        cap = (f"✅ 達標：{pct:.0f}% of 目標（越低越好，目標 ≤ {target:,.0f}）"
               if on_track else
               f"⚠️ 超出目標 {pct - 100:.0f}%（目標 ≤ {target:,.0f}）")
    else:
        frac = value / target
        on_track = value >= target
        pct = frac * 100.0
        if on_track:
            cap = f"✅ 已達標：{pct:.0f}% of 目標 {target:,.0f}"
        else:
            cap = f"進度 {pct:.0f}%（目標 {target:,.0f}，還差 {target - value:,.0f}）"
    return max(0.0, min(frac, 1.0)), cap, on_track
