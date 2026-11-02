"""Server-side distribution summaries of the governed raw query population."""
from .errors import AppError


def validate_histogram(query, style):
    bins = style.extra.get("bins", 20)
    if type(bins) is not int or not 1 <= bins <= 200:
        raise AppError("INVALID_HISTOGRAM", "直方圖分箱數必須為 1–200 的整數。")
    if len(query.dimensions) != 1 or query.metrics or query.having or query.dimensions[0].truncate_date_to:
        raise AppError("INVALID_HISTOGRAM", "直方圖需要單一原始數值維度，不可使用聚合指標或聚合門檻。")
    if style.extra.get("postprocess"):
        raise AppError("INVALID_HISTOGRAM", "直方圖不可套用聚合後處理。")
    return bins


def histogram_result(query, style, frame):
    import numpy as np
    import pandas as pd
    from .core import clean
    bins = validate_histogram(query, style)
    field = query.dimensions[0]
    name = field.alias or field.column_name
    if not frame.columns.is_unique or name not in frame.columns:
        raise AppError("INVALID_HISTOGRAM", "直方圖數值欄位缺失或重複。")
    series = frame[name]
    if len(series) and not series.isna().all() and (not pd.api.types.is_numeric_dtype(series.dtype) or pd.api.types.is_bool_dtype(series.dtype)
                        or pd.api.types.is_complex_dtype(series.dtype)):
        raise AppError("INVALID_HISTOGRAM", "直方圖只能使用數值欄位。")
    values = series.to_numpy(dtype=float, na_value=np.nan)
    values = values[np.isfinite(values)]
    if np.any(np.abs(values) > 2**53 - 1):
        raise AppError("INVALID_HISTOGRAM", "數值超過直方圖可精確處理的範圍，請先調整單位。")
    rows, ranges = [], []
    if len(values):
        try:
            counts, edges = np.histogram(values, bins=bins)
        except (ValueError, IndexError, FloatingPointError) as exc:
            raise AppError("INVALID_HISTOGRAM", "此數值範圍無法可靠分箱，請調整分箱數或單位。") from exc
        if not np.all(np.isfinite(edges)) or not np.all(np.diff(edges) > 0):
            raise AppError("INVALID_HISTOGRAM", "數值精度不足以區分分箱邊界，請調整分箱數或單位。")
        rows = [{"lower": float(edges[i]), "upper": float(edges[i+1]),
                 "right_inclusive": i == len(counts)-1, "count": int(count)} for i, count in enumerate(counts)]
        ranges = [[float(edges[i]), float(edges[i+1]) if i == len(counts)-1
                   else float(np.nextafter(edges[i+1], -np.inf))] for i in range(len(counts))]
    summary = {"version": 1, "field": {**clean(field), "key": name}, "bins": bins, "filter_ranges": ranges,
               "source_count": len(frame), "valid_count": len(values), "excluded_count": len(frame)-len(values),
               "query_limit": query.limit, "mean": float(np.mean(values)) if len(values) else None,
               "median": float(np.median(values)) if len(values) else None,
               "min": float(np.min(values)) if len(values) else None, "max": float(np.max(values)) if len(values) else None}
    return pd.DataFrame(rows, columns=["lower", "upper", "right_inclusive", "count"]), summary
