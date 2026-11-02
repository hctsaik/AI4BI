"""Row-bound bar categories and series; never aggregate an accepted metric."""
import json
from collections import Counter
from math import isfinite

from .errors import AppError


def bar_result(query, style, rows):
    orientation = style.extra.get("orientation", "vertical")
    grouped = len(query.dimensions) > 1
    mode = style.extra.get("bar_mode", "stack" if grouped else "group")
    if orientation not in ("vertical", "horizontal") or mode not in ("group", "stack", "overlay"):
        raise AppError("INVALID_BAR", "長條方向或排列方式無效。")
    if not query.metrics:
        raise AppError("INVALID_BAR", "長條圖至少需要一個指標。")
    dimensions = [d.alias or d.column_name for d in query.dimensions]
    metrics = query.metrics[:1] if grouped else query.metrics
    categories, series, category_keys, series_keys = [], [], {}, {}
    def key(values):
        return json.dumps([(type(v).__name__, v) for v in values], ensure_ascii=False)
    def label(value):
        return "（空值）" if value is None else "（空字串）" if value == "" else str(value)
    for row_index, row in enumerate(rows):
        if any(name not in row for name in dimensions):
            raise AppError("INVALID_BAR", "長條分類欄位缺失。")
        values = [row[dimensions[0]], *[row[name] for name in dimensions[2:]]] if dimensions else [row_index]
        category_key = key(values)
        if category_key not in category_keys:
            category_keys[category_key] = len(categories)
            categories.append({"label": " / ".join(map(label, values)), "filter_value": values[0] if dimensions else None})
        category = category_keys[category_key]
        for metric in metrics:
            metric_key = metric.alias or metric.metric_name
            if metric_key not in row:
                raise AppError("INVALID_BAR", "長條指標欄位缺失。")
            group = row[dimensions[1]] if grouped else metric_key
            group_key = key([group])
            if group_key not in series_keys:
                series_keys[group_key] = len(series)
                series.append({"name": label(group), "metric_key": metric_key, "points": []})
            value = row[metric_key]
            value = value if type(value) in (int, float) and isfinite(value) else None
            series[series_keys[group_key]]["points"].append({"row_index": row_index, "category_index": category, "value": value})
    # Distinguish textually identical typed categories/groups in visible labels.
    for entries in (categories, series):
        field = "label" if entries is categories else "name"
        labels = Counter(entry[field] for entry in entries)
        for index, entry in enumerate(entries):
            if labels[entry[field]] > 1:
                entry[field] += f"〔{index+1}〕"
    return {"version": 1, "orientation": orientation, "mode": mode, "grouped": grouped,
            "categories": categories, "series": series}
