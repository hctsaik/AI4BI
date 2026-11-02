"""Pie weights and labels bound to governed rows, without client regrouping."""
from collections import Counter
from math import fsum, isfinite

from .errors import AppError


def pie_result(query, style, rows, *, truncated=False):
    if not query.metrics:
        raise AppError("INVALID_PIE", "圓餅圖至少需要一個指標。")
    metric = query.metrics[0]
    key = metric.alias or metric.metric_name
    try:
        hole = float(style.extra.get("hole", .4))
    except (ValueError, TypeError) as exc:
        raise AppError("INVALID_PIE", "圓環內徑須介於 0 與 0.9。") from exc
    if not isfinite(hole) or not 0 <= hole <= .9:
        raise AppError("INVALID_PIE", "圓環內徑須介於 0 與 0.9。")
    position = style.extra.get("legend_position") or "right"
    if position not in ("top", "bottom", "left", "right", "hide"):
        raise AppError("INVALID_PIE", "圖例位置無效。")
    settings = {"hole": hole, "show_percent": bool(style.extra.get("show_percent", True)),
                "data_labels": bool(style.extra.get("data_labels", False)), "legend_position": position,
                "show_legend": position != "hide" and (style.show_legend or bool(style.extra.get("legend_position")))}
    fields = [d.alias or d.column_name for d in query.dimensions]
    data = {"version": 1, "metric_key": key, "status": "unavailable", "reason": None,
            "slices": [], "excluded_count": 0, "weight_total": None, "settings": settings}
    candidates = []
    for index, row in enumerate(rows):
        if any(name not in row for name in [key, *fields]):
            raise AppError("INVALID_PIE", "圓餅圖查詢欄位缺失。")
        value = row[key]
        if type(value) not in (int, float) or not isfinite(value):
            data["excluded_count"] += 1
            continue
        labels = ["（空值）" if row[name] is None else "（空字串）" if row[name] == "" else str(row[name]) for name in fields]
        candidates.append({"row_index": index, "value": value, "label": " / ".join(labels) if labels else "全部",
                           "filter_value": row[fields[0]] if fields else None})
    if truncated:
        data["reason"] = "結果已截斷，請縮小查詢範圍後呈現比例。"
    elif any(p["value"] < 0 for p in candidates):
        data["reason"] = "權重含負值，無法呈現圓餅比例；可改用長條圖。"
    else:
        try:
            total = fsum(p["value"] for p in candidates)
        except OverflowError:
            total = float("inf")
        if not isfinite(total) or total <= 0:
            data["reason"] = "沒有正的有限權重總和，無法呈現圓餅比例。"
        else:
            counts = Counter(p["label"] for p in candidates)
            used = set()
            for piece in candidates:
                base = piece["label"]
                if counts[base] > 1:
                    piece["label"] = f"{base}〔列 {piece['row_index']+1}〕"
                while piece["label"] in used:
                    piece["label"] += f"〔列 {piece['row_index']+1}〕"
                used.add(piece["label"])
                piece["percent"] = piece["value"] / total * 100
            data.update(status="ready", slices=candidates, weight_total=total)
    return data
