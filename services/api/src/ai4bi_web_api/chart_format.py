"""Validated cartesian display settings shared by Web and document export."""
from math import isfinite, fsum
import re

from .errors import AppError


def chart_format(query, style, rows, *, truncated=False):
    extra = style.extra
    scale = extra.get("y_scale", "linear")
    position = extra.get("legend_position")
    if scale not in ("linear", "log") or position not in (None, "top", "bottom", "left", "right", "hide"):
        raise AppError("INVALID_CHART_FORMAT", "座標軸或圖例設定無效。")
    bounds = [extra.get("y_min"), extra.get("y_max")]
    for value in bounds:
        if value is not None and (type(value) not in (int, float) or not isfinite(value) or (scale == "log" and value <= 0)):
            raise AppError("INVALID_CHART_FORMAT", "軸界限須為有限數字；對數界限須大於零。")
    if all(v is not None for v in bounds) and bounds[0] >= bounds[1]:
        raise AppError("INVALID_CHART_FORMAT", "縱軸下限必須小於上限。")
    fmt = extra.get("number_format", ",.0f")
    # Common Python/D3 numeric formats; do not evaluate expressions or templates.
    if not isinstance(fmt, str) or not re.fullmatch(r"[+,]?\.?\d{0,2}[f%eEgG]", fmt):
        raise AppError("INVALID_CHART_FORMAT", "數值格式須為數字格式，例如 ,.0f、.2f 或 .1%。" )
    try:
        format(1.25, fmt)
    except ValueError as exc:
        raise AppError("INVALID_CHART_FORMAT", "數值格式無效。") from exc
    labels = {}
    for metric in query.metrics:
        key = metric.alias or metric.metric_name
        labels[key] = [format(row[key], fmt) if type(row.get(key)) in (int, float) and isfinite(row[key]) else "—" for row in rows]
    dimensions = query.dimensions
    return {"version": 1, "y_scale": scale, "y_min": bounds[0], "y_max": bounds[1],
            "x_title": style.x_axis_label or ((dimensions[0].alias or dimensions[0].column_name) if dimensions else ""),
            "y_title": style.y_axis_label or "", "legend_position": position or "top",
            "show_legend": position != "hide" and (bool(position) or (style.show_legend and len(query.metrics) > 1)),
            "data_labels": bool(extra.get("data_labels", False)), "labels": labels,
            "baseline": baseline_result(query, extra, rows, scale, truncated)}


def baseline_result(query, extra, rows, scale, truncated):
    kind = extra.get("baseline")
    if not kind:
        return None
    if kind not in ("mean", "custom"):
        raise AppError("INVALID_BASELINE", "基準線類型無效。")
    key = query.metrics[0].alias or query.metrics[0].metric_name if query.metrics else None
    values = [row[key] for row in rows if key in row and type(row[key]) in (int, float) and isfinite(row[key])]
    result = {"kind": kind, "status": "unavailable", "value": None, "label": None, "reason": None,
              "metric_key": key, "valid_count": len(values), "excluded_count": len(rows)-len(values), "scope": "query_result"}
    if kind == "mean":
        if truncated:
            result["reason"] = "查詢結果已截斷，無法呈現完整結果的平均基準線。"
            return result
        if not values:
            result["reason"] = "第一指標沒有有限數值，無法計算平均基準線。"
            return result
        try:
            value = fsum(values) / len(values)
        except OverflowError:
            result["reason"] = "平均值超出可計算範圍，無法呈現基準線。"
            return result
    else:
        value = extra.get("baseline_value")
        if type(value) not in (int, float) or not isfinite(value):
            raise AppError("INVALID_BASELINE", "自訂基準線須為有限數字。")
    if scale == "log" and value <= 0:
        result["reason"] = "對數軸無法呈現小於或等於零的基準線。"
        return result
    result.update(status="ready", value=value, label=f"{'平均' if kind == 'mean' else '基準'} {value:,.2f}")
    return result
