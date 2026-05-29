"""AI chart suggestions engine — Round 031 / Round 034.

Round 034 adds detect_anomalies(): runs simple statistical checks against
InlineDataSource records to surface proactive "aha moment" observations
without any LLM API call. Used on data upload to give users 3 observations
before they ask their first question.

Usage
-----
    from ai4bi.ai.suggestions import generate_suggestions, detect_anomalies
    suggestions = generate_suggestions(contracts, semantic_model)
    anomalies  = detect_anomalies(contracts)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ai4bi.blocks.contracts import BlockType, DataBlockContract
from ai4bi.query_spec import VisualType


@dataclass
class AnomalyObservation:
    """A single AI-generated data observation for the proactive insight panel."""
    icon: str        # emoji icon
    headline: str    # one-line headline (e.g. "台中店退貨率異常偏高")
    detail: str      # supporting detail (e.g. "0.11 vs 平均 0.06，高出 83%")
    metric: str      # metric column name
    severity: str    # "high" | "medium" | "info"


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


def detect_anomalies(
    contracts: dict[str, DataBlockContract],
    max_observations: int = 3,
) -> list[AnomalyObservation]:
    """Run statistical anomaly detection against InlineDataSource blocks.

    Round 034: gives users proactive "aha moment" observations immediately
    after uploading data — no LLM call, pure pandas statistics.

    Checks performed:
    1. Top-dimension value that deviates most from average (z-score > 1.5)
    2. Metric with highest coefficient of variation (most volatile)
    3. Ratio metric that has suspiciously high average (possible data error)
    """
    try:
        import pandas as pd
        import math
    except ImportError:
        return []

    observations: list[AnomalyObservation] = []

    for block_id, contract in contracts.items():
        if contract.block_type not in (
            BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact
        ):
            continue
        from ai4bi.blocks.contracts import CachedDataSource, InlineDataSource
        if not isinstance(contract.data_source, (InlineDataSource, CachedDataSource)):
            continue
        from ai4bi.blocks.datastore import materialize_dataframe
        try:
            df = materialize_dataframe(contract)
        except (KeyError, TypeError):
            continue
        if df is None or len(df) < 5:
            continue

        # Find sum-metrics and ratio-metrics from contract
        sum_metrics = [
            m.name for m in contract.metrics
            if m.disaggregation_method.value in ("sum", "count")
            and m.name in df.columns
            and pd.api.types.is_numeric_dtype(df[m.name])
        ]
        ratio_metrics = [
            m.name for m in contract.metrics
            if m.disaggregation_method.value == "average"
            and m.name in df.columns
            and pd.api.types.is_numeric_dtype(df[m.name])
        ]
        cat_cols = [
            c.name for c in contract.columns
            if c.data_type in ("string", "str", "object")
            and not _is_id_col(c.name)
            and c.name in df.columns
            and df[c.name].nunique() <= 20
        ]

        # ── Check 1: Category outlier (sum metric grouped by first cat dim) ──
        if sum_metrics and cat_cols:
            metric = sum_metrics[0]
            dim = cat_cols[0]
            try:
                grouped = df.groupby(dim)[metric].sum()
                if len(grouped) >= 3:
                    mean = grouped.mean()
                    std = grouped.std()
                    if std > 0:
                        z_scores = (grouped - mean) / std
                        worst = z_scores.abs().idxmax()
                        z = z_scores[worst]
                        if abs(z) > 1.5:
                            direction = "偏高" if z > 0 else "偏低"
                            pct = abs(grouped[worst] / mean - 1) * 100
                            observations.append(AnomalyObservation(
                                icon="📊",
                                headline=f"「{worst}」的 {metric} 顯著{direction}",
                                detail=f"{grouped[worst]:,.0f}，比平均 {mean:,.0f} {direction} {pct:.0f}%",
                                metric=metric,
                                severity="high" if abs(z) > 2 else "medium",
                            ))
            except Exception:  # noqa: BLE001
                pass

        # ── Check 2: High-volatility metric (CV > 0.5) ──
        if sum_metrics and len(observations) < max_observations:
            for metric in sum_metrics[:3]:
                try:
                    vals = df[metric].dropna()
                    if len(vals) < 5:
                        continue
                    mean = vals.mean()
                    std = vals.std()
                    cv = std / mean if mean > 0 else 0
                    if cv > 0.6:
                        observations.append(AnomalyObservation(
                            icon="📈",
                            headline=f"{metric} 數值差異很大",
                            detail=f"變異係數 {cv:.1f}（高於 0.6 表示各筆資料差距懸殊）",
                            metric=metric,
                            severity="medium",
                        ))
                        break
                except Exception:  # noqa: BLE001
                    pass

        # ── Check 3: Ratio metric sanity (avg > 0.5 might be a data error) ──
        if ratio_metrics and len(observations) < max_observations:
            for metric in ratio_metrics:
                try:
                    avg = df[metric].dropna().mean()
                    if avg > 0.5:
                        observations.append(AnomalyObservation(
                            icon="⚠️",
                            headline=f"{metric} 平均值偏高，請確認單位",
                            detail=(
                                f"平均值 {avg:.2f}（若為百分比欄位，請確認資料是否已是小數形式如 0.05，"
                                f"而非整數 5）"
                            ),
                            metric=metric,
                            severity="high",
                        ))
                        break
                except Exception:  # noqa: BLE001
                    pass

        if len(observations) >= max_observations:
            break

    return observations[:max_observations]
