"""Bind scatter coordinates to governed result rows, shared by Web and PDF."""
from math import isfinite

from .errors import AppError


def scatter_result(query, style, rows, *, truncated=False):
    if not query.metrics:
        raise AppError("INVALID_SCATTER", "散點圖至少需要一個指標。")
    keys = [m.alias or m.metric_name for m in query.metrics[:2]]
    group = query.dimensions[0] if query.dimensions else None
    group_key = (group.alias or group.column_name) if group else None
    size_key = style.extra.get("size_col") or None
    if size_key is not None and not isinstance(size_key, str):
        raise AppError("INVALID_SCATTER", "散點圖大小欄位無效。")
    finite = lambda value: type(value) in (int, float) and isfinite(value)
    points = []
    for index, row in enumerate(rows):
        if any(key not in row for key in [*keys, *([group_key] if group_key else []), *([size_key] if size_key else [])]):
            raise AppError("INVALID_SCATTER", "散點圖座標或分組／大小欄位缺失。")
        x, y = row[keys[0]], row[keys[1]] if len(keys) > 1 else index
        size = row[size_key] if size_key else None
        if size is not None and (not finite(size) or size < 0):
            raise AppError("INVALID_SCATTER", "散點圖大小欄位須為非負有限數值。")
        if not finite(x) or not finite(y):
            continue
        points.append({"row_index": index, "x": x, "y": y,
                       "group": row[group_key] if group_key else None, "size": size})
    method = style.extra.get("trendline") or None
    if method not in (None, "ols", "lowess"):
        raise AppError("INVALID_SCATTER", "趨勢線僅支援 OLS 或 LOWESS。")
    return {"version": 1, "x_key": keys[0], "y_key": keys[1] if len(keys) > 1 else None,
            "group_key": group_key, "size_key": size_key, "points": points,
            "excluded_count": len(rows) - len(points), "trendline": method,
            "trendlines": fit_trendlines(points, method, truncated) if method else []}


def fit_trendlines(points, method, truncated=False):
    import numpy as np
    from statsmodels.regression.linear_model import OLS
    from statsmodels.nonparametric.smoothers_lowess import lowess
    groups = {}
    for point in points:
        key = (type(point["group"]).__name__, point["group"])
        groups.setdefault(key, []).append(point)
    results = []
    for group in groups.values():
        ordered = sorted(group, key=lambda p: p["x"])
        x = np.asarray([p["x"] for p in ordered], dtype=float)
        y = np.asarray([p["y"] for p in ordered], dtype=float)
        result = {"group": group[0]["group"], "method": method, "n": len(group),
                  "status": "unavailable", "x": [], "y": [], "intercept": None, "slope": None, "r_squared": None}
        reason = "結果超過完整呈現上限，請縮小查詢範圍後擬合。" if truncated else (
            "至少需要兩筆有限座標。" if len(group) < 2 else "X 沒有變化，無法估計趨勢。" if np.unique(x).size < 2 else None)
        if reason:
            result["reason"] = reason
        else:
            try:
                if method == "ols":
                    model = OLS(y, np.column_stack((np.ones(len(x)), x)), missing="raise").fit()
                    if model.model.rank < 2:
                        raise ValueError("Numerically singular regression")
                    fitted = model.predict()
                    if np.isfinite(model.params).all():
                        result["intercept"], result["slope"] = map(float, model.params)
                    with np.errstate(divide="ignore", invalid="ignore"):
                        score = float(model.rsquared)
                    result["r_squared"] = score if isfinite(score) else None
                else:
                    fitted = lowess(y, x, frac=.6666666, it=3, delta=0., is_sorted=True, missing="raise", return_sorted=True)[:, 1]
                if not np.isfinite(fitted).all():
                    raise ValueError("Nonfinite fitted curve")
                result.update(status="ready", x=x.tolist(), y=fitted.tolist())
            except (ValueError, FloatingPointError, np.linalg.LinAlgError):
                result["reason"] = "此組資料無法產生有限擬合結果。"
        results.append(result)
    return results
