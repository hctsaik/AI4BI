"""Governed daily KPI series, separate from the headline aggregation."""
from contextlib import nullcontext
from dataclasses import replace
from datetime import date

from ai4bi.query_spec import DimensionRef, SortSpec, SortDirection
from .comparison import validate_comparison, window_executor
from .errors import AppError
from .kpi import finite


def validate_sparkline(query, style, contracts):
    if not style.show_sparkline:
        return None
    # Legacy grouped cards remain tables until explicitly edited by the user.
    if query.dimensions:
        return None
    extra = style.extra
    comparison = validate_comparison(query, style, contracts)
    block = comparison["block_id"] if comparison else extra.get("sparkline_date_block", query.primary_block_id)
    column = comparison["column_name"] if comparison else extra.get("sparkline_date_column")
    contract = contracts.get(block) if isinstance(block, str) else None
    field = next((c for c in contract.columns if c.name == column), None) if contract else None
    if (len(query.metrics) != 1 or extra.get("postprocess") or field is None
            or block not in query.all_block_ids or field.data_type.lower() not in ("date", "datetime", "timestamp")):
        raise AppError("INVALID_SPARKLINE", "趨勢小圖需要有效日期欄位與單一未分組指標，且不可有後處理。")
    return block, column


def sparkline_result(executor, query, style, contracts, *, active_filters, page_id, visual_id, comparison=None):
    from .core import clean
    config = validate_sparkline(query, style, contracts)
    if config is None:
        return None
    block, column = config
    result = {"version": 1, "status": "unavailable", "reason": None, "timezone": "UTC",
              "block_id": block, "column_name": column, "points": [], "truncated": False,
              "limit": 365, "metadata": None, "caption": "逐日指標 · UTC 日界 · 最多最近 365 個有結果日期；缺日不補零"}
    scoped, base = executor, query
    window = None
    if comparison:
        if not comparison["current_window"]:
            result["reason"] = "目前沒有有效比較日期，無法產生趨勢。"
            return result
        scoped, base = window_executor(executor, query, comparison, page_id, visual_id)
        window = tuple(date.fromisoformat(day) for day in comparison["current_window"])
    metric = query.metrics[0].alias or query.metrics[0].metric_name
    alias = "__sparkline_day"
    while alias == metric:
        alias += "_"
    series_query = replace(base, dimensions=[DimensionRef(block, column, alias)],
        sort=[SortSpec(alias, SortDirection.desc)], limit=366,
        data_version=f"{base.data_version}:sparkline:{block}:{column}:{window}")
    with scoped.daily_series(block, column), (scoped.comparison_window(block, column, window) if window else nullcontext()):
        frame, metadata = scoped.run_with_metadata(series_query, active_filters=active_filters, page_id=page_id, visual_id=visual_id)
    rows = clean(frame)["rows"]
    rows = [row for row in rows if row.get(alias) is not None]
    result["truncated"] = len(rows) > 365
    points = [{"date": str(row[alias])[:10], "value": row.get(metric)} for row in rows[:365]]
    points.sort(key=lambda point: point["date"])
    result.update(points=points, metadata=clean(metadata))
    if any(finite(point["value"]) for point in points):
        result["status"] = "ready"
    else:
        result["reason"] = "目前沒有可繪製的有限數值；精確原值保留於趨勢資料。"
    if result["truncated"]:
        result["caption"] += "（已截斷較早日期）"
    if query.having:
        result["caption"] += " · 聚合篩選依每日結果判定"
    return result
