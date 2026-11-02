"""Offline geographic PDF rendering of accepted query rows, without aggregation."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .errors import AppError


def land_rings(topology):
    """Decode TopoJSON transforms, reversed arcs and polygon rings.

    Format: https://github.com/topojson/topojson-specification#213-arcs
    Only our packaged polygon land geometry is consumed.
    """
    transform = topology.get("transform")
    arcs = []
    for arc in topology["arcs"]:
        points = np.asarray(arc, dtype=float)[:, :2]
        if transform:
            points = np.cumsum(points, axis=0)
            points = points * transform["scale"] + transform["translate"]
        arcs.append(points)

    def geometry(item):
        if item["type"] == "GeometryCollection":
            for child in item["geometries"]:
                yield from geometry(child)
            return
        polygons = [item["arcs"]] if item["type"] == "Polygon" else item["arcs"]
        if item["type"] not in ("Polygon", "MultiPolygon"):
            raise ValueError("Expected polygon land geometry")
        for polygon in polygons:
            rings = []
            for ring in polygon:
                parts = [arcs[i] if i >= 0 else arcs[~i][::-1] for i in ring]
                rings.append(np.concatenate([parts[0], *[p[1:] for p in parts[1:]]]))
            yield rings

    return list(geometry(topology["objects"]["land"]))


def project(points, world=False):
    """Mercator / Natural Earth I forward projection in radians.

    Natural Earth polynomial coefficients agree with d3-geo naturalEarth1Raw:
    https://github.com/d3/d3-geo/blob/main/src/projection/naturalEarth1.js
    """
    points = np.asarray(points, dtype=float).reshape((-1, 2))
    lon, lat = np.radians(points[:, 0]), np.radians(points[:, 1])
    if world:
        square = lat * lat
        x = lon * np.polynomial.polynomial.polyval(square, [.8707, -.131979, -.013791, 0, 0, .003971, -.001529])
        y = lat * np.polynomial.polynomial.polyval(square, [1.007226, .015085, 0, -.044475, .028874, -.005916])
    else:
        # Mercator has no finite pole; clip the background at 85 degrees.
        lat = np.clip(lat, np.radians(-85), np.radians(85))
        x, y = lon, np.log(np.tan(np.pi / 4 + lat / 2))
    return np.column_stack((x, y))


def split_dateline(ring):
    """Clip unwrapped rings into the canonical longitude window before projection."""
    if not np.any(np.abs(np.diff(ring[:, 0])) > 180):
        return [ring]
    unwrapped = ring.copy()
    unwrapped[:, 0] = np.degrees(np.unwrap(np.radians(ring[:, 0])))
    if abs(unwrapped[-1, 0] - unwrapped[0, 0]) > 180:
        # A full winding encloses a pole. Close through that pole, not across land.
        pole = -90 if np.mean(ring[:, 1]) < 0 else 90
        unwrapped = np.vstack((unwrapped, [unwrapped[-1, 0], pole],
                               [unwrapped[0, 0], pole], unwrapped[0]))

    def clip(points, boundary, keep_greater):
        output = []
        previous = points[-1]
        inside = lambda p: p[0] >= boundary if keep_greater else p[0] <= boundary
        for current in points:
            if inside(previous) != inside(current):
                ratio = (boundary - previous[0]) / (current[0] - previous[0])
                output.append([boundary, previous[1] + ratio * (current[1] - previous[1])])
            if inside(current):
                output.append(current)
            previous = current
        return np.asarray(output).reshape((-1, 2))

    pieces = []
    first = int(np.floor((unwrapped[:, 0].min() + 180) / 360))
    last = int(np.floor((unwrapped[:, 0].max() + 180) / 360))
    for offset in range(first, last + 1):
        shifted = unwrapped - [360 * offset, 0]
        piece = clip(shifted, -180, True)
        if len(piece):
            piece = clip(piece, 180, False)
        if len(piece) >= 3:
            if not np.array_equal(piece[0], piece[-1]):
                piece = np.vstack((piece, piece[0]))
            pieces.append(piece)
    return pieces


def geographic_page(pdf, spec, visual, title, footer):
    from matplotlib import pyplot as plt
    from matplotlib.path import Path as PlotPath
    from matplotlib.patches import PathPatch
    from matplotlib.colors import is_color_like

    geo = visual.get("geo")
    if not geo or geo.get("version") != 1:
        raise AppError("INVALID_MAP", "地圖匯出缺少相容座標，請重新查詢。")
    try:
        asset = Path(__file__).parent / "static/maps/world_50m.json"
        polygons = land_rings(json.loads(asset.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise AppError("EXPORT_MAP_MISSING", "離線地圖底圖缺失或損壞，請重新建置或安裝。") from exc
    extra = spec["visualization"].get("extra", {})
    view = extra.get("map_view", "auto")
    world = view == "world"
    metrics = spec["query"].get("metrics", [])
    metric = (metrics[0].get("alias") or metrics[0]["metric_name"]) if metrics else None
    points, values, seen = [], [], set()
    for point in geo["points"]:
        index = point["row_index"]
        if type(index) is not int or index < 0 or index >= len(visual["rows"]) or index in seen:
            raise AppError("INVALID_MAP", "地圖匯出列索引無效。")
        seen.add(index)
        coordinates = [point["longitude"], point["latitude"]]
        if not np.isfinite(coordinates).all() or abs(coordinates[0]) > 180 or abs(coordinates[1]) > 90:
            raise AppError("INVALID_MAP", "地圖匯出座標無效。")
        row = visual["rows"][index]
        if geo["location_field"]["key"] not in row or (metric and metric not in row):
            raise AppError("INVALID_MAP", "地圖匯出欄位缺失。")
        value = row.get(metric) if metric else None
        values.append(float(value) if type(value) in (int, float) and np.isfinite(value) else None)
        points.append(coordinates)
    locations = project(points, world)
    fig, ax = plt.subplots(figsize=(11, 7))
    try:
        fig.suptitle(title, parse_math=False)
        fig.text(.05, .02, footer, fontsize=8, parse_math=False)
        ax.set_facecolor("#e7f2f8")
        for polygon in polygons:
            vertices, codes = [], []
            for ring in polygon:
                for piece in split_dateline(ring):
                    projected = project(piece, world)
                    vertices.extend(projected)
                    codes.extend([PlotPath.MOVETO, *([PlotPath.LINETO] * (len(piece) - 2)), PlotPath.CLOSEPOLY])
            ax.add_patch(PathPatch(PlotPath(vertices, codes), facecolor="#e5ede3", edgecolor="#77958c", linewidth=.35))
        maximum = max((abs(v) for v in values if v is not None), default=0)
        sizes = [49 if v is None or v == 0 else max(49, 1600 * abs(v) / maximum) for v in values]
        color = extra.get("color", "#2874a6")
        if not is_color_like(color):
            color = "#2874a6"
        colors = ["#8395a1" if v is None else "#b34a57" if v < 0 else color for v in values]
        if len(locations):
            ax.scatter(locations[:, 0], locations[:, 1], s=sizes, c=colors, alpha=.8, edgecolors="white", linewidths=.7, zorder=3)
        if view == "taiwan":
            bounds = project([[118.5, 21.5], [123, 26]], world)
        elif world or not len(locations):
            bounds = project([[-180, -90 if world else -85], [180, 90 if world else 85]], world)
            if world:
                bounds[:, 0] = [-np.pi * .8707, np.pi * .8707]
        else:
            low, high = locations.min(axis=0), locations.max(axis=0)
            padding = np.maximum((high - low) * .15, np.radians(.5))
            bounds = np.array([low - padding, high + padding])
        ax.set_xlim(bounds[:, 0]); ax.set_ylim(bounds[:, 1]); ax.set_aspect("equal")
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(f"已定位 {len(points)} 筆；未定位 {geo['unmapped_count']} 筆 | {metric or '地點'}", parse_math=False)
        if not points:
            ax.text(.5, .5, "沒有可定位地點；完整資料見後續頁", transform=ax.transAxes, ha="center")
        fig.text(.05, .065, "氣泡面積依指標絕對值；紅色為負值、灰色為空值，零值保留最小標記。完整地點與數值見後續資料表。", fontsize=8)
        fig.tight_layout(rect=[0, .09, 1, .94])
        pdf.savefig(fig)
    finally:
        plt.close(fig)
