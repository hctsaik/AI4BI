"""Attach fixed-core geographic lookup results without changing query rows."""
from .errors import AppError


def geographic_result(query, rows):
    from ai4bi.analysis.geo import resolve_coords
    from .core import clean
    if not query.dimensions:
        raise AppError("INVALID_MAP", "地圖需要一個地點維度，例如城市或縣市。")
    field = query.dimensions[0]
    name = field.alias or field.column_name
    points = []
    for index, row in enumerate(rows):
        if name not in row:
            raise AppError("INVALID_MAP", "地圖查詢缺少地點欄位。")
        coords = resolve_coords(row[name])
        if coords is not None:
            points.append({"row_index": index, "latitude": coords[0], "longitude": coords[1]})
    return {"version": 1, "location_field": {**clean(field), "key": name},
            "resolver": "ai4bi.analysis.geo.resolve_coords", "points": points,
            "mapped_count": len(points), "unmapped_count": len(rows) - len(points)}
