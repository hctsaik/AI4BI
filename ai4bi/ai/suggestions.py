"""AI chart suggestions engine — Round 031.

Analyses loaded DataBlockContracts and the semantic model to generate
proactive chart suggestions, similar to Power BI Copilot's "suggested visuals".

No LLM API call is required — suggestions are rule-based from schema metadata,
so they work instantly in mock mode and with user-uploaded data.

Usage
-----
    from ai4bi.ai.suggestions import generate_suggestions
    suggestions = generate_suggestions(contracts, semantic_model)
    # → list[ChartSuggestion], max 6 entries
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ai4bi.blocks.contracts import BlockType, DataBlockContract
from ai4bi.query_spec import VisualType


@dataclass
class ChartSuggestion:
    block_id: str
    metric_name: str
    visual_type: VisualType
    dimension_name: Optional[str]   # "block_id.column_name" or None for KPI
    title: str
    reason: str                     # one-line explanation shown to the user


_DATE_PREFIXES = ("date_", "time_", "dt_", "ts_")
_DATE_SUFFIXES = ("_date", "_time", "_dt", "_ts", "_at", "_on",
                   "_day", "_month", "_year", "_week", "_period")
_DATE_EXACT   = {"date", "time", "timestamp", "ts", "dt"}
_ID_HINTS     = {"_id", "_key", "_code", "_no", "_num"}


def _is_date_col(name: str, data_type: str) -> bool:
    if data_type in ("date", "timestamp"):
        return True
    n = name.lower()
    return (n in _DATE_EXACT
            or any(n.startswith(p) for p in _DATE_PREFIXES)
            or any(n.endswith(s) for s in _DATE_SUFFIXES))


def _is_id_col(name: str) -> bool:
    lower = name.lower()
    return lower == "id" or any(lower.endswith(h) for h in _ID_HINTS)


def generate_suggestions(
    contracts: dict[str, DataBlockContract],
    semantic_model: dict | None = None,
) -> list[ChartSuggestion]:
    """Return up to 6 proactive chart suggestions based on loaded contracts."""
    suggestions: list[ChartSuggestion] = []
    seen_titles: set[str] = set()

    for block_id, contract in contracts.items():
        if contract.block_type not in (
            BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact
        ):
            continue
        if not contract.metrics:
            continue

        metrics = [m.name for m in contract.metrics]
        pk_set = set(contract.primary_keys)

        date_cols = [
            c.name for c in contract.columns
            if _is_date_col(c.name, c.data_type) and c.name not in pk_set
        ]
        cat_cols = [
            c.name for c in contract.columns
            if c.data_type in ("string", "str", "object")
            and not _is_id_col(c.name)
            and c.name not in pk_set
        ]

        def _add(s: ChartSuggestion) -> None:
            if len(suggestions) < 6 and s.title not in seen_titles:
                suggestions.append(s)
                seen_titles.add(s.title)

        # 1. KPI card for first metric
        _add(ChartSuggestion(
            block_id=block_id,
            metric_name=metrics[0],
            visual_type=VisualType.kpi_card,
            dimension_name=None,
            title=f"Total {metrics[0]}",
            reason="KPI 看板：快速掌握整體數字",
        ))

        # 2. Second KPI for second metric
        if len(metrics) >= 2:
            _add(ChartSuggestion(
                block_id=block_id,
                metric_name=metrics[1],
                visual_type=VisualType.kpi_card,
                dimension_name=None,
                title=f"Total {metrics[1]}",
                reason="KPI 看板：第二指標總覽",
            ))

        # 3. Trend over time (line chart)
        if date_cols:
            _add(ChartSuggestion(
                block_id=block_id,
                metric_name=metrics[0],
                visual_type=VisualType.line_chart,
                dimension_name=f"{block_id}.{date_cols[0]}",
                title=f"{metrics[0]} 趨勢",
                reason=f"時間趨勢：{metrics[0]} 隨時間的變化",
            ))

        # 4. Bar chart by first categorical dimension
        if cat_cols:
            _add(ChartSuggestion(
                block_id=block_id,
                metric_name=metrics[0],
                visual_type=VisualType.bar_chart,
                dimension_name=f"{block_id}.{cat_cols[0]}",
                title=f"{metrics[0]} by {cat_cols[0]}",
                reason=f"分類比較：找出 {cat_cols[0]} 中表現最好/最差的",
            ))

        # 5. Pie chart by second categorical dimension
        if len(cat_cols) >= 2:
            _add(ChartSuggestion(
                block_id=block_id,
                metric_name=metrics[0],
                visual_type=VisualType.pie_chart,
                dimension_name=f"{block_id}.{cat_cols[1]}",
                title=f"{metrics[0]} 佔比 ({cat_cols[1]})",
                reason=f"佔比分析：{cat_cols[1]} 各類別貢獻比例",
            ))

        # 6. Scatter: first vs second metric
        if len(metrics) >= 2 and cat_cols:
            _add(ChartSuggestion(
                block_id=block_id,
                metric_name=metrics[0],
                visual_type=VisualType.scatter,
                dimension_name=f"{block_id}.{cat_cols[0]}",
                title=f"{metrics[0]} vs {metrics[1]}",
                reason=f"相關性：{metrics[0]} 與 {metrics[1]} 的關係",
            ))

    return suggestions
