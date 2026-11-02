"""Actual document output checks; governed query integration lives in test_workspace_api."""
import copy
import pytest

from ai4bi_web_api import exports


def kpi_data(value, extra, *, dimensions=None, metrics=None, rows=None, truncated=False):
    from types import SimpleNamespace
    from ai4bi.query_spec import MetricRef
    from ai4bi_web_api.kpi import kpi_result
    return kpi_result(SimpleNamespace(dimensions=dimensions or [], metrics=metrics or [MetricRef("b", "value")]),
                      SimpleNamespace(extra=extra), rows if rows is not None else [{"value": value}], truncated=truncated)


@pytest.mark.parametrize("direction,value,target,warn,state,fraction", [
    ("gte", 600, 800, 500, "warning", .75), ("gte", 800, 800, 500, "good", 1),
    ("gte", 499, 800, 500, "bad", 499/800), ("lte", 6, 4, 7, "warning", 4/6),
    ("lte", 4, 4, 7, "good", 1), ("lte", 8, 4, 7, "bad", .5),
    ("lte", 0, 4, 7, "good", 1), ("gte", 0, 4, 2, "bad", 0),
])
def test_kpi_thresholds_and_pacing(direction, value, target, warn, state, fraction):
    data = kpi_data(value, {"target": target, "target_good_if": direction,
                           "rag": {"target": target, "warn": warn, "good_if": direction}})
    assert data["value"] == value and data["rag"]["state"] == state
    assert data["pacing"]["fraction"] == pytest.approx(fraction)
    assert data["pacing"]["percent_of_target"] == pytest.approx(value/target*100)
    assert data["pacing"]["on_track"] == (state == "good")


@pytest.mark.parametrize("extra", [
    {"decimals": True}, {"decimals": 1.5}, {"decimals": 7}, {"unit": ["x"]}, {"unit": "x"*65},
    {"compact": "true"}, {"target": True}, {"target": "5"}, {"target": float("inf")},
    {"target_good_if": "invalid"}, {"rag": []}, {"rag": {}},
    {"rag": {"target": 5, "warn": 6}}, {"rag": {"target": 5, "warn": 4, "good_if": "lte"}},
])
def test_kpi_invalid_settings_rejected(extra):
    from ai4bi_web_api.errors import AppError
    with pytest.raises(AppError) as raised:
        kpi_data(600, extra)
    assert raised.value.code == "INVALID_KPI"


def test_kpi_format_does_not_change_threshold_comparison_or_raw_values():
    extra = {"decimals": 0, "unit": "%", "rag": {"target": 90, "warn": 80}}
    data = kpi_data(89.999, extra)
    assert data["label"] == "90" and data["value"] == 89.999 and data["rag"]["state"] == "warning"
    assert kpi_data(1234567.89, {"compact": True, "decimals": 2})["label"] == "1.23M"
    assert kpi_data(-1234.5, {"compact": True, "decimals": 1})["label"] == "-1.2K"
    assert kpi_data(600, {})["label"] == "600"
    for value in (None, True, "5", float("nan"), float("inf")):
        data = kpi_data(value, {"target": 800, "rag": {"target": 800}})
        assert data["status"] == "unavailable" and data["label"] == "—"
        assert data["rag"] is None and data["pacing"] is None
    for value, target in ((0, 0), (-2, -1), (-1, 2), (1e308, 1e-308)):
        data = kpi_data(value, {"target": target})
        assert data["pacing"]["status"] == "unavailable" and data["pacing"]["fraction"] is None
    for options in ({"dimensions": ["category"]}, {"rows": [{"value": 1}, {"value": 2}]}, {"truncated": True}):
        assert kpi_data(1, {"target": 5}, **options)["status"] == "table"


@pytest.mark.parametrize("format", ["pdf", "xlsx"])
def test_kpi_sparkline_export_preserves_series_and_headline(tmp_path, monkeypatch, format):
    from pypdf import PdfReader
    from openpyxl import load_workbook
    snapshot, result = snapshot_result(); snapshot["format"] = format
    spec = snapshot["report"]["pages"]["main"]["visuals"]["table"]
    spec["visualization"]["visual_type"] = "kpi_card"
    spec["query"] = {"dimensions": [], "metrics": [{"metric_name": "value"}]}
    data = kpi_data(600, {})
    data["sparkline"] = {"points": [{"date": "2024-01-01", "value": 5}, {"date": "2024-01-03", "value": 7}],
                         "caption": "UTC daily series", "reason": None}
    result["visuals"] = {"table": {"status": "ready", "columns": ["value"], "rows": [{"value": 600}], "kpi": data}}
    monkeypatch.setattr(exports, "run_query", lambda *_: copy.deepcopy(result))
    exports.export_snapshot(tmp_path, snapshot, tmp_path)
    if format == "pdf":
        pages = PdfReader(tmp_path / "export.pdf").pages
        assert len(pages) == 2
        assert "UTC daily series" in pages[0].extract_text()
        assert "600" in pages[1].extract_text()
    else:
        workbook = load_workbook(tmp_path / "export.xlsx")
        rows = list(next(sheet for sheet in workbook.worksheets if sheet.cell(1, 1).value == "value").values)
        assert rows[1][0] == 600
        assert any(row[:2] == ("2024-01-01", 5) for row in rows)
        assert any(row[:2] == ("2024-01-03", 7) for row in rows)


def test_kpi_pdf_uses_server_formatted_value_and_status(tmp_path, monkeypatch):
    from pypdf import PdfReader
    snapshot, result = snapshot_result(); snapshot["format"] = "pdf"
    spec = snapshot["report"]["pages"]["main"]["visuals"]["table"]
    spec["visualization"]["visual_type"] = "kpi_card"
    spec["query"] = {"dimensions": [], "metrics": [{"metric_name": "value"}]}
    data = kpi_data(600, {"decimals": 1, "unit": "件", "target": 800, "rag": {"target": 800, "warn": 500}})
    result["visuals"] = {"table": {"status": "ready", "columns": ["value"], "rows": [{"value": 600}], "kpi": data}}
    monkeypatch.setattr(exports, "run_query", lambda *_: copy.deepcopy(result))
    exports.export_snapshot(tmp_path, snapshot, tmp_path)
    text = "\n".join(p.extract_text() for p in PdfReader(tmp_path / "export.pdf").pages)
    assert all(label in text for label in ["600.0件", data["rag"]["label"], data["pacing"]["label"]])


def test_baseline_mean_uses_finite_first_metric_and_rejects_incomplete_population():
    from ai4bi.query_spec import MetricRef
    from types import SimpleNamespace
    from ai4bi_web_api.chart_format import baseline_result
    query = SimpleNamespace(metrics=[MetricRef("b", "amount"), MetricRef("b", "other")])
    rows = [{"amount": v, "other": 999} for v in [2, 4, None, "5", True]]
    mean = baseline_result(query, {"baseline": "mean"}, rows, "linear", False)
    assert mean["value"] == 3 and mean["valid_count"] == 2 and mean["excluded_count"] == 3
    assert mean["scope"] == "query_result" and mean["label"] == "平均 3.00"
    assert baseline_result(query, {"baseline": "mean"}, rows, "linear", True)["status"] == "unavailable"
    assert baseline_result(query, {"baseline": "mean"}, [], "linear", False)["status"] == "unavailable"
    assert baseline_result(query, {"baseline": "custom", "baseline_value": 0}, rows, "log", False)["status"] == "unavailable"


@pytest.mark.parametrize("value", [None, True, "5", float("inf")])
def test_baseline_custom_requires_finite_number(value):
    from ai4bi_web_api.errors import AppError
    with pytest.raises(AppError):
        format_data({"baseline": "custom", "baseline_value": value})


@pytest.mark.parametrize("horizontal", [False, True])
def test_pdf_baseline_uses_server_value_and_orientation(tmp_path, monkeypatch, horizontal):
    from matplotlib.axes import Axes
    from pypdf import PdfReader
    snapshot, result = snapshot_result(); snapshot["format"] = "pdf"
    spec = snapshot["report"]["pages"]["main"]["visuals"]["table"]
    spec["visualization"]["visual_type"] = "bar_chart" if horizontal else "line_chart"
    spec["query"] = {"dimensions": [{"column_name": "place"}], "metrics": [{"metric_name": "amount"}]}
    rows = [{"place": "A", "amount": 2}, {"place": "B", "amount": 4}]
    settings = format_data({"baseline": "mean"}, rows)
    visual = {"status": "ready", "columns": list(rows[0]), "rows": rows, "chart_format": settings}
    if horizontal:
        visual["bar"] = {"version": 1, "orientation": "horizontal", "mode": "group", "grouped": False,
            "categories": [{"label": "A"}, {"label": "B"}], "series": [{"name": "amount", "metric_key": "amount", "points": [
                {"row_index": 0, "category_index": 0, "value": 2}, {"row_index": 1, "category_index": 1, "value": 4}]}]}
    result["visuals"] = {"table": visual}
    monkeypatch.setattr(exports, "run_query", lambda *_: copy.deepcopy(result))
    captured = []; method = "axvline" if horizontal else "axhline"; original = getattr(Axes, method)
    def capture(self, value, **kwargs):
        captured.append(value);return original(self, value, **kwargs)
    monkeypatch.setattr(Axes, method, capture)
    exports.export_snapshot(tmp_path, snapshot, tmp_path)
    assert captured == [3]
    assert "平均 3.00" in "\n".join(p.extract_text() for p in PdfReader(tmp_path / "export.pdf").pages)


def grouped_bar_data(rows, orientation="horizontal", mode="stack"):
    from ai4bi.query_spec import VisualQuerySpec, BlockRef, DimensionRef, MetricRef, VisualizationSpec, VisualType
    from ai4bi_web_api.bar_chart import bar_result
    from ai4bi_web_api.chart_format import chart_format
    query = VisualQuerySpec("bar", [BlockRef("b")], dimensions=[DimensionRef("b", "category"), DimensionRef("b", "group")],
                            metrics=[MetricRef("b", "value"), MetricRef("b", "other")])
    style = VisualizationSpec(VisualType.bar_chart, x_axis_label="Category", y_axis_label="Value",
                              extra={"orientation": orientation, "bar_mode": mode, "data_labels": True, "number_format": ".2f"})
    return bar_result(query, style, rows), chart_format(query, style, rows)


def test_grouped_bar_preserves_typed_sparse_cells_and_first_metric():
    rows = [{"category": category, "group": group, "value": value, "other": 999} for category, group, value in
            [(1, 1, 2), ("1", 1, 3), (1, "1", 4), (None, "1", None)]]
    before = copy.deepcopy(rows)
    bar, _ = grouped_bar_data(rows)
    assert [c["filter_value"] for c in bar["categories"]] == [1, "1", None]
    assert len({c["label"] for c in bar["categories"]}) == 3
    assert len(bar["series"]) == 2 and len({s["name"] for s in bar["series"]}) == 2
    assert [[p["value"] for p in s["points"]] for s in bar["series"]] == [[2, 3], [4, None]]
    assert all(s["metric_key"] == "value" for s in bar["series"]) and rows == before


@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
@pytest.mark.parametrize("mode", ["group", "stack", "overlay"])
def test_grouped_bar_pdf_geometry_matches_individual_values(tmp_path, monkeypatch, orientation, mode):
    from matplotlib.axes import Axes
    from pypdf import PdfReader
    rows = [{"category": category, "group": group, "value": value, "other": 999} for category, group, value in
            [("A", "G1", 2), ("B", "G1", -1), ("A", "G2", 3), ("B", "G2", None)]]
    bar, settings = grouped_bar_data(rows, orientation, mode)
    snapshot, result = snapshot_result(); snapshot["format"] = "pdf"
    spec = snapshot["report"]["pages"]["main"]["visuals"]["table"]
    spec["visualization"]["visual_type"] = "bar_chart"
    result["visuals"]["table"] = {"status": "ready", "columns": list(rows[0]), "rows": rows, "bar": bar, "chart_format": settings}
    monkeypatch.setattr(exports, "run_query", lambda *_: copy.deepcopy(result))
    captured = []
    original = Axes.bar_label
    def capture(self, container, **kwargs):
        captured.append([(p.get_x(), p.get_y(), p.get_width(), p.get_height()) for p in container])
        return original(self, container, **kwargs)
    monkeypatch.setattr(Axes, "bar_label", capture)
    exports.export_snapshot(tmp_path, snapshot, tmp_path)
    assert len(captured) == 2
    value_axis = 2 if orientation == "horizontal" else 3
    base_axis = 0 if orientation == "horizontal" else 1
    assert captured[0][0][value_axis] == 2 and captured[1][0][value_axis] == 3
    assert captured[1][0][base_axis] == (2 if mode == "stack" else 0)
    pages = PdfReader(tmp_path / "export.pdf").pages
    assert len(pages) == 2
    text = "\n".join(p.extract_text() for p in pages)
    assert all(v in text for v in ["Category", "Value", "G1", "G2", "999", "other"])


def format_data(extra, rows=None):
    from ai4bi.query_spec import VisualQuerySpec, BlockRef, DimensionRef, MetricRef, VisualizationSpec, VisualType
    from ai4bi_web_api.chart_format import chart_format
    query = VisualQuerySpec("format", [BlockRef("b")], dimensions=[DimensionRef("b", "city", alias="place")], metrics=[MetricRef("b", "amount")])
    style = VisualizationSpec(VisualType.bar_chart, x_axis_label="City", y_axis_label="Amount", extra=extra)
    return chart_format(query, style, rows or [{"place": "A", "amount": 1234.5}, {"place": "B", "amount": None}])


@pytest.mark.parametrize("extra", [{"y_min": 2, "y_max": 1}, {"y_scale": "log", "y_min": 0},
    {"y_min": float("inf")}, {"y_min": True}, {"y_scale": "other"}, {"legend_position": "other"}, {"number_format": "{value}"}])
def test_chart_format_rejects_invalid_settings(extra):
    from ai4bi_web_api.errors import AppError
    with pytest.raises(AppError):
        format_data(extra)


def test_chart_format_labels_bounds_and_missing_values():
    data = format_data({"y_scale": "log", "y_min": 1, "number_format": ",.2f", "legend_position": "left"})
    assert data["labels"]["amount"] == ["1,234.50", "—"]
    assert data["y_min"] == 1 and data["y_max"] is None and data["show_legend"]
    assert format_data({"number_format": ".1%"}, [{"place": "A", "amount": .125}])["labels"]["amount"] == ["12.5%"]


@pytest.mark.parametrize("kind", ["bar_chart", "line_chart"])
def test_cartesian_pdf_uses_shared_labels_axis_limits_and_legend(tmp_path, monkeypatch, kind):
    from matplotlib.axes import Axes
    from pypdf import PdfReader
    snapshot, result = snapshot_result(); snapshot["format"] = "pdf"
    spec = snapshot["report"]["pages"]["main"]["visuals"]["table"]
    spec["visualization"]["visual_type"] = kind
    spec["query"] = {"dimensions": [{"column_name": "place"}], "metrics": [{"metric_name": "amount"}]}
    rows = [{"place": "A", "amount": 12.5}, {"place": "B", "amount": 25}]
    data = format_data({"y_scale": "log", "y_min": 1, "y_max": 100, "number_format": ".2f", "data_labels": True, "legend_position": "bottom"}, rows)
    result["visuals"]["table"] = {"status": "ready", "columns": list(rows[0]), "rows": rows, "chart_format": data}
    monkeypatch.setattr(exports, "run_query", lambda *_: copy.deepcopy(result))
    captured = []
    original = Axes.set_ylim
    def capture(self, *args, **kwargs):
        answer = original(self, *args, **kwargs)
        if kwargs.get("bottom") == 1 and kwargs.get("top") == 100:
            captured.append((self.get_yscale(), answer))
        return answer
    monkeypatch.setattr(Axes, "set_ylim", capture)
    exports.export_snapshot(tmp_path, snapshot, tmp_path)
    assert ("log", (1, 100)) in captured
    text = "\n".join(page.extract_text() for page in PdfReader(tmp_path / "export.pdf").pages)
    assert all(value in text for value in ["12.50", "25.00", "City", "Amount", "amount"])


def pie_data(rows, hole=.4):
    from ai4bi.query_spec import VisualQuerySpec, BlockRef, DimensionRef, MetricRef, VisualizationSpec, VisualType
    from ai4bi_web_api.pie import pie_result
    query = VisualQuerySpec("pie", [BlockRef("b")], dimensions=[DimensionRef("b", "group"), DimensionRef("b", "tool")],
                            metrics=[MetricRef("b", "amount", alias="weight"), MetricRef("b", "other")])
    style = VisualizationSpec(VisualType.pie_chart, extra={"hole": hole, "show_percent": True, "data_labels": True, "legend_position": "bottom"})
    return pie_result(query, style, rows)


def test_pie_preserves_row_grain_typed_labels_first_metric_and_original_filter_values():
    rows = [{"group": group, "tool": tool, "weight": value, "other": 999} for group, tool, value in
            [(1, "A", 2), ("1", "A", 3), (None, "B", 0), ("null", "B", None)]]
    before = copy.deepcopy(rows)
    pie = pie_data(rows)
    assert pie["status"] == "ready" and pie["weight_total"] == 5 and pie["excluded_count"] == 1
    assert len(pie["slices"]) == len({s["label"] for s in pie["slices"]}) == 3
    assert [s["percent"] for s in pie["slices"]] == [40, 60, 0]
    assert [s["filter_value"] for s in pie["slices"]] == [1, "1", None]
    assert [s["value"] for s in pie["slices"]] == [2, 3, 0]
    assert rows == before


@pytest.mark.parametrize("values", [[0, 0], [1, -1], [None, float("inf")]])
def test_pie_unrepresentable_weights_are_explicit(values):
    pie = pie_data([{"group": str(i), "tool": "A", "weight": v, "other": 1} for i, v in enumerate(values)])
    assert pie["status"] == "unavailable" and pie["reason"] and pie["slices"] == []


@pytest.mark.parametrize("hole", [-.1, 1, float("nan")])
def test_pie_invalid_hole_is_rejected(hole):
    from ai4bi_web_api.errors import AppError
    with pytest.raises(AppError, match="圓環內徑"):
        pie_data([], hole)


@pytest.mark.parametrize("hole,negative", [(0, False), (.4, False), (.9, False), (.4, True)])
def test_pie_pdf_keeps_shape_weights_labels_and_complete_rows(tmp_path, monkeypatch, hole, negative):
    from matplotlib.axes import Axes
    from pypdf import PdfReader
    rows = [{"group": group, "tool": "A", "weight": value, "other": 999} for group, value in
            [("第一組", -2 if negative else 2), ("第二組", 3), ("空值組", None)]]
    pie = pie_data(rows, hole)
    snapshot, result = snapshot_result(); snapshot["format"] = "pdf"
    spec = snapshot["report"]["pages"]["main"]["visuals"]["table"]
    spec["visualization"] = {"title": "圓餅測試", "visual_type": "pie_chart"}
    result["visuals"] = {"table": {"status": "ready", "columns": list(rows[0]), "rows": rows, "pie": pie}}
    monkeypatch.setattr(exports, "run_query", lambda *_: copy.deepcopy(result))
    observed = []
    original = Axes.pie
    def capture(self, weights, **kwargs):
        observed.append((weights, kwargs));return original(self, weights, **kwargs)
    monkeypatch.setattr(Axes, "pie", capture)
    exports.export_snapshot(tmp_path, snapshot, tmp_path)
    pdf = PdfReader(tmp_path / "export.pdf")
    assert len(pdf.pages) == 2
    text = "\n".join(p.extract_text() for p in pdf.pages)
    assert "完整資料" in text and "空值組" in text and "999" in text
    if negative:
        assert observed == [] and "權重含負值" in text
    else:
        assert observed[0][0] == [2, 3]
        assert observed[0][1]["wedgeprops"]["width"] == pytest.approx(1-hole)
        assert "40.00%" in text and "60.00%" in text


@pytest.mark.parametrize("single", [False, True])
def test_scatter_coordinates_and_pdf_use_metrics_not_category(tmp_path, monkeypatch, single):
    from ai4bi.query_spec import VisualQuerySpec, BlockRef, DimensionRef, MetricRef, VisualizationSpec, VisualType
    from ai4bi_web_api.scatter import scatter_result
    from matplotlib.axes import Axes
    from pypdf import PdfReader
    query = VisualQuerySpec("scatter", [BlockRef("b")], dimensions=[DimensionRef("b", "group")],
                            metrics=[MetricRef("b", "x")] + ([] if single else [MetricRef("b", "y")]))
    style = VisualizationSpec(VisualType.scatter, extra={"size_col": "size"})
    rows = [{"group": group, "x": x, "y": y, "size": size} for group, x, y, size in
            [("A", 100, 2, 100), ("B", 50, -4, 25), ("A", None, 8, 0), ("B", 75, 9, None)]]
    data = scatter_result(query, style, rows)
    assert [p["x"] for p in data["points"]] == [100, 50, 75]
    assert [p["y"] for p in data["points"]] == ([0, 1, 3] if single else [2, -4, 9])
    assert data["excluded_count"] == 1
    assert [p["group"] for p in data["points"]] == ["A", "B", "B"]
    snapshot, result = snapshot_result()
    snapshot["format"] = "pdf"
    spec = snapshot["report"]["pages"]["main"]["visuals"]["table"]
    spec["visualization"] = {"title": "散點測試", "visual_type": "scatter"}
    result["visuals"] = {"table": {"status": "ready", "columns": list(rows[0]), "rows": rows, "scatter": data}}
    monkeypatch.setattr(exports, "run_query", lambda *_: copy.deepcopy(result))
    observed = []
    original = Axes.scatter
    def capture(self, x, y, **kwargs):
        observed.append((x, y, kwargs["s"]))
        return original(self, x, y, **kwargs)
    monkeypatch.setattr(Axes, "scatter", capture)
    exports.export_snapshot(tmp_path, snapshot, tmp_path)
    assert observed == [([100], [0 if single else 2], [1600]), ([50, 75], [1, 3] if single else [-4, 9], [400, 49])]
    pdf = PdfReader(tmp_path / "export.pdf")
    assert len(pdf.pages) == 2
    assert "散點 3 筆" in pdf.pages[0].extract_text() and "排除 1" in pdf.pages[0].extract_text()
    assert "完整資料" in pdf.pages[1].extract_text()


@pytest.mark.parametrize("size", [-1, float("inf"), "10", True])
def test_scatter_rejects_invalid_marker_area(size):
    from ai4bi.query_spec import VisualQuerySpec, BlockRef, MetricRef, VisualizationSpec, VisualType
    from ai4bi_web_api.scatter import scatter_result
    from ai4bi_web_api.errors import AppError
    query = VisualQuerySpec("scatter", [BlockRef("b")], metrics=[MetricRef("b", "x")])
    style = VisualizationSpec(VisualType.scatter, extra={"size_col": "size"})
    with pytest.raises(AppError, match="非負有限"):
        scatter_result(query, style, [{"x": 1, "size": size}])


@pytest.mark.parametrize("method", ["ols", "lowess"])
def test_scatter_pdf_uses_server_curve_and_preserves_fit_summary(tmp_path, monkeypatch, method):
    from ai4bi_web_api.scatter import fit_trendlines
    from matplotlib.axes import Axes
    from pypdf import PdfReader
    points = [{"row_index": x, "x": x, "y": 2*x+1, "size": None, "group": "A"} for x in range(5)]
    lines = fit_trendlines(points, method)
    snapshot, result = snapshot_result(); snapshot["format"] = "pdf"
    spec = snapshot["report"]["pages"]["main"]["visuals"]["table"]
    spec["visualization"] = {"title": "趨勢線測試", "visual_type": "scatter"}
    result["visuals"] = {"table": {"status": "ready", "columns": ["x", "y"], "rows": points,
        "scatter": {"version": 1, "x_key": "x", "y_key": "y", "group_key": "group", "size_key": None,
                    "points": points, "excluded_count": 0, "trendline": method, "trendlines": lines}}}
    monkeypatch.setattr(exports, "run_query", lambda *_: copy.deepcopy(result))
    observed = []
    original = Axes.plot
    def capture(self, x, y, **kwargs):
        observed.append((x, y));return original(self, x, y, **kwargs)
    monkeypatch.setattr(Axes, "plot", capture)
    exports.export_snapshot(tmp_path, snapshot, tmp_path)
    assert observed == [(lines[0]["x"], lines[0]["y"])]
    text = "\n".join(page.extract_text() for page in PdfReader(tmp_path / "export.pdf").pages)
    assert method.upper() in text and "趨勢擬合結果" in text and "擬合完成" in text


def test_geographic_topology_decodes_delta_reverse_and_holes():
    from ai4bi_web_api.geographic_pdf import land_rings, project
    import numpy as np
    topology = {"transform": {"scale": [2, 3], "translate": [10, 20]},
        "arcs": [[[0, 0], [1, 0], [0, 1]], [[0, 0], [0, 1], [1, 0]]],
        "objects": {"land": {"type": "Polygon", "arcs": [[0, -2], [-1, 1]]}}}
    rings = land_rings(topology)[0]
    assert rings[0].tolist() == [[10, 20], [12, 20], [12, 23], [10, 23], [10, 20]]
    # Closed rings may begin at different vertices; this arc order starts at NE.
    assert rings[1].tolist() == [[12, 23], [12, 20], [10, 20], [10, 23], [12, 23]]
    np.testing.assert_allclose(project([[0, 0], [180, 0]], True), [[0, 0], [np.pi * .8707, 0]])
    np.testing.assert_allclose(project([[0, 45]])[0], [0, np.log(1 + np.sqrt(2))])
    assert np.isfinite(project([[180, 90], [-180, -90]])).all()


def test_geographic_dateline_keeps_islands_at_edges_and_closes_polar_land():
    import numpy as np
    from ai4bi_web_api.geographic_pdf import split_dateline
    ring = np.array([[170., -10], [-170, -10], [-170, 10], [170, 10], [170, -10]])
    parts = split_dateline(ring)
    assert len(parts) == 2
    assert sorted((p[:, 0].min(), p[:, 0].max()) for p in parts) == [(-180, -170), (170, 180)]
    for part in parts:
        assert np.array_equal(part[0], part[-1])
        assert np.max(abs(np.diff(part[:, 0]))) <= 10
    polar = np.array([[-180., -80], [-90, -75], [0, -80], [90, -75], [-180, -80]])
    parts = split_dateline(polar)
    assert min(p[:, 1].min() for p in parts) == -90
    assert all(p[:, 1].max() <= -75 for p in parts)


@pytest.mark.parametrize("view", ["auto", "taiwan", "world", "unmapped"])
def test_geographic_pdf_keeps_symbols_and_full_unknown_rows(tmp_path, monkeypatch, view):
    from matplotlib.axes import Axes
    from pypdf import PdfReader
    from matplotlib.backends.backend_pdf import PdfPages
    import numpy as np
    snapshot, result = snapshot_result()
    snapshot["format"] = "pdf"
    spec = snapshot["report"]["pages"]["main"]["visuals"]["table"]
    spec["visualization"] = {"title": "地理分布測試", "visual_type": "map", "extra": {"map_view": view}}
    spec["query"] = {"metrics": [{"metric_name": "amount"}], "dimensions": [{"column_name": "city"}]}
    points = [] if view == "unmapped" else [
        {"row_index": i, "latitude": lat, "longitude": lon}
        for i, (lat, lon) in enumerate([(25.03, 121.56), (24.15, 120.68), (22.99, 120.21), (22.63, 120.30)])]
    rows = [{"city": city, "amount": amount} for city, amount in zip(
        ["台北", "台中", "台南", "高雄", "未知地點"], [100, -25, 0, None, 888])]
    result["visuals"] = {"table": {"status": "ready", "columns": ["city", "amount"], "rows": rows,
        "truncated": False, "geo": {"version": 1, "location_field": {"key": "city"},
        "points": points, "mapped_count": len(points), "unmapped_count": 5-len(points)}}}
    monkeypatch.setattr(exports, "run_query", lambda *_: copy.deepcopy(result))
    observations = []
    original = Axes.scatter
    def observed(self, x, y, **kwargs):
        observations.append((list(x), list(y), kwargs))
        return original(self, x, y, **kwargs)
    monkeypatch.setattr(Axes, "scatter", observed)
    save_page = PdfPages.savefig
    def captured(self, figure, **kwargs):
        if view in ("taiwan", "world") and not (tmp_path / "map.png").exists():
            figure.savefig(tmp_path / "map.png", dpi=110)
        return save_page(self, figure, **kwargs)
    monkeypatch.setattr(PdfPages, "savefig", captured)
    exports.export_snapshot(tmp_path, snapshot, tmp_path)
    reader = PdfReader(tmp_path / "export.pdf")
    assert len(reader.pages) == 2
    text = "\n".join(p.extract_text() for p in reader.pages)
    assert "未知地點" in text and "888" in text and "-25" in text and "fixed-export-sna" in text
    assert f"已定位 {len(points)}" in text and f"未定位 {5-len(points)}" in text
    if points:
        assert observations[0][2]["s"] == [1600, 400, 49, 49]
        assert observations[0][2]["c"] == ["#2874a6", "#b34a57", "#2874a6", "#8395a1"]
        assert np.isfinite(observations[0][0]).all()
    else:
        assert observations == [] and "沒有可定位地點" in text


def test_geographic_pdf_refuses_missing_packaged_map(tmp_path, monkeypatch):
    from ai4bi_web_api import geographic_pdf
    from ai4bi_web_api.errors import AppError
    monkeypatch.setattr(geographic_pdf, "__file__", str(tmp_path / "geographic_pdf.py"))
    with pytest.raises(AppError, match="底圖缺失"):
        geographic_pdf.geographic_page(None, {}, {"geo": {"version": 1}}, "title", "footer")


def pivot_snapshot_result():
    snapshot, result = snapshot_result()
    snapshot["report"]["pages"]["main"]["visuals"]["table"]["visualization"]["visual_type"] = "pivot"
    snapshot["report"]["pages"]["main"]["visuals"]["table"]["visualization"]["title"] = "樞紐測試"
    metric = {"key": "average", "metric_name": "average", "block_id": "b"}
    frame = lambda rows: {"rows": rows, "truncated": False}
    # Distinct types, a spreadsheet-like string and a category named like a total.
    values = [None, "null", True, 1, "=1+1", "列總計"]
    visual = {"status": "ready", "columns": ["row", "column", "average"], "truncated": False,
              "rows": [{"row": "A", "column": value, "average": i + .5} for i, value in enumerate(values)]}
    visual["rows"][0]["average"] = None
    visual["pivot"] = {"version": 1, "totals_scope": "filtered_population", "metrics": [metric],
        "row_field": {"key": "row", "column_name": "row", "block_id": "b"},
        "column_field": {"key": "column", "column_name": "column", "block_id": "b"},
        "row_totals": frame([{"row": "A", "average": 7.25}, {"row": "=2+2", "average": 8.75}]),
        "column_totals": frame([{"column": value, "average": i + .75} for i, value in enumerate(values)]),
        "grand_total": frame([{"average": 8.125}]), "truncated": False}
    result["visuals"] = {"table": visual}
    return snapshot, result


def test_pivot_matrix_sections_keep_typed_axes_core_totals_and_missing_values():
    from ai4bi_web_api.pivot import matrix_tables
    _, result = pivot_snapshot_result()
    visual = result["visuals"]["table"]
    before = copy.deepcopy(visual)
    tables = list(matrix_tables(visual))
    assert len(tables) == 2
    assert [len(t["columns"]) for t in tables] == [6, 4]
    assert [t["pivot_part"]["column_values"] for t in tables] == [[None, "null", True, 1], ["=1+1", "列總計"]]
    for table in tables:
        assert table["rows"][0]["列總計"] == 7.25
        assert table["rows"][1]["列總計"] == 8.75
        assert table["rows"][-1]["列總計"] == 8.125
        assert list(table["rows"][1].values())[1:-1] == ["—"] * (len(table["columns"]) - 2)
    assert list(tables[0]["rows"][0].values())[1] == "（空值）"
    assert visual == before
    visual["rows"] = []
    visual["pivot"]["row_totals"]["rows"] = []
    visual["pivot"]["column_totals"]["rows"] = []
    empty = list(matrix_tables(visual))
    assert empty[0]["columns"] == ["列維度：row", "列總計"]
    assert empty[0]["rows"] == [{"列維度：row": "欄總計／總計", "列總計": 8.125}]


@pytest.mark.parametrize("format", ["csv", "xlsx", "pdf"])
def test_pivot_document_exports_keep_matrix_parts_and_independent_totals(tmp_path, monkeypatch, format):
    import csv, io, json, zipfile
    snapshot, result = pivot_snapshot_result()
    snapshot["format"] = format
    monkeypatch.setattr(exports, "run_query", lambda *_: copy.deepcopy(result))
    exports.export_snapshot(tmp_path, snapshot, tmp_path)
    if format == "csv":
        with zipfile.ZipFile(tmp_path / "export.csv.zip") as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert len(manifest["tables"]) == 2
            for entry in manifest["tables"]:
                rows = list(csv.reader(io.StringIO(archive.read(entry["file"]).decode("utf-8-sig"))))
                assert rows[-1][-1] == "8.125"
                assert rows[1][-1] == "7.25" and rows[2][-1] == "8.75"
                assert entry["pivot_part"]["metric"]["key"] == "average"
            assert json.loads(archive.read("analysis.json"))["analysis"] == result
    elif format == "xlsx":
        import openpyxl
        book = openpyxl.load_workbook(tmp_path / "export.xlsx")
        assert len(book.sheetnames) == 3
        for sheet in list(book)[1:]:
            assert sheet.cell(1, 1).value.startswith("average |")
            assert sheet.cell(7, sheet.max_column).value == 8.125
            assert sheet.cell(5, sheet.max_column).value == 7.25
            assert all(cell.data_type != "f" for row in sheet for cell in row)
            assert sheet.freeze_panes == "B5"
    else:
        from pypdf import PdfReader
        reader = PdfReader(tmp_path / "export.pdf")
        assert len(reader.pages) == 2
        for page in reader.pages:
            text = page.extract_text()
            assert "average" in text and "8.125" in text and "7.25" in text and "8.75" in text
            assert "fixed-export-sna" in text
        text = "\n".join(page.extract_text() for page in reader.pages)
        assert "C6" in text and "空值" in text and "—" in text


def test_pivot_export_separates_metrics_and_supports_single_axis():
    from ai4bi_web_api.pivot import matrix_tables
    _, result = pivot_snapshot_result()
    visual = result["visuals"]["table"]
    visual["pivot"]["metrics"].append({"key": "distinct", "metric_name": "distinct", "block_id": "b"})
    for rows in [visual["rows"], *[visual["pivot"][name]["rows"] for name in ("row_totals", "column_totals", "grand_total")]]:
        for row in rows:
            row["distinct"] = 2
    parts = list(matrix_tables(visual))
    assert [part["pivot_part"]["metric"]["key"] for part in parts] == ["average", "average", "distinct", "distinct"]
    assert parts[2]["rows"][-1]["列總計"] == 2
    visual["rows"] = copy.deepcopy(visual["pivot"]["row_totals"]["rows"])
    visual["pivot"]["column_field"] = None
    visual["pivot"]["column_totals"] = None
    parts = list(matrix_tables(visual))
    assert len(parts) == 2
    assert parts[0]["columns"] == ["列維度：row", "指標值", "列總計"]
    assert parts[0]["rows"][-1]["指標值"] == 8.125
    assert parts[1]["rows"][-1]["指標值"] == 2


@pytest.mark.parametrize("format", ["csv", "xlsx", "pdf"])
def test_histogram_exports_use_the_same_frequency_table(tmp_path, monkeypatch, format):
    import pandas as pd
    from ai4bi.query_spec import VisualQuerySpec, BlockRef, DimensionRef, VisualizationSpec, VisualType
    from ai4bi_web_api.histogram import histogram_result
    from ai4bi_web_api.core import clean
    query = VisualQuerySpec("hist", [BlockRef("b")], dimensions=[DimensionRef("b", "amount")])
    style = VisualizationSpec(VisualType.bar_chart, extra={"chart_mode": "histogram", "bins": 2})
    frame, histogram = histogram_result(query, style, pd.DataFrame({"amount": [0., 0., 1., 2., 3., 4., None]}))
    snapshot, result = snapshot_result()
    snapshot["format"] = format
    spec = snapshot["report"]["pages"]["main"]["visuals"]["table"]
    spec["visualization"] = {"title": "分布測試", "visual_type": "bar_chart", "extra": style.extra}
    result["visuals"]["table"] = {"status": "ready", **clean(frame), "histogram": histogram, "truncated": False}
    monkeypatch.setattr(exports, "run_query", lambda *_: copy.deepcopy(result))
    heights = []
    if format == "pdf":
        from matplotlib.axes import Axes
        original = Axes.bar
        def observed(self, x, height, *args, **kwargs):
            heights.extend(height)
            return original(self, x, height, *args, **kwargs)
        monkeypatch.setattr(Axes, "bar", observed)
    exports.export_snapshot(tmp_path, snapshot, tmp_path)
    if format == "pdf":
        from pypdf import PdfReader
        assert heights == [3, 3]
        text = PdfReader(tmp_path / "export.pdf").pages[0].extract_text()
        assert "有效 6" in text and "排除 1" in text
    elif format == "xlsx":
        import openpyxl
        sheet = openpyxl.load_workbook(tmp_path / "export.xlsx").worksheets[1]
        assert sheet.cell(2, 4).value == sheet.cell(3, 4).value == 3
    else:
        import json, zipfile
        with zipfile.ZipFile(tmp_path / "export.csv.zip") as archive:
            recovered = json.loads(archive.read("analysis.json"))["analysis"]["visuals"]["table"]
            assert recovered["histogram"]["valid_count"] == 6
            assert [row["count"] for row in recovered["rows"]] == [3, 3]


def test_csv_bundle_preserves_tables_unicode_types_and_protects_spreadsheet_text(tmp_path,monkeypatch):
    import csv,io,json,zipfile
    snapshot,result=snapshot_result()
    snapshot["format"]="csv"
    snapshot["report"]["pages"]["main"]["visuals"]["table"]["visualization"]["title"]="../../same"
    special=["=1+1"," @SUM(1)","a,b\n中文",None,"",-42,True,"'literal"]
    columns=result["visuals"]["table"]["columns"]
    result["visuals"]["table"]["rows"][0]=dict(zip(columns,special))
    snapshot["report"]["pages"]["main"]["visuals"]["empty"]=copy.deepcopy(snapshot["report"]["pages"]["main"]["visuals"]["table"])
    result["visuals"]["empty"]={"status":"ready","columns":["=header"],"rows":[],"truncated":False}
    monkeypatch.setattr(exports,"run_query",lambda *_:copy.deepcopy(result))
    returned=exports.export_snapshot(tmp_path,snapshot,tmp_path)
    assert returned["filename"]=="report.csv.zip" and returned["format"]=="csv"
    with zipfile.ZipFile(tmp_path/"export.csv.zip") as archive:
        assert set(archive.namelist())=={"tables/001.csv","tables/002.csv","manifest.json","analysis.json"}
        assert archive.testzip() is None
        manifest=json.loads(archive.read("manifest.json"))
        raw=archive.read("tables/001.csv")
        assert raw.startswith(b"\xef\xbb\xbf")
        rows=list(csv.reader(io.StringIO(raw.decode("utf-8-sig"),newline="")))
        assert rows[0]==columns and len(rows)==65
        assert rows[1]==["'=1+1","' @SUM(1)","a,b\n中文","","","-42","True","'literal"]
        assert manifest["tables"][0]["protected_cells"]==[[1,0],[1,1]]
        assert manifest["tables"][1]["protected_cells"]==[[0,0]]
        assert list(csv.reader(io.StringIO(archive.read("tables/002.csv").decode("utf-8-sig"))))==[["'=header"]]
        companion=json.loads(archive.read("analysis.json"))
        assert list(companion["analysis"]["visuals"]["table"]["rows"][0].values())==special
        assert rows[-1][-1]=="末列中文 END_MARKER"


def test_csv_bundle_refuses_partial_or_truncated_query(tmp_path,monkeypatch):
    import pytest
    from ai4bi_web_api.errors import AppError
    snapshot,result=snapshot_result()
    snapshot["format"]="csv"
    for field,value,code in [("truncated",True,"EXPORT_LIMIT"),("status","error","EXPORT_QUERY_FAILED")]:
        changed=copy.deepcopy(result)
        changed["visuals"]["table"][field]=value
        monkeypatch.setattr(exports,"run_query",lambda *_:changed)
        with pytest.raises(AppError) as caught:exports.export_snapshot(tmp_path,snapshot,tmp_path)
        assert caught.value.code==code
        assert not (tmp_path/"export.csv.zip").exists()


def snapshot_result():
    columns = [f"field_{i}" for i in range(8)]
    rows = [{column: f"R{row:03d}C{col}" for col, column in enumerate(columns)} for row in range(64)]
    rows[-1][columns[-1]] = "末列中文 END_MARKER"
    spec = {"visualization": {"title": "完整資料表", "visual_type": "table"},
            "query": {"dimensions": [], "metrics": []}}
    snapshot = {"revision": 7, "format": "pdf", "report": {"pages": {"main": {"visuals": {"table": spec}}}}}
    result = {"snapshot_id": "fixed-export-snapshot", "exploration_page_id":None, "visuals": {
        "table": {"status": "ready", "rows": rows, "columns": columns, "truncated": False}}}
    return snapshot, result


@pytest.mark.parametrize("kind", ["bar_chart", "line_chart"])
def test_pdf_uses_executed_drill_query_without_mutating_saved_spec(tmp_path, monkeypatch, kind):
    from pypdf import PdfReader
    snapshot, result = snapshot_result()
    snapshot["format"] = "pdf"
    spec = snapshot["report"]["pages"]["main"]["visuals"]["table"]
    spec["visualization"]["visual_type"] = kind
    spec["query"] = {"dimensions": [{"column_name": "region", "alias": "saved_region"}],
                     "metrics": [{"metric_name": "amount"}]}
    before = copy.deepcopy(snapshot)
    result["visuals"]["table"] = {"status": "ready", "columns": ["active_city", "amount"],
        "rows": [{"active_city": "Taipei", "amount": 10}, {"active_city": "Tainan", "amount": 20}],
        "query": {"dimensions": [{"column_name": "city", "alias": "active_city"}],
                  "metrics": [{"metric_name": "amount"}]}}
    monkeypatch.setattr(exports, "run_query", lambda *_: copy.deepcopy(result))
    exports.export_snapshot(tmp_path, snapshot, tmp_path)
    text = "\n".join(p.extract_text() for p in PdfReader(tmp_path / "export.pdf").pages)
    assert "Taipei" in text and "Tainan" in text and "Revision 7" in text
    assert "saved_region" not in text and snapshot == before


def test_pdf_paginates_all_rows_and_columns(tmp_path, monkeypatch):
    from pypdf import PdfReader
    snapshot, result = snapshot_result()
    result["visuals"]["table"]["rows"][0]["field_0"] = "LONGWORD " * 80 + "LAST_WORD"
    result["visuals"]["table"]["rows"][1]["field_0"] = "$literal$"
    snapshot["report"]["pages"]["main"]["visuals"]["empty_kpi"] = {
        "visualization": {"title": "空值指標", "visual_type": "kpi_card"},
        "query": {"dimensions": [], "metrics": [{"metric_name": "amount"}]}}
    result["visuals"]["empty_kpi"] = {"status": "ready", "columns": ["amount"], "rows": [{"amount": None}]}
    snapshot["report"]["pages"]["main"]["visuals"]["grouped_kpi"] = {
        "visualization": {"title": "分組指標", "visual_type": "kpi_card"},
        "query": {"dimensions": [], "metrics": [{"metric_name": "amount"}]}}
    result["visuals"]["grouped_kpi"] = {"status": "ready", "columns": ["amount"], "rows": [{"amount": 100}, {"amount": 99999}]}
    snapshot["report"]["pages"]["main"]["visuals"]["multi_bar"] = {
        "visualization": {"title": "多指標", "visual_type": "bar_chart"},
        "query": {"dimensions": [{"column_name": "group"}], "metrics": [{"metric_name": "good"}, {"metric_name": "bad"}]}}
    result["visuals"]["multi_bar"] = {"status": "ready", "columns": ["group", "good", "bad"], "rows": [{"group": "A", "good": 9, "bad": 1}]}
    monkeypatch.setattr(exports, "run_query", lambda *_: copy.deepcopy(result))
    exports.export_snapshot(tmp_path, snapshot, tmp_path)
    reader = PdfReader(tmp_path / "export.pdf")
    assert len(reader.pages) > 2
    text = "\n".join(page.extract_text() for page in reader.pages)
    for row in result["visuals"]["table"]["rows"]:
        for value in row.values():
            if not value.startswith("LONGWORD "):
                assert value in text
    assert text.count("LONGWORD") == 80
    assert "LAST_WORD" in text
    assert "空值指標" in text and "—" in text
    assert "99999" in text
    assert "good" in text and "bad" in text
    assert "Revision 7" in text
    assert all("fixed-export-sna" in page.extract_text() for page in reader.pages)


def test_excel_titles_are_case_insensitive_and_strings_are_not_formulas(tmp_path, monkeypatch):
    import openpyxl
    snapshot, result = snapshot_result()
    snapshot["format"] = "xlsx"
    first = snapshot["report"]["pages"]["main"]["visuals"]["table"]
    first["visualization"]["title"] = "'Data'"
    second = copy.deepcopy(first)
    second["visualization"]["title"] = "data"
    snapshot["report"]["pages"]["main"]["visuals"]["second"] = second
    result["visuals"]["table"]["rows"][0]["field_0"] = "=1+1"
    result["visuals"]["second"] = copy.deepcopy(result["visuals"]["table"])
    monkeypatch.setattr(exports, "run_query", lambda *_: copy.deepcopy(result))
    exports.export_snapshot(tmp_path, snapshot, tmp_path)
    book = openpyxl.load_workbook(tmp_path / "export.xlsx")
    assert book.sheetnames == ["來源與版本", "Data", "data_2"]
    assert book["Data"]["A2"].value == "=1+1"
    assert book["Data"]["A2"].data_type == "s"
    assert book["data_2"]["H65"].value == "末列中文 END_MARKER"
