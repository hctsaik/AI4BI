"""Real-core calculation and immutable snapshot checks for report-local extensions."""
import copy
import json

import pytest
from ai4bi.planning.join_planner import QueryPlanningError

from ai4bi_web_api.core import template, validate_report, run_query, run_assistant
from ai4bi_web_api.jobs import make_snapshot
from ai4bi_web_api.storage import Store
from ai4bi_web_api.report_extensions import extensions


def comparison_fixture(rows=None, *, dtype="date", extra=None):
    from ai4bi.report.models import ExecutableReportSpec
    body, contracts = template("fab")
    # The pinned core returns cached block instances. Fixtures must own their
    # records, column types and policies before changing any of them.
    contracts = copy.deepcopy(contracts)
    block = contracts["fab_process_move"]
    if rows is not None:
        original = block.data_source.records[0]
        block.data_source.records = [{**original, "move_id": f"M{i}", "event_date": day, "move_count": value,
                                      "priority": priority} for i, (day, value, priority) in enumerate(rows)]
    next(c for c in block.columns if c.name == "event_date").data_type = dtype
    visual = body["pages"]["main"]["visuals"]["kpi_moves"]
    visual["query"]["metrics"][0]["alias"] = "moves"
    visual["visualization"]["extra"].update(compare_period="week", compare_date_column="event_date")
    visual["visualization"]["extra"].update(extra or {})
    spec = ExecutableReportSpec.from_dict(body).pages["main"].visuals["kpi_moves"]
    return body, contracts, spec


@pytest.mark.parametrize("grain,expected", [
    ("day", {"2024-02-29": 2, "2024-03-01": 3, "2024-04-01": 5}),
    ("week", {"2024-02-26": 5, "2024-04-01": 5}),
    ("month", {"2024-02-01": 2, "2024-03-01": 3, "2024-04-01": 5}),
    ("quarter", {"2024-01-01": 5, "2024-04-01": 5}),
    ("year", {"2024-01-01": 10}),
    ("weekday", {"Thursday": 2, "Friday": 3, "Monday": 5}),
    ("hour", {"22": 2, "0": 8}),
])
def test_date_dimensions_utc_calendar_buckets_preserve_rls(grain, expected):
    import pandas as pd
    from ai4bi.query_spec import DimensionRef
    from ai4bi_web_api.comparison import ComparisonExecutor
    body, contracts, spec = comparison_fixture([
        ("2024-03-01T00:30:00+02:00", 2, "Hot"),
        ("2024-03-01T02:00:00+02:00", 3, "Hot"),
        ("2024-04-01T00:00:00Z", 5, "Hot"),
        (None, 7, "Hot"),
        ("2024-04-01T00:00:00Z", 999, "Normal"),
    ], dtype="timestamp")
    contracts["fab_process_move"].policy.row_filter_column = "priority"
    contracts["fab_process_move"].policy.row_filter_identity_key = "priority"
    spec.query.dimensions = [DimensionRef("fab_process_move", "event_date", "period", truncate_date_to=grain)]
    executor = ComparisonExecutor(extra_contracts=contracts, identity={"priority": "Hot"})
    frame, metadata = executor.run_with_metadata(spec.query)
    actual = {}
    for row in frame.to_dict("records"):
        period = row["period"]
        key = None if pd.isna(period) else str(period) if grain == "weekday" else str(int(period)) if grain == "hour" else period.date().isoformat()
        actual[key] = row["moves"]
    assert actual == {**expected, None: 7}
    assert metadata.dimensions_used == [f"period (DATE_TRUNC {grain})"]


@pytest.mark.parametrize("grain,column", [("minute", "event_date"), ("month'); SELECT 1; --", "event_date"),
    (1, "event_date"), ("month", "move_count"), ("month", "missing")])
def test_date_dimensions_reject_invalid_grain_and_field(grain, column):
    from ai4bi_web_api.errors import AppError
    body, contracts, _ = comparison_fixture(extra={"compare_period": ""})
    visual = body["pages"]["main"]["visuals"]["kpi_moves"]
    visual["query"]["dimensions"] = [{"block_id": "fab_process_move", "column_name": column,
                                      "alias": "period", "truncate_date_to": grain}]
    with pytest.raises(AppError) as caught:
        validate_report(body, contracts)
    assert caught.value.code == "INVALID_DATE_GRAIN"


def test_date_dimension_export_replays_accepted_months(tmp_path):
    import pandas as pd
    from openpyxl import load_workbook
    from ai4bi_web_api.exports import export_snapshot
    body, contracts, _ = comparison_fixture([
        ("2024-02-29", 5, "Hot"), ("2024-03-01", 7, "Hot"),
    ], extra={"compare_period": ""})
    page = body["pages"]["main"]
    visual = page["visuals"]["kpi_moves"]
    visual["query"]["dimensions"] = [{"block_id": "fab_process_move", "column_name": "event_date",
                                      "alias": "period", "truncate_date_to": "month"}]
    page["visuals"], page["visual_order"] = {"kpi_moves": visual}, ["kpi_moves"]
    store = Store(tmp_path / "data")
    try:
        ids = store.create_workspace("Date buckets", body, "date-buckets", "fab")
        for block in contracts.values():
            store.publish_dataset(ids["workspace_id"], block.model_dump(mode="json"), pd.DataFrame(block.data_source.records))
        snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 1, {"visual_ids": ["kpi_moves"]})
        block = contracts["fab_process_move"]
        block.data_source.records[0]["move_count"] = 999
        store.publish_dataset(ids["workspace_id"], block.model_dump(mode="json"), pd.DataFrame(block.data_source.records))
        export_snapshot(store.root, {**snapshot, "format": "xlsx"}, tmp_path)
        workbook = load_workbook(tmp_path / "export.xlsx", data_only=True)
        try:
            source_rows = list(workbook.worksheets[0].values)
            source = dict(zip(source_rows[0], source_rows[1]))
            assert source["execution_contract"] == snapshot["execution_contract"]
            table = next(list(sheet.values) for sheet in workbook if tuple(next(sheet.values))[:2] == ("period", "moves"))
            assert {str(row[0])[:10]: row[1] for row in table[1:3]} == {"2024-02-01": 5, "2024-03-01": 7}
        finally:
            workbook.close()
        export_snapshot(store.root, {**snapshot, "format": "json"}, tmp_path)
        assert json.loads((tmp_path / "export.json").read_text(encoding="utf-8"))["analysis"]["execution_contract"] == snapshot["execution_contract"]
        import zipfile
        export_snapshot(store.root, {**snapshot, "format": "csv"}, tmp_path)
        with zipfile.ZipFile(tmp_path / "export.csv.zip") as bundle:
            assert json.loads(bundle.read("manifest.json"))["execution_contract"] == snapshot["execution_contract"]
            assert json.loads(bundle.read("analysis.json"))["analysis"]["execution_contract"] == snapshot["execution_contract"]
        from pypdf import PdfReader
        export_snapshot(store.root, {**snapshot, "format": "pdf"}, tmp_path)
        assert PdfReader(tmp_path / "export.pdf").metadata.subject == "Execution contract: " + snapshot["execution_contract"]
    finally:
        store.close()


def test_sparkline_daily_utc_scope_and_comparison_window():
    from ai4bi_web_api.comparison import compare_query, ComparisonExecutor
    from ai4bi_web_api.sparkline import sparkline_result
    from ai4bi_web_api.filters import ScopedExecutor
    rows = [("2024-02-23T12:00:00Z", 5, "Hot"), ("2024-02-24T12:00:00Z", 7, "Hot"),
            ("2024-03-01T23:00:00Z", 11, "Hot"), ("2024-03-02T00:30:00+02:00", 13, "Hot"),
            ("2025-01-01T00:00:00Z", 999, "Normal")]
    body, contracts, spec = comparison_fixture(rows, dtype="timestamp")
    spec.visualization.show_sparkline = True
    contracts["fab_process_move"].policy.row_filter_column = "priority"
    contracts["fab_process_move"].policy.row_filter_identity_key = "priority"
    core = ComparisonExecutor(extra_contracts=contracts, identity={"priority": "Hot"})
    executor = ScopedExecutor(core, body, [])
    frame, _, comparison = compare_query(executor, spec.query, spec.visualization, contracts,
        active_filters={}, page_id="main", visual_id="kpi_moves")
    data = sparkline_result(executor, spec.query, spec.visualization, contracts,
        active_filters={}, page_id="main", visual_id="kpi_moves", comparison=comparison)
    assert frame.iloc[0, 0] == 31
    assert data["points"] == [{"date": "2024-02-24", "value": 7}, {"date": "2024-03-01", "value": 24}]
    assert data["status"] == "ready" and not data["truncated"]
    assert core._daily.get() is None and core._comparison.get() is None


def test_sparkline_limits_recent_dates_without_changing_headline():
    from datetime import date, timedelta
    from ai4bi_web_api.sparkline import sparkline_result
    from ai4bi_web_api.report_extensions import report_executor
    rows = [((date(2020, 1, 1)+timedelta(days=i)).isoformat(), i, "Hot") for i in range(400)]
    body, contracts, spec = comparison_fixture(rows, extra={"compare_period": "", "sparkline_date_column": "event_date"})
    spec.visualization.show_sparkline = True
    executor, enriched = report_executor(body, contracts)
    data = sparkline_result(executor, spec.query, spec.visualization, enriched,
        active_filters={}, page_id="main", visual_id="kpi_moves")
    assert data["truncated"] and len(data["points"]) == 365
    assert data["points"][0]["value"] == 35 and data["points"][-1]["value"] == 399
    assert executor.run(spec.query).iloc[0, 0] == sum(range(400))


def test_sparkline_daily_average_is_not_used_as_headline_total():
    from ai4bi.query_spec import AggFunction
    from ai4bi_web_api.sparkline import sparkline_result
    from ai4bi_web_api.report_extensions import report_executor
    body, contracts, spec = comparison_fixture([("2024-01-01", 0, "Hot"), ("2024-01-01", 100, "Hot"),
        ("2024-01-03", 100, "Hot")], extra={"compare_period": "", "sparkline_date_column": "event_date"})
    spec.visualization.show_sparkline = True
    spec.query.metrics[0].agg_override = AggFunction.avg
    from ai4bi.blocks.contracts import DisaggregationMethod
    definition = next(metric for metric in contracts["fab_process_move"].metrics if metric.name == "move_count")
    definition.formula = "AVG(move_count)"
    definition.disaggregation_method = DisaggregationMethod.average
    executor, enriched = report_executor(body, contracts)
    data = sparkline_result(executor, spec.query, spec.visualization, enriched,
        active_filters={}, page_id="main", visual_id="kpi_moves")
    assert [point["value"] for point in data["points"]] == [50, 100]
    assert executor.run(spec.query).iloc[0, 0] == pytest.approx(200/3)


@pytest.mark.parametrize("column", [None, "priority", "absent", ["event_date"]])
def test_sparkline_rejects_invalid_date_field(column):
    from ai4bi_web_api.sparkline import validate_sparkline
    from ai4bi_web_api.errors import AppError
    _, contracts, spec = comparison_fixture(extra={"compare_period": "", "sparkline_date_column": column})
    spec.visualization.show_sparkline = True
    with pytest.raises(AppError, match="日期"):
        validate_sparkline(spec.query, spec.visualization, contracts)


def test_sparkline_distinct_counts_preserve_cross_day_overlap():
    from ai4bi.blocks.contracts import DisaggregationMethod
    from ai4bi_web_api.sparkline import sparkline_result
    from ai4bi_web_api.report_extensions import report_executor
    body, contracts, spec = comparison_fixture([("2024-01-01", 1, "Hot"), ("2024-01-01", 2, "Hot"),
        ("2024-01-03", 2, "Hot"), ("2024-01-03", 3, "Hot")],
        extra={"compare_period": "", "sparkline_date_column": "event_date"})
    spec.visualization.show_sparkline = True
    definition = next(metric for metric in contracts["fab_process_move"].metrics if metric.name == "move_count")
    definition.formula = "COUNT(DISTINCT move_count)"
    definition.disaggregation_method = DisaggregationMethod.count_distinct
    executor, enriched = report_executor(body, contracts)
    data = sparkline_result(executor, spec.query, spec.visualization, enriched,
        active_filters={}, page_id="main", visual_id="kpi_moves")
    assert [point["value"] for point in data["points"]] == [2, 2]
    assert executor.run(spec.query).iloc[0, 0] == 3


def test_sparkline_having_can_remove_daily_points_without_removing_headline():
    from ai4bi.query_spec import HavingSpec, FilterOperator
    from ai4bi_web_api.sparkline import sparkline_result
    from ai4bi_web_api.report_extensions import report_executor
    body, contracts, spec = comparison_fixture([("2024-01-01", 5, "Hot"), ("2024-01-02", 7, "Hot")],
        extra={"compare_period": "", "sparkline_date_column": "event_date"})
    spec.visualization.show_sparkline = True
    spec.query.having = [HavingSpec("fab_process_move", "move_count", FilterOperator.gt, 10)]
    executor, enriched = report_executor(body, contracts)
    data = sparkline_result(executor, spec.query, spec.visualization, enriched,
        active_filters={}, page_id="main", visual_id="kpi_moves")
    assert data["status"] == "unavailable" and data["points"] == [] and data["reason"]
    assert executor.run(spec.query).iloc[0, 0] == 12


def test_comparison_fixture_preserves_cached_template():
    _, original = template("fab")
    before = copy.deepcopy(original)
    _, changed, _ = comparison_fixture([("2024-01-01", 7, "Hot")], dtype="timestamp")
    changed["fab_process_move"].policy.row_filter_column = "priority"
    assert original == before


@pytest.mark.parametrize("kind", ["large_integer", "decimal"])
def test_comparison_preserves_scalar_table_when_display_is_unavailable(kind):
    from contextlib import nullcontext
    from decimal import Decimal
    import pandas as pd
    from ai4bi_web_api.comparison import compare_query
    from ai4bi_web_api.core import clean

    value = 2**53 + 1 if kind == "large_integer" else Decimal("123456789.123456789")
    _, contracts, spec = comparison_fixture(extra={"compare_filter_policy": "keep"})
    current = pd.DataFrame({"moves": pd.Series([value], dtype=object)})
    frames = iter([pd.DataFrame({"__comparison_anchor": [pd.Timestamp("2024-03-01")]}),
                   current, pd.DataFrame({"moves": [5]})])

    class Executor:
        def comparison_window(self, *args):
            return nullcontext()

        def run_with_metadata(self, *args, **kwargs):
            return next(frames), {"source": "governed-result"}

    frame, metadata, result = compare_query(Executor(), spec.query, spec.visualization, contracts,
        active_filters={}, page_id="main", visual_id="kpi_moves")
    assert clean(frame)["rows"] == [{"moves": str(value)}]
    assert frame.iloc[0, 0] == value
    assert metadata == {"source": "governed-result"}
    assert result["status"] == "unavailable" and result["current"] is None
    assert result["reason"]


def test_comparison_utc_boundaries_rls_and_context_restoration():
    from ai4bi_web_api.comparison import ComparisonExecutor, compare_query
    from ai4bi_web_api.filters import ScopedExecutor
    rows = [("2024-02-23T23:59:59Z", 5, "Hot"), ("2024-02-24T00:00:00Z", 7, "Hot"),
            ("2024-03-01T23:59:59Z", 11, "Hot"), ("2024-03-02T00:30:00+02:00", 13, "Hot"),
            ("2025-01-01T00:00:00Z", 999, "Normal"), (None, 1000, "Hot")]
    body, contracts, spec = comparison_fixture(rows, dtype="timestamp")
    contracts["fab_process_move"].policy.row_filter_column = "priority"
    contracts["fab_process_move"].policy.row_filter_identity_key = "priority"
    core = ComparisonExecutor(extra_contracts=contracts, identity={"priority": "Hot"})
    executor = ScopedExecutor(core, body, [])
    frame, metadata, result = compare_query(executor, spec.query, spec.visualization, contracts,
        active_filters={}, page_id="main", visual_id="kpi_moves")
    assert frame.iloc[0,0] == 31
    assert result["anchor"] == "2024-03-01" and result["current_window"] == ["2024-02-24", "2024-03-02"]
    assert result["previous"] == 5 and result["delta"] == 26 and result["delta_percent"] == 520
    assert core._comparison.get() is None
    assert executor.run(spec.query).iloc[0,0] == 1036


@pytest.mark.parametrize("rows,expected,delta,percent", [
    ([("2024-02-23", 0, "Hot"), ("2024-03-01", 7, "Hot")], 0, 7, None),
    ([("2024-02-23", -5, "Hot"), ("2024-03-01", 7, "Hot")], -5, 12, 240),
    ([("2024-03-01", 7, "Hot")], None, None, None),
    ([(None, 7, "Hot")], None, None, None),
])
def test_comparison_missing_period_zero_and_negative_base(rows, expected, delta, percent):
    from ai4bi_web_api.comparison import compare_query
    from ai4bi_web_api.report_extensions import report_executor
    body, contracts, spec = comparison_fixture(rows)
    executor, enriched = report_executor(body, contracts)
    _, _, result = compare_query(executor, spec.query, spec.visualization, enriched, active_filters={}, page_id="main", visual_id="kpi_moves")
    assert (result["previous"],result["delta"],result["delta_percent"]) == (expected,delta,percent)
    if percent is None:
        assert result["reason"]


def test_comparison_having_applies_per_period_not_to_anchor():
    from ai4bi.query_spec import HavingSpec, FilterOperator
    from ai4bi_web_api.comparison import compare_query
    from ai4bi_web_api.report_extensions import report_executor
    body, contracts, spec = comparison_fixture([("2024-02-23", 50, "Hot"), ("2024-03-01", 1, "Hot")])
    spec.query.having = [HavingSpec("fab_process_move", "move_count", FilterOperator.gt, 5)]
    executor, enriched = report_executor(body, contracts)
    frame, metadata, data = compare_query(executor, spec.query, spec.visualization, enriched, active_filters={}, page_id="main", visual_id="kpi_moves")
    assert data["anchor"] == "2024-03-01" and data["current"] is None and data["previous"] == 50
    assert len(frame) == 1 and data["reason"]
    assert any("2024-02-24 <= day < 2024-03-02" in item for item in metadata.filters_applied)


def test_comparison_offset_changes_use_utc_days_and_calendar_period_boundaries():
    from datetime import date
    from ai4bi_web_api.comparison import compare_query, windows
    from ai4bi_web_api.report_extensions import report_executor
    body, contracts, spec = comparison_fixture([("2024-03-03T23:59:59Z", 5, "Hot"),
        ("2024-03-10T01:59:59-05:00", 7, "Hot"), ("2024-03-10T03:00:00-04:00", 11, "Hot")], dtype="timestamp")
    executor, enriched = report_executor(body, contracts)
    _, _, data = compare_query(executor, spec.query, spec.visualization, enriched, active_filters={}, page_id="main", visual_id="kpi_moves")
    assert data["anchor"] == "2024-03-10" and data["current"] == 18 and data["previous"] == 5
    assert windows(date(2024,5,7), "quarter", "calendar") == ((date(2024,4,1),date(2024,5,8)),(date(2023,4,1),date(2023,5,8)))
    assert windows(date(2024,5,7), "year", "calendar") == ((date(2024,1,1),date(2024,5,8)),(date(2023,1,1),date(2023,5,8)))


@pytest.mark.parametrize("extra", [{"compare_period": []}, {"compare_period": "day"}, {"compare_mode": "calendar"},
    {"compare_date_column": "priority"}, {"compare_date_block": []}, {"compare_filter_policy": "unsafe"}])
def test_comparison_invalid_config_is_not_accepted(extra):
    from ai4bi_web_api.errors import AppError
    body, contracts, _ = comparison_fixture(extra=extra)
    with pytest.raises(AppError) as raised:
        validate_report(body, contracts)
    assert raised.value.code == "INVALID_COMPARISON"


def test_comparison_real_snapshot_export_keeps_window_after_source_changes(tmp_path):
    import pandas as pd
    from pypdf import PdfReader
    from openpyxl import load_workbook
    from ai4bi_web_api.exports import export_snapshot
    body, contracts, _ = comparison_fixture([("2023-02-28", 5, "Hot"), ("2024-02-29", 7, "Hot")],
                                           extra={"compare_mode": "calendar", "compare_period": "month"})
    validate_report(body, contracts)
    store = Store(tmp_path / "data")
    try:
        ids = store.create_workspace("Comparison", body, "comparison", "fab")
        for block in contracts.values():
            store.publish_dataset(ids["workspace_id"], block.model_dump(mode="json"), pd.DataFrame(block.data_source.records))
        snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 1, {"visual_ids": ["kpi_moves"]})
        first = run_query(store.root, snapshot)["visuals"]["kpi_moves"]
        comparison = first["kpi"]["comparison"]
        assert comparison["current"] == 7 and comparison["previous"] == 5 and comparison["delta_percent"] == 40
        contracts["fab_process_move"].data_source.records.append({**contracts["fab_process_move"].data_source.records[0], "event_date": "2025-02-28", "move_count": 900})
        block = contracts["fab_process_move"]
        store.publish_dataset(ids["workspace_id"], block.model_dump(mode="json"), pd.DataFrame(block.data_source.records))
        replay = run_query(store.root, snapshot)["visuals"]["kpi_moves"]["kpi"]["comparison"]
        assert all(replay[key] == comparison[key] for key in ("current", "previous", "anchor", "captions"))
        snapshot["format"] = "pdf"
        export_snapshot(store.root, snapshot, tmp_path)
        text = "\n".join(p.extract_text() for p in PdfReader(tmp_path / "export.pdf").pages)
        assert all(caption in text for caption in comparison["captions"])
        snapshot["format"] = "xlsx"
        export_snapshot(store.root, snapshot, tmp_path)
        workbook = load_workbook(tmp_path / "export.xlsx", data_only=True)
        table = list(workbook.worksheets[1].values)
        assert table[1][0] == 7
        assert table[5][:6] == ("current", "2024-02-01", "2024-03-01", 7, 2, 40)
        assert table[6][:4] == ("previous", "2023-02-01", "2023-03-01", 5)
    finally:
        store.close()


@pytest.mark.parametrize("policy,previous", [("replace", 5), ("keep", None)])
def test_comparison_date_filter_policy_keeps_other_scopes(policy, previous):
    from ai4bi_web_api.comparison import compare_query
    from ai4bi_web_api.report_extensions import report_executor
    from ai4bi_web_api.filters import filter_command
    body, contracts, spec = comparison_fixture([("2024-02-23", 5, "Hot"), ("2024-03-01", 7, "Hot"),
                                               ("2024-03-01", 100, "Normal")], extra={"compare_filter_policy": policy})
    body = filter_command(body, "add_filter", {"filter": {"scope": "visual", "page_id": "main", "visual_id": "kpi_moves",
        "block_id": "fab_process_move", "expression": {"operator": "and", "children": [
            {"block_id": "fab_process_move", "column_name": "event_date", "operator": "gte", "value": "2024-02-24"},
            {"block_id": "fab_process_move", "column_name": "priority", "operator": "eq", "value": "Hot"}]}}}, contracts)
    executor, enriched = report_executor(body, contracts)
    before = copy.deepcopy(body)
    frame, _, result = compare_query(executor, spec.query, spec.visualization, enriched, active_filters={}, page_id="main", visual_id="kpi_moves")
    assert result["current"] == 7 and result["previous"] == previous and body == before
    assert executor.run(spec.query, page_id="main", visual_id="kpi_moves").iloc[0,0] == 7


def test_comparison_mixed_or_refuses_replacement_and_calendar_handles_leap_day():
    from datetime import date
    from ai4bi_web_api.comparison import compare_query, windows
    from ai4bi_web_api.report_extensions import report_executor
    from ai4bi_web_api.filters import filter_command
    from ai4bi_web_api.errors import AppError
    assert windows(date(2024,2,29), "month", "calendar") == ((date(2024,2,1),date(2024,3,1)),(date(2023,2,1),date(2023,3,1)))
    body, contracts, spec = comparison_fixture()
    body = filter_command(body, "add_filter", {"filter": {"scope": "report", "block_id": "fab_process_move",
        "expression": {"operator": "or", "children": [
            {"block_id": "fab_process_move", "column_name": "event_date", "operator": "gte", "value": "2026-03-01"},
            {"block_id": "fab_process_move", "column_name": "priority", "operator": "eq", "value": "Hot"}]}}}, contracts)
    executor, enriched = report_executor(body, contracts)
    with pytest.raises(AppError) as raised:
        compare_query(executor, spec.query, spec.visualization, enriched, active_filters={}, page_id="main", visual_id="kpi_moves")
    assert raised.value.code == "AMBIGUOUS_COMPARISON_FILTER" and executor._comparison.get() is None
    with pytest.raises(AppError) as raised:
        validate_report(body, contracts)
    assert raised.value.code == "AMBIGUOUS_COMPARISON_FILTER"


def test_kpi_real_query_uses_effective_scalar_and_validates_before_save(tmp_path):
    import pandas as pd
    from ai4bi_web_api.errors import AppError
    body, contracts = template("fab")
    visual = body["pages"]["main"]["visuals"]["kpi_moves"]
    visual["visualization"]["extra"].update(decimals=1, unit="件", target=800, rag={"target": 800, "warn": 500})
    validate_report(body, contracts)
    invalid = copy.deepcopy(body)
    invalid["pages"]["main"]["visuals"]["kpi_moves"]["visualization"]["extra"]["rag"]["warn"] = 900
    with pytest.raises(AppError) as raised:
        validate_report(invalid, contracts)
    assert raised.value.code == "INVALID_KPI"
    store = Store(tmp_path / "data")
    try:
        ids = store.create_workspace("KPI", body, "create-kpi", "fab")
        for block in contracts.values():
            store.publish_dataset(ids["workspace_id"], block.model_dump(mode="json"), pd.DataFrame(block.data_source.records))
        snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 1, {"visual_ids": ["kpi_moves"]})
        result = run_query(store.root, snapshot)["visuals"]["kpi_moves"]
        assert result["status"] == "ready", result
        assert result["kpi"]["value"] == 600 and result["kpi"]["label"] == "600.0"
        assert result["kpi"]["rag"]["state"] == "warning" and result["kpi"]["pacing"]["fraction"] == .75
    finally:
        store.close()


def test_pie_real_query_preserves_first_metric_and_full_row_population(tmp_path):
    import pandas as pd
    from ai4bi.query_spec import VisualQuerySpec, BlockRef, MetricRef, VisualizationSpec, VisualType
    from ai4bi_web_api.pie import pie_result
    body, contracts = template("retail")
    block = contracts["retail_sales"]
    vid = "pie_revenue_by_category"
    body["pages"]["main"]["visuals"][vid]["query"]["metrics"].append({"block_id": block.block_id, "metric_name": "order_count", "alias": "orders"})
    store = Store(tmp_path / "data")
    try:
        ids = store.create_workspace("Pie", body, "create-pie", "retail")
        store.publish_dataset(ids["workspace_id"], block.model_dump(mode="json"), pd.DataFrame(block.data_source.records))
        result = run_query(store.root, make_snapshot(store, ids["workspace_id"], ids["report_id"], 1, {"visual_ids": [vid]}))["visuals"][vid]
        assert result["status"] == "ready", result
        pie = result["pie"]
        assert pie["status"] == "ready" and len(pie["slices"]) == 3
        assert sum(p["percent"] for p in pie["slices"]) == pytest.approx(100)
        for p in pie["slices"]:
            row = result["rows"][p["row_index"]]
            assert p["value"] == row[pie["metric_key"]] and p["value"] != row["orders"]
        assert sum(p["value"] for p in pie["slices"]) == pytest.approx(sum(r["revenue"] for r in block.data_source.records))
    finally:
        store.close()
    query = VisualQuerySpec("pie", [BlockRef("b")], metrics=[MetricRef("b", "value")])
    incomplete = pie_result(query, VisualizationSpec(VisualType.pie_chart), [{"value": 1}], truncated=True)
    assert incomplete["status"] == "unavailable" and "截斷" in incomplete["reason"]


def test_scatter_binds_two_governed_metrics_and_preserves_filter_identity(tmp_path):
    import pandas as pd
    body, contracts = template("fab")
    block = contracts["fab_process_move"]
    visual = body["pages"]["main"]["visuals"]["bar_qt_step"]
    visual["visualization"]["visual_type"] = "scatter"
    visual["query"]["metrics"] = [{"block_id": block.block_id, "metric_name": name, "alias": alias}
                                   for name, alias in [("move_count", "x"), ("avg_queue_time_hr", "y")]]
    visual["query"]["sort"] = []
    store = Store(tmp_path / "data")
    try:
        ids = store.create_workspace("Scatter", body, "create-scatter", "fab")
        store.publish_dataset(ids["workspace_id"], block.model_dump(mode="json"), pd.DataFrame(block.data_source.records))
        snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 1, {"visual_ids": ["bar_qt_step"]})
        result = run_query(store.root, snapshot)["visuals"]["bar_qt_step"]
        assert result["status"] == "ready", result
        data = result["scatter"]
        assert len(data["points"]) == 6 and data["excluded_count"] == 0
        assert data["x_key"] == "x" and data["y_key"] == "y"
        assert sum(p["x"] for p in data["points"]) == 600
        for point in data["points"]:
            row = result["rows"][point["row_index"]]
            assert point["x"] == row["x"] and point["y"] == row["y"]
            assert point["group"] == row[data["group_key"]]
    finally:
        store.close()


@pytest.mark.parametrize("method", ["ols", "lowess"])
def test_scatter_trendlines_match_original_plotly_per_group(method):
    import numpy as np
    import pandas as pd
    import plotly.express as px
    from ai4bi_web_api.scatter import fit_trendlines
    rows = [{"x": float(x), "y": float((x-4)**2 + (2 if group == "B" else 0)), "group": group}
            for group in ["A", "B"] for x in [8, 0, 3, 1, 7, 4, 2, 6, 5]]
    lines = fit_trendlines(rows, method)
    figure = px.scatter(pd.DataFrame(rows), x="x", y="y", color="group", symbol="group", trendline=method)
    expected = [trace for trace in figure.data if trace.mode == "lines"]
    assert len(lines) == len(expected) == 2
    for actual, old in zip(lines, expected):
        assert actual["status"] == "ready" and actual["n"] == 9
        np.testing.assert_allclose(actual["x"], old.x)
        np.testing.assert_allclose(actual["y"], old.y, rtol=1e-10, atol=1e-10)


def test_scatter_ols_has_known_coefficients_and_degenerate_groups_are_explicit():
    from ai4bi_web_api.scatter import fit_trendlines
    points = [{"x": x, "y": 2*x+1, "group": "A"} for x in [3, 0, 1, 2]]
    line = fit_trendlines(points, "ols")[0]
    assert line["slope"] == pytest.approx(2) and line["intercept"] == pytest.approx(1)
    assert line["r_squared"] == pytest.approx(1)
    for method in ["ols", "lowess"]:
        for data in [points[:1], [{"x": 1, "y": y, "group": "A"} for y in [1, 3, 5]]]:
            result = fit_trendlines(data, method)[0]
            assert result["status"] == "unavailable" and result["reason"] and result["x"] == []
        assert fit_trendlines(points, method, truncated=True)[0]["status"] == "unavailable"
    constant = fit_trendlines([{**p, "y": 3} for p in points], "ols")[0]
    assert constant["status"] == "ready" and constant["r_squared"] is None
    singular = fit_trendlines([{"x": 1e18+x*1024, "y": x, "group": "A"} for x in range(4)], "ols")[0]
    assert singular["status"] == "unavailable" and singular["reason"]


@pytest.mark.parametrize("one_dimension,cell_limit,filtered", [
    (False, None, False), (False, 1, False), (True, None, False), (False, None, True),
])
def test_pivot_nonadditive_totals_use_snapshot_population(tmp_path, one_dimension, cell_limit, filtered):
    import pandas as pd
    report, contracts = template("fab")
    contracts = copy.deepcopy(contracts)
    block = contracts["fab_process_move"]
    original = block.data_source.records[0]
    block.data_source.records = [
        {**original, "move_id": str(i), "step_name": row, "tool_id": column,
         "queue_time_hr": queue, "move_count": moves, "rework_flag": rework, "wafer_id": wafer}
        for i, (row, column, queue, moves, rework, wafer) in enumerate([
            ("A", "X", 2., 1, 1, "w1"), ("A", "X", 4., 3, 0, "w1"),
            ("A", "Y", 12., 2, 1, "w2"), ("B", "X", 30., 4, 0, "w1"),
        ])
    ]
    visual = report["pages"]["main"]["visuals"]["bar_qt_step"]
    visual["visualization"]["visual_type"] = "pivot"
    query = visual["query"]
    query["dimensions"] = [{"block_id": block.block_id, "column_name": "step_name", "alias": "row"}]
    if not one_dimension:
        query["dimensions"].append({"block_id": block.block_id, "column_name": "tool_id", "alias": "column"})
    query["metrics"] = [{"block_id": block.block_id, "metric_name": name, "alias": alias}
                        for name, alias in [("avg_queue_time_hr", "average"), ("unique_wafers", "distinct"),
                                            ("rework_rate", "ratio")]]
    query["sort"] = [{"column_name": "average", "direction": "desc"}]
    query["limit"] = cell_limit
    if filtered:
        report["web_extensions"] = {"version": 1, "persistent_filters": [{
            "filter_id": "pivot-only", "scope": "visual", "page_id": "main", "visual_id": "bar_qt_step",
            "block_id": block.block_id, "column_name": "step_name", "operator": "eq", "value": "A",
            "data_type": "string"}]}
    store = Store(tmp_path / "data")
    try:
        ids = store.create_workspace("Pivot", report, "pivot-create", "fab")
        for contract in contracts.values():
            store.publish_dataset(ids["workspace_id"], contract.model_dump(mode="json"), pd.DataFrame(contract.data_source.records))
        snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 1, {"visual_ids": ["bar_qt_step"]})
        result = run_query(store.root, snapshot)["visuals"]["bar_qt_step"]
        assert result["status"] == "ready", result
        pivot = result["pivot"]
        assert pivot["version"] == 1 and not pivot["truncated"]
        grand = pivot["grand_total"]["rows"][0]
        assert grand["average"] == pytest.approx(6. if filtered else 12.)
        assert grand["distinct"] == 2
        assert grand["ratio"] == pytest.approx(100 / 3 if filtered else 20.)
        rows = {row["row"]: row for row in pivot["row_totals"]["rows"]}
        assert rows["A"]["average"] == 6.
        assert rows["A"]["distinct"] == 2
        assert rows["A"]["ratio"] == pytest.approx(100 / 3)
        if filtered:
            assert set(rows) == {"A"}
        else:
            assert rows["B"]["average"] == 30.
        if one_dimension:
            assert pivot["column_field"] is None and pivot["column_totals"] is None
        else:
            columns = {row["column"]: row for row in pivot["column_totals"]["rows"]}
            assert columns["X"]["average"] == pytest.approx(3. if filtered else 12.)
            assert columns["X"]["distinct"] == 1
            assert columns["X"]["ratio"] == pytest.approx(25. if filtered else 12.5)
        assert pivot["grand_total"]["query"]["limit"] is None
        assert pivot["row_totals"]["query"]["sort"] == []
        if cell_limit:
            assert len(result["rows"]) == 1 and len(rows) == 2
        # A newly published version must not change an already accepted snapshot.
        changed = pd.DataFrame(block.data_source.records)
        changed["queue_time_hr"] = 999.
        store.publish_dataset(ids["workspace_id"], block.model_dump(mode="json"), changed)
        repeated = run_query(store.root, snapshot)["visuals"]["bar_qt_step"]
        assert repeated["rows"] == result["rows"]
        for name in ("row_totals", "column_totals", "grand_total"):
            if pivot[name] is None:
                assert repeated["pivot"][name] is None
            else:
                canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
                assert canonical(repeated["pivot"][name]["rows"]) == canonical(pivot[name]["rows"])
                assert repeated["pivot"][name]["query"] == pivot[name]["query"]
    finally:
        store.close()


def test_pivot_having_is_evaluated_at_each_aggregation_grain():
    from ai4bi.query_spec import VisualQuerySpec, BlockRef, MetricRef, DimensionRef, HavingSpec, FilterOperator, VisualizationSpec, VisualType
    from ai4bi_web_api.report_extensions import report_executor
    from ai4bi_web_api.pivot import pivot_result
    body, contracts = template("fab")
    executor, _ = report_executor(body, contracts)
    query = VisualQuerySpec("pivot-having", [BlockRef("fab_process_move")],
        metrics=[MetricRef("fab_process_move", "move_count")],
        dimensions=[DimensionRef("fab_process_move", "step_name"), DimensionRef("fab_process_move", "tool_id")],
        having=[HavingSpec("fab_process_move", "move_count", FilterOperator.gt, 75)])
    cells, _ = executor.run_with_metadata(query, page_id="main", visual_id="pivot-having")
    assert cells.empty  # Every tool has 50 moves, but each step has 100.
    pivot = pivot_result(executor, query, VisualizationSpec(VisualType.pivot), cells,
                         active_filters={}, page_id="main", visual_id="pivot-having", limit=2)
    assert pivot["row_totals"]["row_count"] == 6
    assert len(pivot["row_totals"]["rows"]) == 2
    assert pivot["row_totals"]["truncated"] and pivot["truncated"]
    assert all(row["move_count"] == 100 for row in pivot["row_totals"]["rows"])
    assert pivot["column_totals"]["rows"] == []
    assert pivot["grand_total"]["rows"] == [{"move_count": 600.0}]


def test_clean_primitive_fast_path_preserves_special_values():
    from datetime import datetime, timezone
    from decimal import Decimal
    from enum import IntEnum, Enum
    import numpy as np
    import pandas as pd
    from ai4bi_web_api.core import clean

    class Number(IntEnum):
        one = 1

    class Label(str, Enum):
        one = "one"

    big = 2**53
    values = [None, True, False, "text", 1, -1, 1.25, float("nan"),
              float("inf"), float("-inf"), big, -big, 2**53-1,
              Number.one, Label.one, np.int64(7), np.float64(2.5),
              pd.NA, pd.NaT, Decimal("1.20"), datetime(2026, 1, 1, tzinfo=timezone.utc)]
    expected = [None, True, False, "text", 1, -1, 1.25, None, None, None,
                str(big), str(-big), 2**53-1, 1, "one", 7, 2.5, None, "NaT",
                "1.20", "2026-01-01T00:00:00+00:00"]
    assert clean(values) == expected
    assert type(clean(Number.one)) is int
    assert type(clean(Label.one)) is str
    expected[10:12] = [big, -big]
    assert clean(values, safe_ints=False) == expected


@pytest.mark.parametrize("values,counts,excluded", [
    ([0., 0., 1., 2., 3., 4.], [3, 3], 0),
    ([-4., -2., 0., 2., 4., None, float("inf")], [2, 3], 2),
    ([3., 3., 3.], [0, 3], 0), ([], [], 0), ([None, None], [], 2),
])
def test_histogram_boundaries_and_missing_population(values, counts, excluded):
    import pandas as pd
    from ai4bi.query_spec import VisualQuerySpec, BlockRef, DimensionRef, VisualizationSpec, VisualType
    from ai4bi_web_api.histogram import histogram_result
    query = VisualQuerySpec("hist", [BlockRef("b")], dimensions=[DimensionRef("b", "value")])
    style = VisualizationSpec(VisualType.bar_chart, extra={"chart_mode": "histogram", "bins": 2})
    bins, summary = histogram_result(query, style, pd.DataFrame({"value": values}))
    assert bins["count"].tolist() == counts
    assert summary["excluded_count"] == excluded
    assert summary["valid_count"] == sum(counts)
    assert summary["source_count"] == len(values)
    if counts:
        assert bins["right_inclusive"].tolist() == [False, True]
        import math
        for index, (low, high) in enumerate(summary["filter_ranges"]):
            assert sum(value is not None and math.isfinite(value) and low <= value <= high for value in values) == counts[index]
    else:
        assert summary["mean"] is None


@pytest.mark.parametrize("change", ["bins", "bool-bins", "metrics", "string", "boolean", "large"])
def test_histogram_rejects_ambiguous_or_unsafe_inputs(change):
    import pandas as pd
    from ai4bi.query_spec import VisualQuerySpec, BlockRef, DimensionRef, MetricRef, VisualizationSpec, VisualType
    from ai4bi_web_api.histogram import histogram_result
    from ai4bi_web_api.errors import AppError
    query = VisualQuerySpec("hist", [BlockRef("b")], dimensions=[DimensionRef("b", "value")])
    style = VisualizationSpec(VisualType.bar_chart, extra={"chart_mode": "histogram", "bins": 2})
    values = [1., 2.]
    if change == "bins": style.extra["bins"] = 201
    elif change == "bool-bins": style.extra["bins"] = True
    elif change == "metrics": query.metrics = [MetricRef("b", "amount")]
    elif change == "string": values = ["1", "2"]
    elif change == "boolean": values = [True, False]
    elif change == "large": values = [2**53, 2**53 + 1]
    with pytest.raises(AppError):
        histogram_result(query, style, pd.DataFrame({"value": values}))


def test_histogram_uses_all_accepted_rows_before_display_limit(tmp_path):
    import pandas as pd
    body, contracts = template("retail")
    block = contracts["retail_sales"]
    block.data_source.records = [{**block.data_source.records[0], "revenue": float(i % 10)} for i in range(6000)]
    visual = body["pages"]["main"]["visuals"]["hist_revenue"]
    visual["visualization"]["extra"]["bins"] = 10
    comparison = copy.deepcopy(visual)
    comparison["component_id"] = comparison["query"]["spec_id"] = "hist_compare"
    body["pages"]["main"]["visuals"]["hist_compare"] = comparison
    body["pages"]["main"]["visual_order"].append("hist_compare")
    store = Store(tmp_path / "data")
    try:
        ids = store.create_workspace("Histogram", body, "create-histogram", "retail")
        store.publish_dataset(ids["workspace_id"], block.model_dump(mode="json"), pd.DataFrame(block.data_source.records))
        snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 1, {"visual_ids": ["hist_revenue"]})
        result = run_query(store.root, snapshot)["visuals"]["hist_revenue"]
        assert result["status"] == "ready", result
        assert not result["truncated"]
        assert [r["count"] for r in result["rows"]] == [600] * 10
        assert result["histogram"]["mean"] == result["histogram"]["median"] == 4.5
        assert result["histogram"]["source_count"] == 6000
        selected = make_snapshot(store, ids["workspace_id"], ids["report_id"], 1, {
            "visual_ids": ["hist_revenue", "hist_compare"], "filters": [{"source_visual_id": "hist_revenue",
            "block_id": "retail_sales", "column_name": "revenue", "operator": "between",
            "value": result["histogram"]["filter_ranges"][0]}]})
        filtered = run_query(store.root, selected)["visuals"]
        assert filtered["hist_revenue"]["histogram"]["valid_count"] == 6000
        assert filtered["hist_compare"]["histogram"]["valid_count"] == 600
        assert filtered["hist_compare"]["histogram"]["max"] == 0.
    finally:
        store.close()


def test_geography_uses_fixed_core_lookup_and_preserves_original_rows():
    from ai4bi.query_spec import VisualQuerySpec, BlockRef, DimensionRef
    from ai4bi_web_api.geo import geographic_result
    from ai4bi_web_api.errors import AppError
    query = VisualQuerySpec("geo", [BlockRef("b")], dimensions=[DimensionRef("b", "city", "location")])
    rows = [{"location": value, "_lat": 999, "amount": amount} for value, amount in
            [("臺北市", 10), ("taipei", -5), ("London", 0), (None, None), ("unknown", 8)]]
    before = copy.deepcopy(rows)
    geo = geographic_result(query, rows)
    assert geo["mapped_count"] == 3 and geo["unmapped_count"] == 2
    assert geo["points"] == [
        {"row_index": 0, "latitude": 25.033, "longitude": 121.5654},
        {"row_index": 1, "latitude": 25.033, "longitude": 121.5654},
        {"row_index": 2, "latitude": 51.5074, "longitude": -.1278}]
    assert geo["location_field"]["key"] == "location"
    assert rows == before
    assert geographic_result(query, [rows[-1]])["points"] == []
    query.dimensions = []
    with pytest.raises(AppError, match="地圖需要"):
        geographic_result(query, rows)


def test_contract_fingerprints_cover_rows_order_types_and_metadata():
    from ai4bi_web_api.core import validation_contract_fingerprints
    _, contracts = template("fab")
    contracts = copy.deepcopy(contracts)
    block = contracts["fab_process_move"]
    block.data_source.records = [{"value":1}, {"value":2}]
    contracts = {"source":block}
    baseline = validation_contract_fingerprints(contracts)
    assert validation_contract_fingerprints(copy.deepcopy(contracts)) == baseline
    for rows in ([{"value":2},{"value":1}], [{"value":1}], [{"value":True},{"value":2}],
                 [{"value":1.0},{"value":2}], [{"value":1},{"value":3}]):
        changed = copy.deepcopy(contracts)
        changed["source"].data_source.records = rows
        assert validation_contract_fingerprints(changed) != baseline
    changed = copy.deepcopy(contracts)
    changed["source"].columns[0].description = "Changed schema metadata"
    assert validation_contract_fingerprints(changed) != baseline


def test_contract_fingerprint_extra_memory_does_not_copy_the_table():
    import tracemalloc
    from ai4bi_web_api.core import validation_contract_fingerprints
    _, contracts = template("fab")
    contracts = copy.deepcopy(contracts)
    block = contracts["fab_process_move"]
    block.data_source.records = (block.data_source.records * 20)[:10000]
    tracemalloc.start()
    try:
        fingerprints = validation_contract_fingerprints({"source":block})
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(fingerprints["source"]) == 64
    # Input storage is outside this measurement. The previous full-table copy
    # consumed about 25 MB for this same 10k x 22 fixture.
    assert peak < 4 * 1024 * 1024


@pytest.mark.parametrize("change", ["title", "records", "formula", "parameters", "filter", "scope", "query", "invalid-layout", "invalid-metric"])
def test_validation_proofs_require_identical_governed_inputs(monkeypatch, change):
    from ai4bi_web_api.core import QueryValidationCache
    from ai4bi_web_api.filters import GroupedExecutor, filter_command
    body, contracts = template("fab")
    cache = QueryValidationCache()
    calls = []
    original = GroupedExecutor.run

    def measured(self, spec, *args, **kwargs):
        calls.append(spec.spec_id)
        return original(self, spec, *args, **kwargs)

    monkeypatch.setattr(GroupedExecutor, "run", measured)
    validate_report(body, contracts, validation_cache=cache, validation_scope="workspace:report")
    initial = len(calls)
    assert initial == 5
    changed = copy.deepcopy(body)
    changed_contracts = copy.deepcopy(contracts)
    scope = "workspace:report"
    if change == "title":
        changed["title"] = "Presentation only"
    elif change == "records":
        changed_contracts["fab_process_move"].data_source.records[0]["move_count"] = 12345
    elif change == "formula":
        changed_contracts["fab_process_move"].metrics[0].formula += " + 0"
    elif change == "parameters":
        changed.setdefault("web_extensions", {})["parameters"] = {"discount": 0.25}
    elif change == "filter":
        changed = filter_command(changed, "add_filter", {"filter":{"scope":"visual", "page_id":"main",
            "visual_id":"kpi_moves", "block_id":"fab_process_move", "column_name":"step_name",
            "operator":"eq", "value":"Etch"}}, changed_contracts)
    elif change == "scope":
        scope = "another-workspace:report"
    elif change == "query":
        changed["pages"]["main"]["visuals"]["bar_qt_step"]["query"]["limit"] = 3
    elif change == "invalid-layout":
        from ai4bi_web_api.errors import AppError
        changed["pages"]["main"]["visuals"]["kpi_moves"]["col_span"] = 13
        with pytest.raises(AppError):
            validate_report(changed, changed_contracts, validation_cache=cache, validation_scope=scope)
        assert len(calls) == initial
        return
    else:
        changed["pages"]["main"]["visuals"]["kpi_moves"]["query"]["metrics"][0]["metric_name"] = "missing_metric"
        with pytest.raises(QueryPlanningError):
            validate_report(changed, changed_contracts, validation_cache=cache, validation_scope=scope)
        assert len(calls) > initial
        return
    validated = validate_report(changed, changed_contracts, validation_cache=cache, validation_scope=scope)
    if change == "title":
        assert validated["title"] == "Presentation only" and len(calls) == initial
    else:
        assert len(calls) > initial
    if change == "filter":
        assert calls[initial:] == ["kpi_moves"]


def test_validation_proofs_are_bounded_and_never_remember_failures():
    from ai4bi_web_api.core import QueryValidationCache
    cache = QueryValidationCache(max_entries=2)
    calls = []
    def check(key):
        cache.run(key, lambda: calls.append(key))
    for key in ("a", "b", "a", "c", "b"):
        check(key)
    assert calls == ["a", "b", "c", "b"]
    for _ in range(2):
        with pytest.raises(ValueError):
            cache.run("failed", lambda: (_ for _ in ()).throw(ValueError("Not valid")))
    check("failed")
    assert calls[-1] == "failed" and len(cache._verified) == 2


@pytest.mark.parametrize("change", ["title", "data", "metadata", "scope", "parameters", "corrupt", "forged-version"])
def test_stored_validation_uses_verified_bytes_and_metadata(tmp_path, monkeypatch, change):
    import hashlib
    import pandas as pd
    from ai4bi_web_api import core
    from ai4bi_web_api.filters import GroupedExecutor
    from ai4bi_web_api.errors import AppError
    body, contracts = template("fab")
    store = Store(tmp_path)
    ids = store.create_workspace("Stored proof", body, "stored-proof", "fab")
    for block in contracts.values():
        store.publish_dataset(ids["workspace_id"], block.model_dump(mode="json"), pd.DataFrame(block.data_source.records))
    sources = store.datasets(ids["workspace_id"])
    cache = core.QueryValidationCache()
    calls = []
    original = GroupedExecutor.run

    def measured(self, spec, *args, **kwargs):
        result = original(self, spec, *args, **kwargs)
        calls.append((spec.spec_id, result))
        return result

    monkeypatch.setattr(GroupedExecutor, "run", measured)
    monkeypatch.setattr(core, "validation_contract_fingerprints", lambda _: pytest.fail("Decoded rows hashed again"))
    core.validate_stored_report(body, tmp_path, sources, validation_cache=cache, validation_scope="one")
    assert len(calls) == 5
    changed = copy.deepcopy(body)
    changed["title"] = "Updated"
    scope = "one"
    source = next(item for item in sources if item["contract"]["block_id"] == "fab_process_move")
    path = tmp_path / source["path"]
    if change == "data":
        frame = pd.read_parquet(path)
        frame["move_count"] *= 2
        frame.to_parquet(path, index=False)
        source["version"] = hashlib.sha256(path.read_bytes()).hexdigest()
    elif change == "metadata":
        source["contract"]["metrics"][0]["description"] = "Changed definition metadata"
    elif change == "scope":
        scope = "two"
    elif change == "parameters":
        changed.setdefault("web_extensions", {})["parameters"] = {"discount": .5}
    elif change == "corrupt":
        path.write_bytes(path.read_bytes() + b"corrupt")
    elif change == "forged-version":
        source["version"] = "0" * 64
    if change in {"corrupt", "forged-version"}:
        with pytest.raises(AppError) as caught:
            core.validate_stored_report(changed, tmp_path, sources, validation_cache=cache, validation_scope=scope)
        assert caught.value.code == "SOURCE_CORRUPT" and len(calls) == 5
    else:
        result = core.validate_stored_report(changed, tmp_path, sources, validation_cache=cache, validation_scope=scope)
        assert result["title"] == "Updated"
        assert len(calls) == (5 if change == "title" else 10)
        if change == "data":
            moves = body["pages"]["main"]["visuals"]["kpi_moves"]["query"]["spec_id"]
            assert next(frame for name, frame in calls[5:] if name == moves).iloc[0, 0] == 1200
    store.close()


@pytest.mark.parametrize("calculated", [False, True])
def test_stored_warm_validation_rechecks_bytes_and_decodes_only_for_execution(tmp_path, monkeypatch, calculated):
    import pandas as pd
    from ai4bi_web_api import core
    from ai4bi_web_api.filters import GroupedExecutor
    body, contracts = template("fab")
    if calculated:
        body["web_extensions"] = {"calculated_metrics": [{"block_id": "fab_process_move",
            "name": "double_moves", "formula": "SUM(move_count) * 2"}]}
    store = Store(tmp_path)
    ids = store.create_workspace("Lazy validation", body, "lazy-proof", "fab")
    for block in contracts.values():
        store.publish_dataset(ids["workspace_id"], block.model_dump(mode="json"), pd.DataFrame(block.data_source.records))
    sources = store.datasets(ids["workspace_id"])
    reads, parses, queries = [], [], []
    read, parse, run = core._read_source, core._parse_contracts, GroupedExecutor.run

    def record_read(root, item):
        reads.append(item["version"])
        return read(root, item)

    def record_parse(items):
        parses.append(True)
        return parse(items)

    def record_run(self, query, *args, **kwargs):
        frame = run(self, query, *args, **kwargs)
        queries.append(query.spec_id)
        if query.spec_id == "validate_calculation":
            assert frame.iloc[0, 0] == 1200
        return frame

    monkeypatch.setattr(core, "_read_source", record_read)
    monkeypatch.setattr(core, "_parse_contracts", record_parse)
    monkeypatch.setattr(GroupedExecutor, "run", record_run)
    cache = core.QueryValidationCache()
    for index in range(2):
        body["title"] = f"Title {index}"
        assert core.validate_stored_report(body, tmp_path, sources, validation_cache=cache)["title"] == body["title"]
    assert len(reads) == 2 * len(sources)
    assert len(parses) == (2 if calculated else 1)
    assert len(queries) == (7 if calculated else 5)
    # A changed query must execute on actual rows, even after a warm title edit.
    visual = body["pages"]["main"]["visuals"]["kpi_moves"]
    visual["query"]["metrics"][0]["alias"] = "updated_total"
    core.validate_stored_report(body, tmp_path, sources, validation_cache=cache)
    assert len(parses) == (3 if calculated else 2)
    assert len(queries) == (9 if calculated else 6)
    store.close()


@pytest.mark.parametrize("change", ["unchanged", "data", "metadata", "scope", "parameters", "predicate", "corrupt", "signature", "missing-visual", "invalid-query"])
def test_bookmark_proofs_recheck_snapshot_and_execute_changed_views(tmp_path, monkeypatch, change):
    import hashlib
    import pandas as pd
    from ai4bi_web_api import core
    from ai4bi_web_api.errors import AppError
    from ai4bi_web_api.filters import GroupedExecutor
    body, contracts = template("fab")
    store = Store(tmp_path)
    try:
        ids = store.create_workspace("Bookmark proofs", body, "bookmark-proof", "fab")
        for block in contracts.values():
            store.publish_dataset(ids["workspace_id"], block.model_dump(mode="json"), pd.DataFrame(block.data_source.records))
        sources = store.datasets(ids["workspace_id"])
        cache = core.QueryValidationCache()
        body = core.validate_stored_report(body, tmp_path, sources, validation_cache=cache,
            validation_scope="one", bookmark_edit=("save_bookmark", {"name":"All", "view":{"page_id":"main", "filters":[]}}))
        bookmark = body["web_extensions"]["bookmarks"][0]
        bid = bookmark["bookmark_id"]
        reads, parses, results = [], [], []
        read, parse, run = core._read_source, core._parse_contracts, GroupedExecutor.run
        def measured_read(root, item):
            reads.append(item["version"])
            return read(root, item)
        def measured_parse(items):
            parses.append(True)
            return parse(items)
        def measured_run(self, query, *args, **kwargs):
            result = run(self, query, *args, **kwargs)
            results.append((query.spec_id, result))
            return result
        monkeypatch.setattr(core, "_read_source", measured_read)
        monkeypatch.setattr(core, "_parse_contracts", measured_parse)
        monkeypatch.setattr(GroupedExecutor, "run", measured_run)
        def resolve(scope="one"):
            return core.resolve_stored_bookmark(body, bid, tmp_path, sources, validation_cache=cache, validation_scope=scope)
        assert resolve()["page_id"] == "main"
        baseline = len(parses), len(results)
        assert resolve()["page_id"] == "main"
        assert (len(parses), len(results)) == baseline
        assert len(reads) == 2 * len(sources)
        source = next(item for item in sources if item["contract"]["block_id"] == "fab_process_move")
        path = tmp_path / source["path"]
        scope = "one"
        if change == "data":
            frame = pd.read_parquet(path)
            frame["move_count"] *= 2
            frame.to_parquet(path, index=False)
            source["version"] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif change == "metadata":
            source["contract"]["metrics"][0]["description"] = "Changed metadata"
        elif change == "scope":
            scope = "another-publication"
        elif change == "parameters":
            body["web_extensions"]["parameters"] = {"discount":.5}
        elif change in {"predicate", "signature"}:
            bookmark["view"]["filters"] = [{"block_id":"fab_process_move", "column_name":"step_name", "operator":"eq", "value":"Etch"}]
            column = next(c for c in source["contract"]["columns"] if c["name"] == "step_name")
            bookmark["fields"] = [{"block_id":"fab_process_move", "column_name":"step_name", "data_type":column["data_type"]}]
            if change == "signature":
                bookmark["fields"][0]["data_type"] = "changed-type"
        elif change == "corrupt":
            path.write_bytes(path.read_bytes() + b"corrupt")
        elif change == "missing-visual":
            bookmark["view"]["selected_visual_id"] = "deleted-visual"
        elif change == "invalid-query":
            body["pages"]["main"]["visuals"]["kpi_moves"]["query"]["metrics"][0]["metric_name"] = "missing_metric"
        if change in {"corrupt", "signature", "missing-visual", "invalid-query"}:
            for _ in range(2):
                with pytest.raises(AppError):
                    resolve(scope)
            if change != "invalid-query":
                assert len(parses) == baseline[0]
        else:
            assert resolve(scope)["page_id"] == "main"
            assert len(parses) == baseline[0] + (change != "unchanged")
            if change in {"data", "predicate"}:
                total = next(frame.iloc[0, 0] for name, frame in results[baseline[1]:] if name == "kpi_moves")
                assert total == (1200 if change == "data" else 100)
        if change == "unchanged":
            # A second bookmark and an update of the same view share execution proofs.
            for kind, payload in [("save_bookmark", {"name":"All again", "view":bookmark["view"]}),
                                  ("update_bookmark", {"bookmark_id":bid, "view":bookmark["view"]})]:
                body = core.validate_stored_report(body, tmp_path, sources, validation_cache=cache,
                    validation_scope="one", bookmark_edit=(kind, payload))
            assert (len(parses), len(results)) == baseline
    finally:
        store.close()


def test_worker_dataframe_sources_preserve_types_and_recheck_file_versions(tmp_path, monkeypatch):
    import pandas as pd
    from ai4bi.blocks.datastore import materialize_dataframe
    from ai4bi_web_api import core
    from ai4bi_web_api.errors import AppError
    body, contracts = template("fab")
    store = Store(tmp_path)
    ids = store.create_workspace("Typed worker", body, "typed", "fab")
    frame = pd.DataFrame({"move_id": pd.Series(["001", "002"], dtype="string"),
                          "move_count": pd.Series([9007199254740993, None], dtype="Int64"),
                          "queue_time_hr": pd.Series([1.25, None], dtype="Float64"),
                          "event_date": pd.to_datetime(["2026-01-01T12:34:56", None])})
    store.publish_dataset(ids["workspace_id"], contracts["fab_process_move"].model_dump(mode="json"), frame)
    datasets = store.datasets(ids["workspace_id"])
    monkeypatch.setattr(core, "_worker_dataframe_sources", False)
    ordinary = core.load_contracts(tmp_path, datasets)["fab_process_move"]
    assert ordinary.data_source.source_type == "inline"
    core.enable_worker_dataframe_sources()
    cached = core.load_contracts(tmp_path, datasets)["fab_process_move"]
    assert cached.data_source.source_type == "cached" and cached.data_source.row_count == 2
    pd.testing.assert_frame_equal(materialize_dataframe(cached), frame)
    assert core.clean(materialize_dataframe(cached).to_dict(orient="records"), safe_ints=False) == ordinary.data_source.records
    path = tmp_path / datasets[0]["path"]
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(AppError) as caught: core.load_contracts(tmp_path, datasets)
    assert caught.value.code == "SOURCE_CORRUPT"


def test_worker_source_index_reuses_hash_but_rejects_mutated_or_missing_frame(monkeypatch):
    from collections import OrderedDict
    import pandas as pd
    from ai4bi.blocks import datastore
    from ai4bi_web_api import core
    monkeypatch.setattr(core, "_worker_source_keys", OrderedDict())
    monkeypatch.setattr(datastore, "_STORE", {})
    original = datastore.put_dataframe
    calls = []
    def put(frame):
        calls.append(len(frame))
        return original(frame)
    monkeypatch.setattr(datastore, "put_dataframe", put)
    frame = pd.DataFrame({"source_index_probe": [1, 2, 3]})
    key = core.worker_source_key(b"verified-parquet-a", frame)
    assert core.worker_source_key(b"verified-parquet-a", frame.copy()) == key
    assert len(calls) == 1
    datastore.get_dataframe(key).iloc[0, 0] = 999
    assert core.worker_source_key(b"verified-parquet-a", frame) is None
    assert len(calls) == 2
    datastore.clear()
    assert core.worker_source_key(b"verified-parquet-a", frame) == key
    assert len(calls) == 3
    # A changed version must be checked, even if the decoded rows are equal.
    assert core.worker_source_key(b"verified-parquet-b", frame) == key
    assert len(calls) == 4


def test_worker_source_index_is_bounded_and_does_not_hide_dtype_collisions(monkeypatch):
    from collections import OrderedDict
    import pandas as pd
    from ai4bi.blocks import datastore
    from ai4bi_web_api import core
    monkeypatch.setattr(core, "_worker_source_keys", OrderedDict())
    monkeypatch.setattr(datastore, "_STORE", {})
    frame = pd.DataFrame({"source_index_types": [1, 0]})
    for index in range(40):
        assert core.worker_source_key(str(index).encode(), frame) is not None
    assert len(core._worker_source_keys) == 32
    assert core.worker_source_key(b"39", frame.astype(bool)) is None


@pytest.mark.parametrize("kind", ["offset", "date", "naive"])
def test_worker_dataframe_temporal_group_labels_match_inline(tmp_path, monkeypatch, kind):
    import pandas as pd
    from ai4bi_web_api import core
    body, contracts = template("fab")
    visual = body["pages"]["main"]["visuals"]["bar_qt_step"]
    visual["query"]["dimensions"][0].update(column_name="event_date", alias="period")
    body["pages"]["main"].update(visuals={"bar_qt_step": visual}, visual_order=["bar_qt_step"])
    store = Store(tmp_path)
    ids = store.create_workspace("Temporal labels", body, "temporal", "fab")
    block = contracts["fab_process_move"]
    frame = pd.DataFrame(block.data_source.records)
    dates = pd.to_datetime(frame["event_date"])
    frame["event_date"] = dates.dt.tz_localize("Asia/Taipei") if kind == "offset" else dates.dt.date if kind == "date" else dates
    store.publish_dataset(ids["workspace_id"], block.model_dump(mode="json"), frame)
    snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 1, {})
    monkeypatch.setattr(core, "_worker_dataframe_sources", False)
    baseline = run_query(tmp_path, snapshot)
    core.enable_worker_dataframe_sources()
    actual = run_query(tmp_path, snapshot)
    expected = baseline["visuals"]["bar_qt_step"]
    assert expected["status"] == actual["visuals"]["bar_qt_step"]["status"] == "ready"
    assert actual["visuals"]["bar_qt_step"]["rows"] == expected["rows"]
    assert all((row["period"].endswith("+08:00") if kind == "offset" else len(row["period"]) == 10 if kind == "date" else "T" in row["period"]) for row in expected["rows"])


def test_worker_dataframe_decimal_retains_legacy_cleaning(tmp_path, monkeypatch):
    import pandas as pd
    from decimal import Decimal
    from ai4bi_web_api import core
    body, contracts = template("fab")
    store = Store(tmp_path)
    ids = store.create_workspace("Decimal semantics", body, "decimal", "fab")
    frame = pd.DataFrame({"move_id": ["001", "002"], "queue_time_hr": [Decimal("1.20"), None]})
    store.publish_dataset(ids["workspace_id"], contracts["fab_process_move"].model_dump(mode="json"), frame)
    monkeypatch.setattr(core, "_worker_dataframe_sources", True)
    loaded = core.load_contracts(tmp_path, store.datasets(ids["workspace_id"]))["fab_process_move"]
    assert loaded.data_source.source_type == "inline"
    assert loaded.data_source.records == [{"move_id": "001", "queue_time_hr": "1.20"}, {"move_id": "002", "queue_time_hr": None}]


def test_worker_dataframe_hash_collision_keeps_distinct_types(tmp_path, monkeypatch):
    import pandas as pd
    from ai4bi.blocks.datastore import materialize_dataframe, put_dataframe
    from ai4bi_web_api import core
    body, contracts = template("fab")
    store = Store(tmp_path)
    ids = store.create_workspace("Type collision", body, "collision", "fab")
    # Actual collision in the fixed core, not a mocked hash implementation.
    column = "benchmark_collision_flag"
    integers = pd.DataFrame({column: [1, 0]})
    booleans = pd.DataFrame({column: [True, False]})
    assert put_dataframe(integers) == put_dataframe(booleans)
    for bid, frame, dtype in (("integer_block", integers, "integer"), ("boolean_block", booleans, "boolean")):
        block = contracts["fab_process_move"].model_dump(mode="json")
        block.update(block_id=bid, columns=[{"name": column, "data_type": dtype}], metrics=[])
        store.publish_dataset(ids["workspace_id"], block, frame)
    monkeypatch.setattr(core, "_worker_dataframe_sources", True)
    loaded = core.load_contracts(tmp_path, store.datasets(ids["workspace_id"]))
    pd.testing.assert_frame_equal(materialize_dataframe(loaded["integer_block"]), integers)
    pd.testing.assert_frame_equal(materialize_dataframe(loaded["boolean_block"]), booleans)
    assert loaded["integer_block"].data_source.source_type == "cached"
    assert loaded["boolean_block"].data_source.source_type == "inline"


@pytest.mark.parametrize("mode", ["loader", "stored"])
def test_parquet_parser_uses_the_bytes_that_passed_digest_validation(tmp_path, monkeypatch, mode):
    import pandas as pd
    from ai4bi.blocks.datastore import materialize_dataframe
    from ai4bi_web_api import core
    body, contracts = template("fab")
    page = body["pages"]["main"]
    page["visuals"] = {"kpi_moves": page["visuals"]["kpi_moves"]}
    page["visual_order"] = ["kpi_moves"]
    store = Store(tmp_path)
    ids = store.create_workspace("Checked bytes", body, "bytes", "fab")
    block = contracts["fab_process_move"]
    frame = pd.DataFrame(block.data_source.records)
    store.publish_dataset(ids["workspace_id"], block.model_dump(mode="json"), frame)
    datasets = store.datasets(ids["workspace_id"])
    path = tmp_path / datasets[0]["path"]
    original = path.read_bytes()
    read_parquet = pd.read_parquet
    def replace_after_check(stream):
        assert stream.getvalue() == original
        path.write_bytes(b"replaced after digest check")
        return read_parquet(stream)
    monkeypatch.setattr(core.pd, "read_parquet", replace_after_check)
    monkeypatch.setattr(core, "_worker_dataframe_sources", mode == "loader")
    if mode == "loader":
        loaded = core.load_contracts(tmp_path, datasets)[block.block_id]
        pd.testing.assert_frame_equal(materialize_dataframe(loaded), frame)
    else:
        from ai4bi_web_api.errors import AppError
        cache = core.QueryValidationCache()
        assert core.validate_stored_report(body, tmp_path, datasets, validation_cache=cache)["title"] == body["title"]
        with pytest.raises(AppError) as caught:
            core.validate_stored_report(body, tmp_path, datasets, validation_cache=cache)
        assert caught.value.code == "SOURCE_CORRUPT"
    store.close()


@pytest.mark.parametrize("nonfinite", [None, float("inf"), float("-inf"), float("nan")])
def test_worker_dataframe_queries_match_inline_across_blocks(tmp_path, monkeypatch, nonfinite):
    import pandas as pd
    from ai4bi_web_api import core
    body, contracts = template("fab")
    store = Store(tmp_path)
    ids = store.create_workspace("Worker parity", body, "parity", "fab")
    for contract in contracts.values():
        frame = pd.DataFrame(contract.data_source.records)
        if contract.block_id == "fab_process_move" and nonfinite is not None:
            frame.loc[0, "queue_time_hr"] = nonfinite
        store.publish_dataset(ids["workspace_id"], contract.model_dump(mode="json"), frame)
    snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 1, {})
    monkeypatch.setattr(core, "_worker_dataframe_sources", False)
    baseline = run_query(tmp_path, snapshot)
    core.enable_worker_dataframe_sources()
    cached = run_query(tmp_path, snapshot)
    for vid, visual in baseline["visuals"].items():
        assert cached["visuals"][vid]["status"] == visual["status"] == "ready"
        assert cached["visuals"][vid]["rows"] == visual["rows"]
    assert cached["data_versions"] == baseline["data_versions"]


@pytest.mark.parametrize("invalid",[None,True,"5",float("nan"),float("inf"),[5],{"sql":"1=1"}])
def test_having_rejects_non_numeric_or_ignored_value(invalid):
    from ai4bi_web_api.errors import AppError
    body,contracts=template("fab")
    query=body["pages"]["main"]["visuals"]["bar_qt_step"]["query"]
    metric=query["metrics"][0]
    query["having"]=[{"block_id":metric["block_id"],"metric_name":metric["metric_name"],"operator":"gt","value":invalid}]
    with pytest.raises(AppError) as caught:validate_report(body,contracts)
    assert caught.value.code=="INVALID_HAVING"


@pytest.mark.parametrize("change",["missing_metric","duplicate_metric","backwards","too_many","extra","unsupported"])
def test_having_rejects_ambiguous_or_invalid_definition(change):
    from ai4bi_web_api.errors import AppError
    body,contracts=template("fab")
    query=body["pages"]["main"]["visuals"]["bar_qt_step"]["query"]
    metric=query["metrics"][0]
    item={"block_id":metric["block_id"],"metric_name":metric["metric_name"],"operator":"gt","value":5}
    query["having"]=[item]
    if change=="missing_metric":item["metric_name"]="not-projected"
    elif change=="duplicate_metric":query["metrics"].append({**metric,"alias":"second"})
    elif change=="backwards":item.update(operator="between",value=[5,1])
    elif change=="too_many":query["having"]=[item]*51
    elif change=="extra":item["expression"]="1=1"
    else:item["operator"]="is_null"
    with pytest.raises(AppError):validate_report(body,contracts)


def test_having_filters_aggregates_after_where_and_current_drill_level():
    from ai4bi_web_api.filters import filter_command
    from ai4bi_web_api.report_extensions import report_executor
    from ai4bi_web_api.drilling import apply_drill
    from ai4bi.report.models import ExecutableReportSpec
    body,contracts=template("fab")
    source=body["pages"]["main"]["visuals"]["bar_qt_step"]
    metric=source["query"]["metrics"][0]
    source["query"]["having"]=[{"block_id":metric["block_id"],"metric_name":metric["metric_name"],"operator":"between","value":[2,4]}]
    source["visualization"]["extra"]["drill_hierarchy"]=["step_name","tool_id"]
    body=filter_command(body,"add_filter",{"filter":{"scope":"report","block_id":"fab_process_move","column_name":"priority","operator":"eq","value":"Hot"}},contracts)
    body=validate_report(body,contracts)
    visual=ExecutableReportSpec.from_dict(body).pages["main"].visuals["bar_qt_step"]
    executor,_=report_executor(body,contracts)
    rows=contracts["fab_process_move"].data_source.records
    def expected(column,path=None):
        values={}
        for row in rows:
            if row["priority"]=="Hot" and (path is None or row["step_name"]==path):values.setdefault(row[column],[]).append(row["queue_time_hr"])
        return {key:sum(v)/len(v) for key,v in values.items() if 2<=sum(v)/len(v)<=4}
    query,context=apply_drill(visual.query,visual.visualization,contracts)
    frame=executor.run(query)
    assert dict(zip(frame.iloc[:,0],frame.iloc[:,1]))==pytest.approx(expected("step_name"))
    context["path"]=[{"column":"step_name","value":"Lithography"}]
    query,_=apply_drill(visual.query,visual.visualization,contracts,context)
    frame=executor.run(query)
    assert dict(zip(frame.iloc[:,0],frame.iloc[:,1]))==pytest.approx(expected("tool_id","Lithography"))


def grouped_filter_payload():
    def leaf(column,operator,value):
        return {"block_id":"fab_process_move","column_name":column,"operator":operator,"value":value}
    return {"scope":"report","block_id":"fab_process_move","expression":{"operator":"or","children":[
        leaf("step_name","eq","Etch"),{"operator":"and","children":[leaf("priority","eq","Hot"),leaf("queue_time_hr","gt",2)]}]}}


def test_nested_filters_use_core_sql_rls_having_and_scoped_ai_population():
    from ai4bi_web_api.filters import filter_command, GroupedExecutor, ScopedExecutor
    from ai4bi_web_api.report_extensions import report_executor
    from ai4bi_web_api.drilling import assistant_source_contracts
    from ai4bi.blocks.datastore import materialize_dataframe
    from ai4bi.query_spec import VisualQuerySpec, BlockRef, MetricRef, DimensionRef, HavingSpec, FilterOperator
    from ai4bi.report.models import ExecutableReportSpec
    body,contracts = template("fab")
    before = copy.deepcopy(body)
    body = filter_command(body,"add_filter",{"filter":grouped_filter_payload()},contracts)
    body = validate_report(body,contracts)
    rows = contracts["fab_process_move"].data_source.records
    selected = [r for r in rows if r["step_name"]=="Etch" or (r["priority"]=="Hot" and r["queue_time_hr"]>2)]
    assert 100 < len(selected) < 600
    executor,enriched = report_executor(body,contracts,page_id="main",visual_id="kpi_moves")
    query = ExecutableReportSpec.from_dict(body).pages["main"].visuals["kpi_moves"].query
    frame,metadata = executor.run_with_metadata(query)
    assert frame.iloc[0,0] == len(selected)
    assert any(" OR " in value and " AND " in value for value in metadata.filters_applied)
    scoped = assistant_source_contracts(executor,enriched,None)
    assert len(materialize_dataframe(scoped["fab_process_move"]))==len(selected)
    # Core HAVING binds after grouped WHERE: assert both parameter ordering and group values.
    grouped = VisualQuerySpec("grouped-count",[BlockRef("fab_process_move")],
        dimensions=[DimensionRef("fab_process_move","step_name")],metrics=[MetricRef("fab_process_move","move_count","moves")],
        having=[HavingSpec("fab_process_move","move_count",FilterOperator.gt,50)])
    frame = executor.run(grouped)
    expected = {step:sum(r["step_name"]==step for r in selected) for step in {r["step_name"] for r in rows}}
    assert dict(zip(frame["step_name"],frame["moves"]))=={step:n for step,n in expected.items() if n>50}
    # A group cannot bypass a core row-level policy, even through an OR branch.
    secured = copy.deepcopy(enriched)
    secured["fab_process_move"].policy.row_filter_column = "priority"
    secured["fab_process_move"].policy.row_filter_identity_key = "priority"
    core = GroupedExecutor(extra_contracts=secured,identity={"priority":"Hot"})
    wrapper = ScopedExecutor(core,body,extensions(body).persistent_filters)
    assert wrapper.run(query).iloc[0,0] == sum(r["priority"]=="Hot" for r in selected)
    # Group context is reset; an independent call on the same core retains only RLS.
    assert core.run(query).iloc[0,0] == sum(r["priority"]=="Hot" for r in rows)
    assert before.get("web_extensions") is None and len(materialize_dataframe(contracts["fab_process_move"]))==600


@pytest.mark.parametrize("change",["type","source","operator","operator_shape","empty","depth","budget","forged_type"])
def test_invalid_filter_group_is_rejected_without_mutation(change):
    from ai4bi_web_api.filters import filter_command
    from ai4bi_web_api.errors import AppError
    body,contracts=template("fab")
    before=copy.deepcopy(body)
    raw=grouped_filter_payload()
    leaf=raw["expression"]["children"][1]["children"][1]
    if change=="type":leaf["value"]="5 OR 1=1"
    elif change=="source":leaf["block_id"]="different"
    elif change=="operator":leaf["operator"]="raw_sql"
    elif change=="operator_shape":leaf["operator"]=["or"]
    elif change=="empty":raw["expression"]["children"]=[]
    elif change=="forged_type":leaf["data_type"]="string"
    elif change=="budget":raw["expression"]["children"]=[copy.deepcopy(raw["expression"])]*40
    else:
        for _ in range(5):raw["expression"]={"operator":"or","children":[copy.deepcopy(leaf),raw["expression"]]}
    with pytest.raises(AppError):filter_command(body,"add_filter",{"filter":raw},contracts)
    assert body==before


def test_filter_group_null_and_sql_literal_remain_typed_predicates():
    from ai4bi_web_api.filters import filter_command
    from ai4bi_web_api.report_extensions import report_executor
    from ai4bi.report.models import ExecutableReportSpec
    body,contracts=template("fab")
    contracts=copy.deepcopy(contracts)
    contracts["fab_process_move"].data_source.records[0]["step_name"]=None
    raw=grouped_filter_payload()
    raw["expression"]["children"]=[
        {"block_id":"fab_process_move","column_name":"step_name","operator":"is_null","value":None},
        {"block_id":"fab_process_move","column_name":"step_name","operator":"eq","value":"' OR 1=1 --"}]
    body=filter_command(body,"add_filter",{"filter":raw},contracts)
    executor,_=report_executor(body,contracts)
    query=ExecutableReportSpec.from_dict(body).pages["main"].visuals["kpi_moves"].query
    assert executor.run(query).iloc[0,0]==1
    # SUM over no matching rows remains NULL, not a fabricated zero.
    import pandas as pd
    raw["expression"]={"operator":"and","children":[
        {"block_id":"fab_process_move","column_name":"step_name","operator":"eq","value":"Etch"},
        {"block_id":"fab_process_move","column_name":"step_name","operator":"eq","value":"Lithography"}]}
    clean_body,_=template("fab")
    empty=filter_command(clean_body,"add_filter",{"filter":raw},contracts)
    executor,_=report_executor(empty,contracts)
    assert pd.isna(executor.run(query).iloc[0,0])


def test_drill_null_path_uses_null_predicate_and_original_value():
    from ai4bi_web_api.drilling import apply_drill
    from ai4bi.report.models import ExecutableReportSpec
    from ai4bi.analysis.executor import Executor
    body,contracts = template("fab")
    visual = ExecutableReportSpec.from_dict(body).pages["main"].visuals["bar_qt_step"]
    visual.visualization.extra["drill_hierarchy"] = ["step_name","tool_id"]
    contracts = copy.deepcopy(contracts)
    record = contracts["fab_process_move"].data_source.records[0]
    record["step_name"] = None
    _,config = apply_drill(visual.query,visual.visualization,contracts)
    config["path"] = [{"column":"step_name","value":None}]
    query,_ = apply_drill(visual.query,visual.visualization,contracts,config)
    frame = Executor(extra_contracts=contracts).run(query)
    assert len(frame) == 1
    assert frame.iloc[0]["tool_id"] == record["tool_id"]
    assert frame.iloc[0,1] == record["queue_time_hr"]


def test_assistant_drill_executor_and_materialized_population_agree():
    from ai4bi_web_api.drilling import assistant_drill_executor,assistant_source_contracts
    from ai4bi_web_api.report_extensions import report_executor
    from ai4bi.query_spec import VisualQuerySpec,BlockRef,MetricRef
    from ai4bi.report.models import ExecutableReportSpec
    from ai4bi.blocks.datastore import materialize_dataframe
    body,contracts = template("fab")
    vid = "bar_qt_step"
    body["pages"]["main"]["visuals"][vid]["visualization"]["extra"]["drill_hierarchy"] = ["step_name","tool_id"]
    original = copy.deepcopy(body)
    state = {"block_id":"fab_process_move","hierarchy":["step_name","tool_id"],"field_types":["string","string"],"path":[{"column":"step_name","value":"Etch"}]}
    executor,enriched = report_executor(body,contracts,page_id="main",visual_id=vid)
    drilled,context = assistant_drill_executor(executor,body,enriched,vid,{vid:state})
    report = ExecutableReportSpec.from_dict(body)
    assert "tool_id" in drilled.run(report.pages["main"].visuals[vid].query).columns
    aggregate = VisualQuerySpec("adhoc",[BlockRef("fab_process_move")],metrics=[MetricRef("fab_process_move","move_count","moves")])
    assert drilled.run(aggregate).iloc[0,0] == 100
    assert drilled.run_with_metadata(aggregate)[0].iloc[0,0] == 100
    assert drilled.run(report.pages["main"].visuals["kpi_moves"].query).iloc[0,0] == 600
    scoped = assistant_source_contracts(executor,enriched,context)
    assert len(materialize_dataframe(scoped["fab_process_move"])) == 100
    assert scoped["fab_process_move"].data_source.row_count == 100
    assert len(materialize_dataframe(contracts["fab_process_move"])) == 600
    empty = assistant_source_contracts(executor,enriched,{**context,"path":[{"column":"step_name","value":"missing"}]})
    empty_frame = materialize_dataframe(empty["fab_process_move"])
    assert empty_frame.empty and "tool_id" in empty_frame.columns
    assert body == original
    # This real NL handler reads dataframes directly and receives no Executor.
    from ai4bi.ai.nl2proposal import NL2ProposalService
    from ai4bi_web_api.core import clean
    lithography = assistant_source_contracts(executor,enriched,{**context,"path":[{"column":"step_name","value":"Lithography"}]})
    answer = NL2ProposalService().propose("bottleneck over time",report,vid,contracts=lithography,executor=None,conversation_state={})
    table = clean(answer.result_table)
    assert table["row_count"] > 0
    records = contracts["fab_process_move"].data_source.records
    for row in table["rows"]:
        start,end = row["period"].split("/")
        groups = {}
        for record in records:
            if record["step_name"] == "Lithography" and start <= record["event_date"] <= end:
                groups.setdefault(record["tool_id"],[]).append(record["queue_time_hr"])
        expected = {tool:sum(values)/len(values) for tool,values in groups.items()}
        assert row["bottleneck"] in expected
        assert row["value"] == round(max(expected.values()),3)
        assert row["value"] == round(expected[row["bottleneck"]],3)
    # Persistent conditions also constrain the dataframe population.
    combined = copy.deepcopy(body)
    combined["web_extensions"] = {"persistent_filters":[{"filter_id":"priority","scope":"report","block_id":"fab_process_move","column_name":"priority","operator":"eq","value":"Hot","data_type":"string"}]}
    filtered,enriched = report_executor(combined,contracts,page_id="main",visual_id=vid)
    scoped = assistant_source_contracts(filtered,enriched,context)
    expected_count = sum(r["step_name"] == "Etch" and r["priority"] == "Hot" for r in records)
    assert expected_count > 0
    assert len(materialize_dataframe(scoped["fab_process_move"])) == expected_count
    wrapped,_ = assistant_drill_executor(filtered,combined,enriched,vid,{vid:state})
    assert wrapped.run(aggregate).iloc[0,0] == expected_count


def test_explicit_page_order_survives_storage_and_controls_export(tmp_path):
    import pandas as pd
    import openpyxl
    from ai4bi_web_api.exports import export_snapshot
    body, contracts = template("fab")
    visual = copy.deepcopy(body["pages"]["main"]["visuals"]["kpi_moves"])
    visual["component_id"] = "first_moves"
    visual["visualization"]["title"] = "First page moves"
    body["pages"]["z_first"] = {"page_id":"z_first", "title":"First", "visuals":{"first_moves":visual}, "visual_order":["first_moves"]}
    body["web_extensions"] = {"page_order":["z_first","main"]}
    body = validate_report(body, contracts)
    store = Store(tmp_path / "data")
    try:
        ids = store.create_workspace("Pages", body, "page-order-test", "fab")
        for contract in contracts.values():
            store.publish_dataset(ids["workspace_id"], contract.model_dump(mode="json"), pd.DataFrame(contract.data_source.records))
        snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 1, {"format":"xlsx"})
        # Simulate the sorted-key persistence/worker encoding that used to erase order.
        snapshot = json.loads(json.dumps(snapshot, sort_keys=True))
        assert list(snapshot["report"]["pages"]) == ["main", "z_first"]
        assert list(run_query(store.root, snapshot)["visuals"])[0] == "first_moves"
        destination = tmp_path / "export"
        destination.mkdir()
        export_snapshot(store.root, snapshot, destination)
        book = openpyxl.load_workbook(destination / "export.xlsx", read_only=True)
        try:
            assert book.sheetnames[1] == "First page moves"
        finally:
            book.close()
    finally:
        store.close()


def test_exploration_page_is_frozen_and_other_pages_export_unfiltered(tmp_path):
    import pandas as pd
    import openpyxl
    from pypdf import PdfReader
    from ai4bi_web_api.report_extensions import duplicate_page
    from ai4bi_web_api.exports import export_snapshot
    from ai4bi_web_api.errors import AppError
    report,contracts = template("fab")
    report = validate_report(duplicate_page(report,"main"),contracts)
    copied = report["web_extensions"]["page_order"][1]
    source = next(vid for vid,v in report["pages"]["main"]["visuals"].items() if any(d["column_name"] == "step_name" for d in v["query"]["dimensions"]))
    copied_kpi = report["pages"][copied]["visual_order"][report["pages"]["main"]["visual_order"].index("kpi_moves")]
    store = Store(tmp_path/"data")
    try:
        ids = store.create_workspace("Scope",report,"create-scope-test","fab")
        for contract in contracts.values():
            store.publish_dataset(ids["workspace_id"],contract.model_dump(mode="json"),pd.DataFrame(contract.data_source.records))
        predicate = {"source_visual_id":source,"block_id":"fab_process_move","column_name":"step_name","operator":"eq","value":"Etch"}
        snapshot = make_snapshot(store,ids["workspace_id"],ids["report_id"],1,{"filters":[predicate],"format":"json"})
        assert snapshot["exploration_page_id"] == "main"  # Compatible inference for old callers.
        result = run_query(store.root,snapshot)
        assert list(result["visuals"]["kpi_moves"]["rows"][0].values()) == [100]
        assert list(result["visuals"][copied_kpi]["rows"][0].values()) == [600]
        assert len(result["visuals"][source]["rows"]) == 6
        legacy = copy.deepcopy(snapshot)
        del legacy["exploration_page_id"]
        def data(visuals):
            return {vid:{key:v[key] for key in ("status","rows","columns","row_count")} for vid,v in visuals.items()}
        assert data(run_query(store.root,legacy)["visuals"]) == data(result["visuals"])
        destination = tmp_path/"exports"
        destination.mkdir()
        export_snapshot(store.root,snapshot,destination)
        exported = json.loads((destination/"export.json").read_text(encoding="utf-8"))["analysis"]
        assert exported["exploration_page_id"] == "main" and data(exported["visuals"]) == data(result["visuals"])
        export_snapshot(store.root,{**snapshot,"format":"xlsx"},destination)
        book = openpyxl.load_workbook(destination/"export.xlsx",read_only=True)
        try:
            rows = list(book["來源與版本"].values)
            metadata = dict(zip(rows[0],rows[1]))
            assert metadata["exploration_page_id"] == "main"
            assert json.loads(metadata["exploration_filters"]) == [predicate]
        finally:
            book.close()
        export_snapshot(store.root,{**snapshot,"format":"pdf"},destination)
        assert "Exploration page: main" in PdfReader(destination/"export.pdf").pages[0].extract_text()
        def remove_page(body):
            del body["pages"]["main"]
            body["web_extensions"]["page_order"] = [copied]
            return validate_report(body,contracts)
        store.command(ids["workspace_id"],ids["report_id"],{"base_revision":1,"idempotency_key":"remove-source-page","command_type":"replace_report"},remove_page)
        assert data(run_query(store.root,snapshot)["visuals"]) == data(result["visuals"])
        with pytest.raises(AppError,match="探索頁面"):
            make_snapshot(store,ids["workspace_id"],ids["report_id"],2,{"filters":[predicate],"exploration_page_id":"main"})
    finally:
        store.close()


@pytest.mark.parametrize("options", [
    {"filters":[{"value":1}]},
    {"filters":[{"source_visual_id":"a"},{"source_visual_id":"b"}]},
    {"filters":[{"source_visual_id":"a"}],"exploration_page_id":"second"},
    {"filters":[],"exploration_page_id":"missing"},
    {"filters":[{"source_visual_id":"missing"}]},
])
def test_ambiguous_or_invalid_exploration_scope_rejected(options):
    from ai4bi_web_api.bookmarks import exploration_page
    from ai4bi_web_api.errors import AppError
    body = {"pages":{"first":{"visuals":{"a":{}}},"second":{"visuals":{"b":{}}}}}
    with pytest.raises(AppError):
        exploration_page(body,options)


def test_source_free_exploration_requires_or_infers_one_page():
    from ai4bi_web_api.bookmarks import exploration_page
    body = {"pages":{"first":{"visuals":{"a":{}}},"second":{"visuals":{"b":{}}}}}
    assert exploration_page(body,{"filters":[{"value":1}],"visual_ids":["b"]}) == "second"
    assert exploration_page(body,{"filters":[{"value":1}],"exploration_page_id":"first"}) == "first"


@pytest.mark.parametrize("order", [[], ["main", "main"], ["missing"]])
def test_page_order_must_be_an_exact_permutation(order):
    from ai4bi_web_api.errors import AppError
    body, contracts = template("blank")
    body["web_extensions"] = {"page_order":order}
    with pytest.raises(AppError, match="頁面順序"):
        validate_report(body, contracts)


def test_core_page_addition_and_deletion_preserve_relative_order():
    from ai4bi_web_api.report_extensions import preserve_extensions, ordered_report
    source = {"pages":{"first":{},"second":{}}, "web_extensions":{"page_order":["second","first"]}}
    added = preserve_extensions({"pages":{"first":{},"third":{},"second":{}}}, source)
    assert list(ordered_report(added)["pages"]) == ["second", "first", "third"]
    deleted = preserve_extensions({"pages":{"third":{},"first":{}}}, added)
    assert list(ordered_report(deleted)["pages"]) == ["first", "third"]


def test_parameters_use_snapshot_and_preserve_ai_proposals(tmp_path, monkeypatch):
    import pandas as pd
    monkeypatch.setenv("LLM_MODE", "mock")
    store = Store(tmp_path / "data")
    try:
        report, contracts = template("fab")
        report["web_extensions"] = {"version": 1, "parameters": {"discount": .1},
            "parameter_ranges": {"discount": {"minimum":0., "maximum":1., "step":.01}},
            "scenarios":[{"scenario_id":"baseline","name":"Baseline","parameters":{"discount":.1}}],
            "bookmarks":[{"bookmark_id":"main-view","name":"Main","view":{"page_id":"main","selected_visual_id":None,"filters":[]},"fields":[]}],
            "persistent_filters":[{"filter_id":"all-moves","scope":"report","block_id":"fab_process_move","column_name":"move_count","operator":"gte","value":1,"data_type":"integer"}],
            "calculated_metrics": [{"block_id": "fab_process_move", "name": "discounted_moves",
                                    "formula": "SUM(move_count) * (1 - @discount)"}]}
        report["pages"]["main"]["visuals"]["kpi_moves"]["query"]["metrics"][0].update(metric_name="discounted_moves", alias="discounted_moves")
        report = validate_report(report, contracts)
        assert all(m.name != "discounted_moves" for m in contracts["fab_process_move"].metrics)
        ids = store.create_workspace("What-if", report, "create-what-if", "fab")
        for contract in contracts.values():
            store.publish_dataset(ids["workspace_id"], contract.model_dump(mode="json"), pd.DataFrame(contract.data_source.records))
        old = make_snapshot(store, ids["workspace_id"], ids["report_id"], 1, {"visual_ids": ["kpi_moves"]})
        request = {"idempotency_key": "change-discount", "base_revision": 1, "command_type": "replace_report"}
        def change(body):
            body["web_extensions"]["parameters"]["discount"] = .5
            return validate_report(body, contracts)
        store.command(ids["workspace_id"], ids["report_id"], request, change)
        current = make_snapshot(store, ids["workspace_id"], ids["report_id"], 2, {"visual_ids": ["kpi_moves"]})
        assert old["snapshot_id"] != current["snapshot_id"]
        assert run_query(store.root, old)["visuals"]["kpi_moves"]["rows"][0]["discounted_moves"] == 540
        assert run_query(store.root, current)["visuals"]["kpi_moves"]["rows"][0]["discounted_moves"] == 300
        assistant = {**current, "prompt": "rename this chart to Scenario", "selected_component_id": "kpi_moves"}
        candidate = run_assistant(store.root, assistant)["candidate_report"]
        assert candidate["web_extensions"]["parameters"] == {"discount": .5}
        assert candidate["web_extensions"]["parameter_ranges"] == report["web_extensions"]["parameter_ranges"]
        assert candidate["web_extensions"]["scenarios"] == report["web_extensions"]["scenarios"]
        assert candidate["web_extensions"]["bookmarks"] == report["web_extensions"]["bookmarks"]
        assert candidate["web_extensions"]["persistent_filters"] == report["web_extensions"]["persistent_filters"]
        undo = {"idempotency_key": "undo-discount", "base_revision": 2, "command_type": "undo"}
        restored = store.command(ids["workspace_id"], ids["report_id"], undo, lambda value: value)
        assert restored["report"]["web_extensions"]["parameters"] == {"discount": .1}
    finally:
        store.close()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "1); DROP TABLE data", True])
def test_non_numeric_or_non_finite_parameters_rejected(value):
    with pytest.raises(ValueError):
        extensions({"web_extensions": {"parameters": {"discount": value}}})


def test_unused_invalid_calculation_is_rejected():
    report, contracts = template("fab")
    report["web_extensions"] = {"calculated_metrics": [
        {"block_id": "fab_process_move", "name": "bad", "formula": "SUM(move_count); DROP TABLE x"}]}
    with pytest.raises(QueryPlanningError):
        validate_report(copy.deepcopy(report), contracts)


@pytest.mark.parametrize("limits,value", [
    ({"minimum":0.,"maximum":0.,"step":.1},0.),
    ({"minimum":1.,"maximum":0.,"step":.1},.5),
    ({"minimum":0.,"maximum":1.,"step":0.},.5),
    ({"minimum":0.,"maximum":1.,"step":2.},.5),
    ({"minimum":0.,"maximum":1.,"step":float("inf")},.5),
    ({"minimum":False,"maximum":1.,"step":.1},.5),
    ({"minimum":0.,"maximum":1.,"step":.1},1.1),
    ({"minimum":-1e308,"maximum":1e308,"step":1.},0.),
])
def test_invalid_parameter_ranges_rejected(limits, value):
    with pytest.raises(ValueError):
        extensions({"web_extensions":{"parameters":{"discount":value},"parameter_ranges":{"discount":limits}}})


def test_range_requires_parameter_but_not_step_alignment():
    limits = {"minimum":0.,"maximum":1.,"step":.1}
    with pytest.raises(ValueError):
        extensions({"web_extensions":{"parameter_ranges":{"missing":limits}}})
    assert extensions({"web_extensions":{"parameters":{"p":.25},"parameter_ranges":{"p":limits}}}).parameters["p"] == .25
    assert extensions({}).parameter_ranges == {}


@pytest.mark.parametrize("scenarios", [
    [{"scenario_id":"a","name":"A","parameters":{}}],
    [{"scenario_id":"a","name":" ","parameters":{"p":1.}}],
    [{"scenario_id":"a","name":"A","parameters":{"p":True}}],
    [{"scenario_id":"a","name":"A","parameters":{"p":float("nan")}}],
    [{"scenario_id":"a","name":"A","parameters":{"bad key":1.}}],
    [{"scenario_id":"a","name":"A","parameters":{"p":1.}},{"scenario_id":"a","name":"B","parameters":{"p":2.}}],
    [{"scenario_id":"a","name":"A","parameters":{"p":1.}},{"scenario_id":"b","name":"a","parameters":{"p":2.}}],
    [{"scenario_id":str(i),"name":str(i),"parameters":{"p":1.}} for i in range(31)],
])
def test_scenario_contract_rejects_invalid_or_ambiguous_snapshots(scenarios):
    with pytest.raises(ValueError):
        extensions({"web_extensions":{"scenarios":scenarios}})


@pytest.mark.parametrize("value,operator", [(None,"is_null"),(False,"eq"),(2,"eq"),(2.5,"gte"),('2',"eq"),([1,2],"in"),(["a","b"],"between")])
def test_bookmark_filter_values_preserve_original_types(value,operator):
    from ai4bi_web_api.bookmarks import ExplorationFilter
    result = ExplorationFilter.model_validate({"block_id":"source","column_name":"column","operator":operator,"value":value}).model_dump()
    assert result["value"] == value and type(result["value"]) is type(value)


@pytest.mark.parametrize("value", [float("nan"),float("inf"),{"sql":"x"},[[1]],list(range(101))])
def test_bookmark_predicates_reject_nonfinite_nested_and_oversized_values(value):
    from ai4bi_web_api.bookmarks import ExplorationFilter
    with pytest.raises(ValueError):
        ExplorationFilter.model_validate({"block_id":"source","column_name":"column","operator":"in" if isinstance(value,list) else "eq","value":value})


def test_bookmark_signatures_are_complete_and_names_unique():
    from ai4bi_web_api.bookmarks import Bookmark
    item = {"bookmark_id":"a","name":"A","view":{"page_id":"main","filters":[{"block_id":"source","column_name":"column","operator":"eq","value":1}]},"fields":[]}
    with pytest.raises(ValueError):
        Bookmark.model_validate(item)
    item["fields"] = [{"block_id":"source","column_name":"column","data_type":"integer"}]
    Bookmark.model_validate(item)
    with pytest.raises(ValueError):
        extensions({"web_extensions":{"bookmarks":[item,{**item,"bookmark_id":"b","name":"a"}]}})


def test_saved_scenario_survives_store_restart(tmp_path):
    from ai4bi_web_api.report_extensions import scenario_command
    report, contracts = template("blank")
    report["web_extensions"] = {"parameters":{"p":.1,"q":2.}}
    store = Store(tmp_path / "data")
    try:
        ids = store.create_workspace("Scenarios",validate_report(report,contracts),"restart-scenario","blank")
        saved = store.command(ids["workspace_id"],ids["report_id"],
            {"idempotency_key":"save-scenario","base_revision":1,"command_type":"save_scenario"},
            lambda body:validate_report(scenario_command(body,"save_scenario",{"name":"Base"}),contracts))
    finally:
        store.close()
    reopened = Store(tmp_path / "data")
    try:
        assert reopened.report(ids["workspace_id"],ids["report_id"])["report"]["web_extensions"] == saved["report"]["web_extensions"]
    finally:
        reopened.close()


@pytest.mark.parametrize("kind", ["parameter", "metric"])
def test_referenced_deletion_rolls_back_then_unused_deletion_can_undo(tmp_path, kind):
    report, contracts = template("fab")
    report["web_extensions"] = {"parameters":{"discount":.1},
        "parameter_ranges":{"discount":{"minimum":0.,"maximum":1.,"step":.01}},
        "calculated_metrics":[{"block_id":"fab_process_move","name":"adjusted",
                               "formula":"SUM(move_count) * (1 - @discount)"}]}
    metric = report["pages"]["main"]["visuals"]["kpi_moves"]["query"]["metrics"][0]
    metric.update(metric_name="adjusted",alias="adjusted")
    report = validate_report(report, contracts)
    store = Store(tmp_path / "data")
    try:
        ids = store.create_workspace("Delete",report,"create-delete","fab")
        def command(key, revision, transform, command_type="replace_report"):
            return store.command(ids["workspace_id"],ids["report_id"],
                {"idempotency_key":key,"base_revision":revision,"command_type":command_type},transform)
        def remove(body):
            extra = body["web_extensions"]
            if kind == "parameter":
                extra["parameters"].pop("discount")
                extra["parameter_ranges"].pop("discount")
            else:
                extra["calculated_metrics"] = []
            return validate_report(body,contracts)
        with pytest.raises((QueryPlanningError, ValueError)):
            command("invalid-delete",1,remove)
        def unlink(body):
            if kind == "parameter":
                body["web_extensions"]["calculated_metrics"][0]["formula"] = "SUM(move_count)"
            else:
                body["pages"]["main"]["visuals"]["kpi_moves"]["query"]["metrics"][0]["metric_name"] = "move_count"
            return validate_report(body,contracts)
        # Revision 1 remains usable after rejection: no partial mutation or history entry.
        unlinked = command("unlink",1,unlink)
        deleted = command("delete",2,remove)
        assert deleted["revision"] == 3
        restored = command("undo-delete",3,lambda body:body,"undo")
        assert restored["report"]["web_extensions"] == unlinked["report"]["web_extensions"]
        assert restored["report"]["pages"] == unlinked["report"]["pages"]
    finally:
        store.close()
