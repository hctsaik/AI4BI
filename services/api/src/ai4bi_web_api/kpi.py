"""KPI display and target evaluation from the accepted governed scalar result."""
from math import isfinite

from .errors import AppError


def finite(value):
    return type(value) in (int, float) and isfinite(value)


def validate_kpi(style):
    extra = style.extra
    decimals = extra.get("decimals")
    if decimals is not None and (type(decimals) is not int or not 0 <= decimals <= 6):
        raise AppError("INVALID_KPI", "KPI 小數位須為 0 到 6 的整數。")
    if not isinstance(extra.get("unit", ""), str) or len(extra.get("unit", "")) > 64:
        raise AppError("INVALID_KPI", "KPI 單位須為最多 64 字的文字。")
    if type(extra.get("compact", False)) is not bool:
        raise AppError("INVALID_KPI", "KPI 縮寫設定須為布林值。")
    if extra.get("target_good_if", "gte") not in ("gte", "lte"):
        raise AppError("INVALID_KPI", "目標方向須為越高越好或越低越好。")
    if extra.get("target") is not None and not finite(extra["target"]):
        raise AppError("INVALID_KPI", "目標須為有限數字。")
    rag = extra.get("rag")
    if rag is not None:
        if not isinstance(rag, dict) or not finite(rag.get("target")) or rag.get("good_if", "gte") not in ("gte", "lte"):
            raise AppError("INVALID_KPI", "狀態門檻須有有限目標與有效方向。")
        warn = rag.get("warn")
        if warn is not None and (not finite(warn) or (warn > rag["target"] if rag.get("good_if", "gte") == "gte" else warn < rag["target"])):
            raise AppError("INVALID_KPI", "注意門檻須位於未達標側，且為有限數字。")


def number_label(value, extra):
    if not finite(value):
        return "—"
    suffix = ""
    if extra.get("compact", False):
        for divisor, abbreviation in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
            if abs(value) >= divisor:
                value, suffix = value / divisor, abbreviation
                break
    decimals = extra.get("decimals")
    text = f"{value:,.{2 if decimals is None else decimals}f}"
    if decimals is None:
        text = text.rstrip("0").rstrip(".")
    return text + suffix


def kpi_result(query, style, rows, *, truncated=False):
    validate_kpi(style)
    extra = style.extra
    result = {"version": 1, "status": "table", "value": None, "label": None,
              "unit": extra.get("unit", ""), "rag": None, "pacing": None, "reason": None}
    if query.dimensions or len(query.metrics) != 1 or len(rows) > 1 or truncated:
        result["reason"] = "分組、多指標或截斷結果保留完整資料表，不取第一列作為總計。"
        return result
    key = query.metrics[0].alias or query.metrics[0].metric_name
    value = rows[0].get(key) if rows else None
    result.update(status="ready" if finite(value) else "unavailable", value=value if finite(value) else None,
                  label=number_label(value, extra))
    if not finite(value):
        result["reason"] = "目前沒有有限數值，無法判定目標或狀態。"
        return result
    rag = extra.get("rag")
    if rag is not None:
        target, warn, direction = rag["target"], rag.get("warn"), rag.get("good_if", "gte")
        good = value >= target if direction == "gte" else value <= target
        warning = warn is not None and (value >= warn if direction == "gte" else value <= warn)
        state = "good" if good else "warning" if warning else "bad"
        result["rag"] = {"state": state, "target": target, "warn": warn, "good_if": direction,
                         "label": f"{ {'good': '達標', 'warning': '注意', 'bad': '未達標'}[state]}（目標 {'>=' if direction == 'gte' else '<='} {number_label(target, extra)}{result['unit']}）"}
    target = extra.get("target")
    if target is not None:
        direction = extra.get("target_good_if", "gte")
        good = value >= target if direction == "gte" else value <= target
        label = f"目標 {'>=' if direction == 'gte' else '<='} {number_label(target, extra)}{result['unit']} · {'已達標' if good else '未達標'}"
        pacing = {"status": "unavailable", "target": target, "good_if": direction, "on_track": good,
                  "fraction": None, "percent_of_target": None, "label": label, "reason": None}
        if target <= 0 or value < 0:
            pacing["reason"] = "進度比例限正目標與非負實際值；達標判定仍依原始數值。"
        else:
            percent = value / target * 100
            fraction = value / target if direction == "gte" else target / value if value else 1
            if not isfinite(percent) or not isfinite(fraction):
                pacing["reason"] = "進度比例超出可呈現範圍。"
            else:
                pacing.update(status="ready", fraction=max(0, min(fraction, 1)), percent_of_target=percent,
                              label=label + f" · 實際為目標 {percent:,.1f}%")
        result["pacing"] = pacing
    return result
