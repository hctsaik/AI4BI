"""Pivot axes and independently evaluated totals from one accepted snapshot."""
from dataclasses import replace
import json

from .errors import AppError


def pivot_result(executor, query, style, cells, *, active_filters, page_id, visual_id, limit=5000):
    from .core import clean

    if not 1 <= len(query.dimensions) <= 2 or not query.metrics:
        raise AppError("INVALID_PIVOT", "樞紐表需要一個列維度、至多一個欄維度及至少一個指標。")
    if style.extra.get("postprocess"):
        raise AppError("INVALID_PIVOT", "樞紐表需要原始聚合指標，請先移除累計或 Top N 等後處理。")
    row = query.dimensions[0]
    column = query.dimensions[1] if len(query.dimensions) == 2 else None
    dimension_names = [d.alias or d.column_name for d in query.dimensions]
    metrics = [{"key": m.alias or m.metric_name, "block_id": m.block_id,
                "metric_name": m.metric_name} for m in query.metrics]
    required = dimension_names + [m["key"] for m in metrics]
    if len(set(required)) != len(required) or not cells.columns.is_unique or any(name not in cells.columns for name in required):
        raise AppError("INVALID_PIVOT", "樞紐欄位名稱缺失或重複，請設定不同的維度與指標別名。")
    if cells.duplicated(subset=dimension_names).any():
        raise AppError("INVALID_PIVOT", "樞紐列與欄的組合不唯一，無法自行合併數值。")

    def total(dimensions):
        # Preserve every source/ref/filter/metric/parameter policy. Group ordering
        # and presentation row limits must not silently reduce the total's input.
        subtotal_query = replace(query, dimensions=dimensions, sort=[], limit=None)
        frame, metadata = executor.run_with_metadata(subtotal_query, active_filters=active_filters,
                                                     page_id=page_id, visual_id=visual_id)
        names = [d.alias or d.column_name for d in dimensions] + [m["key"] for m in metrics]
        if not frame.columns.is_unique or any(name not in frame.columns for name in names):
            raise AppError("INVALID_PIVOT", "樞紐總計欄位與原查詢不一致。")
        return {**clean(frame.head(limit)), "row_count": len(frame), "truncated": len(frame) > limit,
                "metadata": clean(metadata), "query": clean(subtotal_query)}

    row_totals = total([row])
    column_totals = total([column]) if column else None
    grand_total = total([])
    return {"version": 1, "row_field": {**clean(row), "key": dimension_names[0]},
            "column_field": {**clean(column), "key": dimension_names[1]} if column else None,
            "metrics": metrics, "totals_scope": "filtered_population", "having_scope": "each_aggregation_grain",
            "row_totals": row_totals, "column_totals": column_totals, "grand_total": grand_total,
            "truncated": any(item and item["truncated"] for item in (row_totals, column_totals, grand_total))}


def matrix_tables(result, columns_per_part=4):
    """Yield bounded-width export tables; never aggregate already aggregated values."""
    spec = result.get("pivot")
    if not spec or spec.get("version") != 1 or spec.get("totals_scope") != "filtered_population":
        raise AppError("INVALID_PIVOT", "樞紐匯出缺少相容的核心總計。")
    if columns_per_part < 1:
        raise ValueError("columns_per_part must be positive")
    row_field = spec["row_field"]["key"]
    column_field = spec["column_field"]["key"] if spec["column_field"] else None
    rows, columns, cells = {}, {}, {}

    def key(value):
        return json.dumps([type(value).__name__, value], ensure_ascii=False, allow_nan=False)

    def label(value):
        # Explicit type makes null/string, bool/int and user-supplied labels distinct.
        return f"{type(value).__name__}: {json.dumps(value, ensure_ascii=False, allow_nan=False)}"

    for cell in result["rows"]:
        rv, cv = cell[row_field], cell[column_field] if column_field else None
        rk, ck = key(rv), key(cv)
        rows[rk], columns[ck] = rv, cv
        if (rk, ck) in cells:
            raise AppError("INVALID_PIVOT", "樞紐儲存格重複，無法匯出。")
        cells[rk, ck] = cell

    def total_index(total, field, axis):
        indexed = {}
        for row in (total or {}).get("rows", []):
            value = row[field]
            identity = key(value)
            if identity in indexed:
                raise AppError("INVALID_PIVOT", "樞紐總計重複，無法匯出。")
            indexed[identity], axis[identity] = row, value
        return indexed

    row_totals = total_index(spec["row_totals"], row_field, rows)
    column_totals = total_index(spec["column_totals"], column_field, columns)
    if not columns and not column_field:
        columns[key(None)] = None
    grand_rows = spec["grand_total"]["rows"]
    if len(grand_rows) > 1:
        raise AppError("INVALID_PIVOT", "樞紐總計不唯一。")
    grand = grand_rows[0] if grand_rows else None
    column_items = list(columns.items())
    for metric in spec["metrics"]:
        metric_key = metric["key"]

        def measure(row):
            if row is None:
                return "—"
            value = row[metric_key]
            return "（空值）" if value is None else value

        for offset in range(0, max(1, len(column_items)), columns_per_part):
            part = column_items[offset:offset + columns_per_part]
            headings = [f"列維度：{row_field}"] + [
                f"C{offset+i+1} {label(value)}" if column_field else "指標值"
                for i, (_, value) in enumerate(part)] + ["列總計"]
            records = []
            for rk, rv in rows.items():
                values = [label(rv)] + [measure(cells.get((rk, ck))) for ck, _ in part] + [measure(row_totals.get(rk))]
                records.append(dict(zip(headings, values)))
            totals = ["欄總計／總計"] + [measure(column_totals.get(ck) if column_field else grand) for ck, _ in part] + [measure(grand)]
            records.append(dict(zip(headings, totals)))
            yield {"columns": headings, "rows": records, "pivot_part": {
                "metric": metric, "part": offset // columns_per_part + 1,
                "parts": max(1, (len(column_items) + columns_per_part - 1) // columns_per_part),
                "row_field": spec["row_field"], "column_field": spec["column_field"],
                "column_values": [value for _, value in part], "totals_scope": spec["totals_scope"],
                "note": "各段總計皆依完整篩選資料計算，不可跨段相加；聚合門檻各自套用。— 為未回傳，空值為核心空值。"}}
