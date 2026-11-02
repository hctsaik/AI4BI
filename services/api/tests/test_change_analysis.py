"""Numerical and failure-boundary checks against the actual pinned helper."""
import copy
from datetime import date, datetime

import pandas as pd
import pytest

from ai4bi.query_spec import BlockRef, MetricRef, VisualQuerySpec
from ai4bi_web_api.change_analysis import compare
from ai4bi_web_api.errors import AppError
from test_workspace_api import client, workspace, wait_job, command


class Executor:
    def __init__(self, ratio=False):
        self.ratio = ratio
        self.calls = []
        self.data = pd.DataFrame([
            ("2026-08-25", "A", 20., 100.),
            ("2026-08-31", "A", 80., 100.),
            ("2026-09-01", "A", 90., 300.),
            ("2026-09-06", "B", 60., 100.),
            ("2026-09-07", "B", 999., 100.),
        ], columns=["day", "current", "numerator", "denominator"])

    def run(self, spec):
        self.calls.append(copy.deepcopy(spec))
        lower, upper = spec.filters[-2:]
        data = self.data[self.data.day.between(lower.value, upper.value)]
        alias = spec.metrics[0].alias
        if spec.dimensions:
            grouped = data.groupby(spec.dimensions[0].column_name, dropna=False)[["numerator", "denominator"]].sum()
            values = grouped.numerator / grouped.denominator * 100 if self.ratio else grouped.numerator
            return values.rename(alias).rename_axis(spec.dimensions[0].alias).reset_index()
        value = data.numerator.sum() / data.denominator.sum() * 100 if self.ratio else data.numerator.sum()
        return pd.DataFrame({alias: [value]})


def run(executor, **changes):
    spec = VisualQuerySpec("change", [BlockRef("fact")], metrics=[MetricRef("fact", "metric", "current")])
    before = copy.deepcopy(spec)
    options = dict(block_id="fact", date_column="day", dimension_column="current", period="week",
                   anchor=date(2026, 9, 6), additive=not executor.ratio)
    options.update(changes)
    result = compare(executor, spec, **options)
    assert spec == before
    return result


def test_additive_windows_and_new_group_match_independent_totals():
    executor = Executor()
    original = executor.data.copy(deep=True)
    result = run(executor)
    assert result["windows"] == {"current": ["2026-08-31", "2026-09-06"], "previous": ["2026-08-24", "2026-08-30"]}
    assert (result["overall_current"], result["overall_previous"], result["overall_delta"]) == (230., 20., 210.)
    rows = {r["group"]: r for r in result["rows"]}
    assert rows["A"] == dict(group="A", current=170., previous=20., delta=150., delta_pct=750., contribution_pct=71.4)
    assert rows["B"] == dict(group="B", current=60., previous=0., delta=60., delta_pct=None, contribution_pct=28.6)
    pd.testing.assert_frame_equal(executor.data, original)


def test_weighted_overall_and_absent_group_are_not_summed_or_zero_filled():
    result = run(Executor(ratio=True))
    assert result["overall_current"] == 46.
    assert result["overall_previous"] == 20.
    assert result["overall_delta"] == 26.
    rows = {r["group"]: r for r in result["rows"]}
    assert rows["A"]["current"] == 42.5
    assert rows["A"]["delta"] == 22.5
    assert rows["B"]["previous"] is None and rows["B"]["delta"] is None
    assert all(r["contribution_pct"] is None for r in rows.values())


@pytest.mark.parametrize("ratio", [False, True])
def test_null_dimension_retains_identity(ratio):
    executor = Executor(ratio)
    executor.data.loc[executor.data.current == "A", "current"] = None
    result = run(executor)
    assert {r["group"] for r in result["rows"]} == {None, "B"}


@pytest.mark.parametrize("failed_call", [1, 2, 3, 4])
def test_each_governed_query_exception_becomes_explicit_failure(failed_call):
    executor = Executor(ratio=True)
    actual = executor.run
    def failing(spec):
        if len(executor.calls) + 1 == failed_call:
            executor.calls.append(spec)
            raise RuntimeError("private source details")
        return actual(spec)
    executor.run = failing
    with pytest.raises(AppError) as error:
        run(executor)
    assert error.value.code == "CHANGE_QUERY_FAILED"
    assert "private" not in str(error.value)


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), True, "12"])
def test_undefined_or_nonfinite_metrics_are_rejected(value):
    executor = Executor()
    actual = executor.run
    def invalid(spec):
        frame = actual(spec)
        frame[spec.metrics[0].alias] = value
        return frame
    executor.run = invalid
    with pytest.raises(AppError) as error:
        run(executor)
    assert error.value.code == "CHANGE_METRIC_UNDEFINED"


@pytest.mark.parametrize("options", [{"period": "calendar_month"}, {"anchor": datetime(2026, 9, 6)},
                                    {"anchor": date.min}, {"additive": 1}, {"dimension_column": "day"}])
def test_invalid_settings_fail_before_execution(options):
    executor = Executor()
    with pytest.raises(AppError) as error:
        run(executor, **options)
    assert error.value.code == "CHANGE_SETTINGS_INVALID"
    assert executor.calls == []


def test_empty_is_explicit():
    executor = Executor()
    executor.data = executor.data.iloc[:0]
    result = run(executor)
    assert result["status"] == "empty" and result["rows"] == []
    assert result["overall_delta"] is None


@pytest.mark.parametrize("metric,additive", [("good_die", True), ("weighted_yield_pct", False)])
def test_real_governed_executor_matches_independent_raw_aggregation(metric, additive):
    from ai4bi_web_api.core import template
    from ai4bi_web_api.report_extensions import report_executor
    body, contracts = template("fab")
    contracts = copy.deepcopy(contracts)
    contract = contracts["fab_wafer_yield"]
    original = contract.data_source.records[0]
    records = [
        {**original, "wafer_id": str(i), "test_date": day, "product_family": group,
         "good_die": good, "tested_die": tested}
        for i, (day, group, good, tested) in enumerate([
            ("2026-08-25", "A", 20, 100), ("2026-08-31", "A", 80, 100),
            ("2026-09-01", "A", 90, 300), ("2026-09-06", "B", 60, 100),
            ("2026-09-07", "B", 999, 1000),
        ])
    ]
    contract.data_source.records = records
    before = copy.deepcopy(contracts)
    executor, _ = report_executor(body, contracts, page_id="main")
    spec = VisualQuerySpec("governed_change", [BlockRef(contract.block_id)],
                           metrics=[MetricRef(contract.block_id, metric)])
    result = compare(executor, spec, block_id=contract.block_id, date_column="test_date",
                     dimension_column="product_family", period="week", anchor=date(2026, 9, 6), additive=additive)
    data = pd.DataFrame(records)
    def aggregate(start, end):
        part = data[data.test_date.between(start, end)]
        return part.good_die.sum() if additive else part.good_die.sum() / part.tested_die.sum() * 100
    assert result["overall_current"] == pytest.approx(aggregate("2026-08-31", "2026-09-06"))
    assert result["overall_previous"] == pytest.approx(aggregate("2026-08-24", "2026-08-30"))
    assert result["group_count"] == 2
    assert contracts == before


@pytest.mark.parametrize("malformation", ["missing_column", "duplicate_group", "too_many_groups"])
def test_incomplete_or_truncated_results_are_never_delivered(monkeypatch, malformation):
    executor = Executor()
    actual = executor.run
    if malformation == "too_many_groups":
        monkeypatch.setattr("ai4bi_web_api.change_analysis.MAX_GROUPS", 1)
    def changed(spec):
        frame = actual(spec)
        if malformation == "missing_column":
            return frame.drop(columns=[spec.metrics[0].alias])
        if malformation == "duplicate_group":
            return pd.concat([frame, frame], ignore_index=True)
        return frame
    executor.run = changed
    with pytest.raises(AppError) as error:
        run(executor)
    assert error.value.code == ("CHANGE_RESULT_LIMIT" if malformation == "too_many_groups" else "CHANGE_RESULT_INVALID")


def test_overflow_does_not_escape_as_nonfinite_json():
    executor = Executor()
    executor.data.loc[executor.data.day == "2026-08-25", "numerator"] = -1e308
    executor.data.loc[executor.data.day == "2026-08-31", "numerator"] = 1e308
    with pytest.raises(AppError) as error:
        run(executor)
    assert error.value.code == "CHANGE_METRIC_UNDEFINED"


def snapshot_fixture(*, policy="replace", anchor=None, ratio=False, dtype="date"):
    from ai4bi_web_api.core import template
    from ai4bi_web_api.publications import EXECUTION_CONTRACT
    from ai4bi_web_api.schemas import ChangeSettings
    body, contracts = template("fab")
    contracts = copy.deepcopy(contracts)
    block = contracts["fab_wafer_yield"]
    original = block.data_source.records[0]
    block.data_source.records = [{**original, "wafer_id": str(i), "test_date": day,
                                 "product_family": group, "good_die": n, "tested_die": d}
        for i, (day, group, n, d) in enumerate([
            ("2026-08-25", "A", 20, 100), ("2026-08-31", "A", 80, 100),
            ("2026-09-01", "A", 90, 300), ("2026-09-06", "B", 60, 100)])]
    next(c for c in block.columns if c.name == "test_date").data_type = dtype
    settings = ChangeSettings(block_id=block.block_id, metric_name="weighted_yield_pct" if ratio else "good_die",
                              date_column="test_date", dimension_column="product_family", period="week",
                              filter_policy=policy, anchor=anchor)
    snapshot = {**settings.model_dump(), "analysis_contract": "change-v2", "execution_contract": EXECUTION_CONTRACT,
                "report": body, "revision": 1, "snapshot_id": "fixed-test-snapshot", "exploration_page_id": "main",
                "selected_component_id": None, "filters": [], "drill_state": {}, "datasets": []}
    return snapshot, contracts


@pytest.mark.parametrize("ratio", [False, True])
@pytest.mark.parametrize("policy", ["keep", "replace"])
def test_snapshot_date_policy_and_auto_anchor(ratio, policy):
    from ai4bi_web_api.change_analysis import analyze_snapshot
    snapshot, contracts = snapshot_fixture(policy=policy, ratio=ratio)
    snapshot["filters"] = [dict(block_id="fab_wafer_yield", column_name="test_date", operator="gte", value="2026-08-31")]
    before = copy.deepcopy(snapshot)
    result = analyze_snapshot(snapshot, contracts)
    assert snapshot == before
    assert result["anchor"] == "2026-09-06" and result["timezone"] == "UTC"
    assert result["overall_current"] == (46. if ratio else 230.)
    assert result["overall_previous"] == (None if policy == "keep" and ratio else 0. if policy == "keep" else 20.)
    assert result["additive"] is not ratio
    assert result["metadata"]["anchor"] and result["metadata"]["gcur"]


def test_timestamp_utc_window_includes_last_day_and_excludes_next_day():
    from ai4bi_web_api.change_analysis import analyze_snapshot
    snapshot, contracts = snapshot_fixture(anchor="2026-09-06", dtype="timestamp")
    records = contracts["fab_wafer_yield"].data_source.records
    records[3]["test_date"] = "2026-09-07T07:59:59+08:00"
    records.append({**records[3], "wafer_id": "next", "test_date": "2026-09-07T08:00:00+08:00", "good_die": 999})
    result = analyze_snapshot(snapshot, contracts)
    assert result["overall_current"] == 230.
    assert result["overall_previous"] == 20.


def test_empty_filtered_anchor_is_explicit_and_does_not_fallback():
    from ai4bi_web_api.change_analysis import analyze_snapshot
    snapshot, contracts = snapshot_fixture()
    snapshot["filters"] = [dict(block_id="fab_wafer_yield", column_name="product_family", operator="eq", value="missing")]
    result = analyze_snapshot(snapshot, contracts)
    assert result["anchor"] is None and result["status"] == "empty" and result["rows"] == []


@pytest.mark.parametrize("field,value", [("date_column", "product_family"), ("metric_name", "missing"),
                                       ("dimension_column", "yield_pct"), ("anchor", "2026-02-30")])
def test_snapshot_rejects_incompatible_settings(field, value):
    from ai4bi_web_api.change_analysis import analyze_snapshot
    snapshot, contracts = snapshot_fixture()
    snapshot[field] = value
    with pytest.raises(AppError) as error:
        analyze_snapshot(snapshot, contracts)
    assert error.value.code == "CHANGE_SETTINGS_INVALID"


def test_http_change_job_executes_and_deduplicates(client):
    ids, path, _ = workspace(client)
    request = dict(block_id="fab_wafer_yield", metric_name="weighted_yield_pct", date_column="test_date",
                   dimension_column="product_family", period="week", base_revision=1,
                   exploration_page_id="main", idempotency_key="change-real-worker")
    accepted = client.post(path + "/analyses/change", json=request)
    assert accepted.status_code == 202, accepted.text
    assert client.post(path + "/analyses/change", json=request).json() == accepted.json()
    job = wait_job(client, accepted.json()["job_id"])
    assert job["status"] == "succeeded", job
    result = job["result"]
    assert result["analysis_contract"] == "change-v2" and result["additive"] is False
    from ai4bi_web_api.core import load_contracts
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi.blocks.datastore import materialize_dataframe
    captured = make_snapshot(client.app.state.store, ids["workspace_id"], ids["report_id"], 1, {})
    contracts = load_contracts(client.app.state.store.root, captured["datasets"])
    data = materialize_dataframe(contracts["fab_wafer_yield"])
    current = data[data.test_date.between(*result["windows"]["current"])]
    previous = data[data.test_date.between(*result["windows"]["previous"])]
    assert result["group_count"] == len(set(current.product_family) | set(previous.product_family))
    assert result["overall_current"] == pytest.approx(current.good_die.sum() / current.tested_die.sum() * 100)
    assert result["overall_previous"] == pytest.approx(previous.good_die.sum() / previous.tested_die.sum() * 100)
    assert all(row["contribution_pct"] is None for row in result["rows"])
    assert result["data_versions"]
    forbidden = client.post(path + "/analyses/change", json={**request, "additive": True})
    assert forbidden.status_code == 422


@pytest.mark.parametrize("field,value,code", [("analysis_contract", "change-v1", "CHANGE_INCOMPATIBLE"),
                                             ("execution_contract", "web-query-v0", "SNAPSHOT_RUNTIME_INCOMPATIBLE")])
def test_incompatible_runtime_rejected_before_source_reads(client, monkeypatch, field, value, code):
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.change_analysis import run_change
    ids, _, _ = workspace(client)
    snapshot = make_snapshot(client.app.state.store, ids["workspace_id"], ids["report_id"], 1, {"analysis_contract": "change-v2"})
    snapshot[field] = value
    monkeypatch.setattr("ai4bi_web_api.core.load_contracts", lambda *args: pytest.fail("Unexpected source read"))
    with pytest.raises(AppError) as error:
        run_change(client.app.state.store.root, snapshot)
    assert error.value.code == code


@pytest.mark.parametrize("policy", ["keep", "replace"])
@pytest.mark.parametrize("scope", ["report", "page", "visual"])
def test_persistent_date_and_group_filter_intersection(policy, scope):
    from ai4bi_web_api.change_analysis import analyze_snapshot
    from ai4bi_web_api.filters import filter_command
    snapshot, contracts = snapshot_fixture(policy=policy, anchor="2026-09-06")
    snapshot["selected_component_id"] = "bar_yield_prod"
    condition = {"scope": scope, "block_id": "fab_wafer_yield", "expression": {"operator": "and", "children": [
        dict(block_id="fab_wafer_yield", column_name="test_date", operator="gte", value="2026-08-31"),
        dict(block_id="fab_wafer_yield", column_name="product_family", operator="eq", value="A")]}}
    if scope != "report":
        condition["page_id"] = "main"
    if scope == "visual":
        condition["visual_id"] = "bar_yield_prod"
    snapshot["report"] = filter_command(snapshot["report"], "add_filter", {"filter": condition}, contracts)
    result = analyze_snapshot(snapshot, contracts)
    assert result["overall_current"] == 170.
    assert result["overall_previous"] == (0. if policy == "keep" else 20.)
    assert [row["group"] for row in result["rows"]] == ["A"]


def test_mixed_or_date_replacement_is_rejected_but_keep_remains_valid():
    from ai4bi_web_api.change_analysis import analyze_snapshot
    from ai4bi_web_api.filters import filter_command
    snapshot, contracts = snapshot_fixture(anchor="2026-09-06")
    condition = {"scope": "report", "block_id": "fab_wafer_yield", "expression": {"operator": "or", "children": [
        dict(block_id="fab_wafer_yield", column_name="test_date", operator="gte", value="2026-08-31"),
        dict(block_id="fab_wafer_yield", column_name="product_family", operator="eq", value="A")]}}
    snapshot["report"] = filter_command(snapshot["report"], "add_filter", {"filter": condition}, contracts)
    before = copy.deepcopy(snapshot)
    with pytest.raises(AppError) as error:
        analyze_snapshot(snapshot, contracts)
    assert error.value.code == "AMBIGUOUS_COMPARISON_FILTER" and snapshot == before
    snapshot["filter_policy"] = "keep"
    result = analyze_snapshot(snapshot, contracts)
    assert result["overall_current"] == 230. and result["overall_previous"] == 20.


def test_selected_query_filters_are_kept_and_having_does_not_trim_population():
    from ai4bi_web_api.change_analysis import analyze_snapshot
    snapshot, contracts = snapshot_fixture(anchor="2026-09-06")
    snapshot["selected_component_id"] = "bar_yield_prod"
    query = snapshot["report"]["pages"]["main"]["visuals"]["bar_yield_prod"]["query"]
    query["filters"] = [dict(block_id="fab_wafer_yield", column_name="product_family", operator="eq", value="A")]
    query["having"] = [dict(block_id="fab_wafer_yield", metric_name=query["metrics"][0]["metric_name"], operator="gt", value=999999.)]
    query["limit"] = 1
    result = analyze_snapshot(snapshot, contracts)
    assert result["overall_current"] == 170. and result["overall_previous"] == 20.


def test_report_calculated_metric_is_available_and_not_assumed_additive():
    from ai4bi_web_api.change_analysis import analyze_snapshot
    snapshot, contracts = snapshot_fixture(anchor="2026-09-06")
    snapshot["report"].setdefault("web_extensions", {}).update(version=1, calculated_metrics=[
        dict(block_id="fab_wafer_yield", name="custom_ratio", formula="SUM(good_die) / SUM(tested_die) * 100")])
    snapshot["metric_name"] = "custom_ratio"
    result = analyze_snapshot(snapshot, contracts)
    assert result["overall_current"] == 46. and result["additive"] is False


def test_bad_request_revision_and_idempotency_are_enforced(client):
    _, path, _ = workspace(client)
    request = dict(block_id="fab_wafer_yield", metric_name="good_die", date_column="test_date",
                   dimension_column="product_family", base_revision=99, idempotency_key="change-revision-test")
    assert client.post(path + "/analyses/change", json=request).status_code == 409
    request["base_revision"] = 1
    first = client.post(path + "/analyses/change", json=request)
    assert first.status_code == 202
    assert client.post(path + "/analyses/change", json={**request, "period": "year"}).status_code == 409
    assert wait_job(client, first.json()["job_id"])["status"] == "succeeded"


def test_real_sql_large_integer_keeps_single_unit_difference():
    from ai4bi_web_api.change_analysis import analyze_snapshot
    snapshot, contracts = snapshot_fixture(anchor="2026-09-06")
    original = contracts["fab_wafer_yield"].data_source.records[0]
    previous = 2**53 + 1
    contracts["fab_wafer_yield"].data_source.records = [
        {**original, "wafer_id": "before", "test_date": "2026-08-25", "good_die": previous},
        {**original, "wafer_id": "after", "test_date": "2026-09-06", "good_die": previous + 1},
    ]
    result = analyze_snapshot(snapshot, contracts)
    assert result["overall_previous"] == str(previous)
    assert result["overall_current"] == str(previous + 1)
    assert result["overall_delta"] == 1
    assert result["rows"][0]["delta"] == 1
    assert result["rows"][0]["contribution_pct"] == 100


def test_real_sql_sum_beyond_int64_and_negative_delta_remain_exact():
    from ai4bi_web_api.change_analysis import analyze_snapshot
    snapshot, contracts = snapshot_fixture(anchor="2026-09-06")
    original = contracts["fab_wafer_yield"].data_source.records[0]
    value = 2**62 + 1
    contracts["fab_wafer_yield"].data_source.records = [
        {**original, "wafer_id": str(i), "test_date": "2026-08-25" if i < 3 else "2026-09-06", "good_die": value}
        for i in range(5)
    ]
    result = analyze_snapshot(snapshot, contracts)
    assert result["overall_previous"] == str(value * 3)
    assert result["overall_current"] == str(value * 2)
    assert result["overall_delta"] == str(-value)
    assert result["rows"][0]["previous"] == str(value * 3)
    assert result["rows"][0]["delta"] == str(-value)


@pytest.mark.parametrize("missing", [False, True])
def test_decimal_values_and_missing_groups_do_not_coerce_to_float(missing):
    from decimal import Decimal
    executor = Executor()
    current = Decimal("9007199254740993.125000000000000001")
    previous = Decimal("9007199254740993.125")
    def exact(spec):
        suffix = spec.spec_id.rsplit("__", 1)[-1]
        is_current = suffix == "gcur"
        return pd.DataFrame({spec.dimensions[0].alias: ["A" if is_current or not missing else "B"],
                             spec.metrics[0].alias: [current if is_current else previous]})
    executor.run = exact
    result = run(executor)
    assert result["overall_current"] == str(current)
    assert result["overall_previous"] == str(previous)
    assert result["overall_delta"] == 1e-18
    if missing:
        rows = {r["group"]: r for r in result["rows"]}
        assert rows["A"]["current"] == str(current) and rows["A"]["previous"] == 0
        assert rows["B"]["current"] == 0 and rows["B"]["previous"] == str(previous)
    else:
        assert result["rows"][0]["delta"] == 1e-18


def test_real_sql_tied_groups_have_canonical_order_across_source_permutations():
    from ai4bi_web_api.change_analysis import analyze_snapshot
    snapshot, contracts = snapshot_fixture(anchor="2026-09-06")
    block = contracts["fab_wafer_yield"]
    original = block.data_source.records[0]
    records = [{**original, "wafer_id": str(i), "test_date": "2026-09-06", "product_family": group, "good_die": 10}
               for i, group in enumerate(["Z", None, "A", "M"])]
    results = []
    for values in [records, list(reversed(records)), records[2:] + records[:2]]:
        block.data_source.records = values
        results.append(analyze_snapshot(snapshot, contracts))
    assert results[0]["rows"] == results[1]["rows"] == results[2]["rows"]
    assert [r["group"] for r in results[0]["rows"]] == ["A", "M", "Z", None]


def test_exact_sql_projection_restores_context_after_success_and_failure():
    from ai4bi_web_api.report_extensions import report_executor
    snapshot, contracts = snapshot_fixture(anchor="2026-09-06")
    executor, _ = report_executor(snapshot["report"], contracts, page_id="main")
    spec = VisualQuerySpec("projection", [BlockRef("fab_wafer_yield")],
                           metrics=[MetricRef("fab_wafer_yield", "good_die", "value")])
    assert executor._exact_metric.get() is None
    with executor.exact_metric_output("value"):
        exact = executor.run(spec)
        assert exact.iloc[0]["value"] == "250"
    assert executor._exact_metric.get() is None
    assert executor.run(spec).iloc[0]["value"] == 250

    with pytest.raises(Exception):
        with executor.exact_metric_output("missing_alias"):
            executor.run(spec)
    assert executor._exact_metric.get() is None
    assert executor.run(spec).iloc[0]["value"] == 250


def saved_command(client, path, revision, kind, payload, *, key=None):
    from uuid import uuid4
    return command(client, path, revision, kind, payload, key=key or uuid4().hex)


def saved_payload(**changes):
    from ai4bi_web_api.schemas import ChangeSettings
    settings = ChangeSettings(block_id="fab_wafer_yield", metric_name="weighted_yield_pct", date_column="test_date",
                              dimension_column="product_family", period="week").model_dump()
    settings.update(changes)
    return dict(name="Saved change", page_id="main", selected_component_id="bar_yield_prod", settings=settings)


def test_saved_change_crud_history_and_idempotency(client):
    _, path, _ = workspace(client)
    first = saved_command(client, path, 1, "save_change_analysis", saved_payload(), key="change-save-history")
    assert first.status_code == 200, first.text
    assert saved_command(client, path, 1, "save_change_analysis", saved_payload(), key="change-save-history").json() == first.json()
    item = first.json()["report"]["web_extensions"]["change_analyses"][0]
    assert item["analysis_contract"] == "change-v2" and len(item["metric_signature"]) == 64
    update = {**saved_payload(period="month"), "analysis_id": item["analysis_id"]};update.pop("name")
    response = saved_command(client, path, 2, "update_change_analysis", update)
    assert response.status_code == 200, response.text
    assert response.json()["report"]["web_extensions"]["change_analyses"][0]["period"] == "month"
    assert saved_command(client, path, 3, "rename_change_analysis", dict(analysis_id=item["analysis_id"], name="Renamed")).status_code == 200
    removed = saved_command(client, path, 4, "delete_change_analysis", dict(analysis_id=item["analysis_id"]))
    assert removed.status_code == 200 and removed.json()["report"]["web_extensions"]["change_analyses"] == []
    restored = saved_command(client, path, 5, "undo", {})
    assert restored.status_code == 200
    assert restored.json()["report"]["web_extensions"]["change_analyses"][0]["name"] == "Renamed"
    redone = saved_command(client, path, 6, "redo", {})
    assert redone.status_code == 200 and redone.json()["report"]["web_extensions"]["change_analyses"] == []


def test_saved_change_snapshot_replays_after_draft_delete(client):
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.core import load_contracts
    from ai4bi_web_api.change_analysis import run_saved_analyses
    ids, path, _ = workspace(client)
    saved = saved_command(client, path, 1, "save_change_analysis", saved_payload()).json()
    item = saved["report"]["web_extensions"]["change_analyses"][0]
    store = client.app.state.store
    snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 2, {"exploration_page_id": "main"})
    before = copy.deepcopy(snapshot)
    contracts = load_contracts(store.root, snapshot["datasets"])
    first = run_saved_analyses(snapshot, contracts)
    assert saved_command(client, path, 2, "delete_change_analysis", dict(analysis_id=item["analysis_id"])).status_code == 200
    replay = run_saved_analyses(snapshot, contracts)
    assert snapshot == before
    for field in ("rows", "overall_current", "overall_previous", "overall_delta", "settings", "data_versions"):
        assert first[item["analysis_id"]][field] == replay[item["analysis_id"]][field]


def test_saved_change_page_copy_remaps_selection_and_prunes_removed_page(client):
    _, path, _ = workspace(client)
    saved = saved_command(client, path, 1, "save_change_analysis", saved_payload()).json()
    original = saved["report"]["web_extensions"]["change_analyses"][0]
    copied = saved_command(client, path, 2, "duplicate_page", {"page_id": "main"})
    assert copied.status_code == 200, copied.text
    body = copied.json()["report"]
    second = next(i for i in body["web_extensions"]["change_analyses"] if i["analysis_id"] != original["analysis_id"])
    assert second["selected_component_id"] in body["pages"][second["page_id"]]["visuals"]
    assert second["selected_component_id"] != original["selected_component_id"]
    del body["pages"][second["page_id"]]
    body["web_extensions"]["page_order"].remove(second["page_id"])
    removed = saved_command(client, path, 3, "replace_report", {"report": body})
    assert removed.status_code == 200, removed.text
    assert removed.json()["report"]["web_extensions"]["change_analyses"] == [original]


def test_saved_change_signature_detects_formula_change_and_update_repairs():
    from ai4bi_web_api.change_analysis import settings_command, validate_saved_analyses
    from ai4bi_web_api.report_extensions import extensions
    snapshot, contracts = snapshot_fixture()
    body = settings_command(snapshot["report"], "save_change_analysis", saved_payload(), contracts)
    definition = extensions(body).change_analyses[0]
    changed = copy.deepcopy(contracts)
    metric = next(m for m in changed["fab_wafer_yield"].metrics if m.name == "weighted_yield_pct")
    metric.formula = "SUM(good_die) / NULLIF(SUM(tested_die),0) * 10"
    with pytest.raises(AppError) as error:
        validate_saved_analyses(body, changed, [definition])
    assert error.value.code == "CHANGE_SETTINGS_INCOMPATIBLE"
    payload = {**saved_payload(), "analysis_id": definition.analysis_id};payload.pop("name")
    repaired = settings_command(body, "update_change_analysis", payload, changed)
    validate_saved_analyses(repaired, changed, extensions(repaired).change_analyses)
    assert extensions(repaired).change_analyses[0].metric_signature != definition.metric_signature


def test_saved_change_calculated_metric_signature_and_offline_metadata_repair():
    from ai4bi_web_api.change_analysis import settings_command, run_saved_analyses
    snapshot, contracts = snapshot_fixture(anchor="2026-09-06")
    snapshot["report"].setdefault("web_extensions", {}).update(calculated_metrics=[dict(
        block_id="fab_wafer_yield", name="custom", formula="SUM(good_die) / SUM(tested_die) * 100")])
    body = settings_command(snapshot["report"], "save_change_analysis", saved_payload(metric_name="custom", anchor="2026-09-06"), contracts)
    result = run_saved_analyses({**snapshot, "report": body}, contracts)
    aid = next(iter(result));assert result[aid]["overall_current"] == 46 and not result[aid]["additive"]
    renamed = settings_command(body, "rename_change_analysis", dict(analysis_id=aid, name="Offline rename"), {})
    removed = settings_command(renamed, "delete_change_analysis", dict(analysis_id=aid), {})
    assert removed["web_extensions"]["change_analyses"] == []


@pytest.mark.parametrize("format", ["json", "csv", "xlsx", "pdf"])
def test_saved_change_export_contains_complete_saved_results(client, format):
    _, path, _ = workspace(client)
    assert saved_command(client, path, 1, "save_change_analysis", saved_payload()).status_code == 200
    accepted = client.post(path + "/exports", json=dict(format=format, base_revision=2, idempotency_key="change-export-"+format))
    assert accepted.status_code == 202, accepted.text
    job = wait_job(client, accepted.json()["job_id"])
    assert job["status"] == "succeeded", job
    response = client.get("/api/v1/artifacts/" + accepted.json()["job_id"])
    assert response.status_code == 200
    import io
    if format in ("json", "csv"):
        if format == "json":
            content = response.json()
        else:
            import json, zipfile
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                content = json.loads(archive.read("analysis.json"))
                manifest = json.loads(archive.read("manifest.json"))
                entries = [entry for entry in manifest["tables"] if entry.get("kind") == "change_groups"]
                assert len(entries) == 1 and entries[0]["row_count"] == 5
                assert "contribution_pct" in archive.read(entries[0]["file"]).decode("utf-8-sig")
        item = next(iter(content["analysis"]["change_analyses"].values()))
        assert item["name"] == "Saved change" and item["group_count"] == len(item["rows"]) == 5
        assert item["execution_contract"] == "web-query-v7"
        assert item["settings"] == content["report"]["web_extensions"]["change_analyses"][0]
    elif format == "xlsx":
        book = pd.ExcelFile(io.BytesIO(response.content))
        sheets = [name for name in book.sheet_names if name.startswith("CH_")]
        assert len(sheets) == 2
        groups = pd.read_excel(book, next(name for name in sheets if name.endswith("groups")))
        assert len(groups) == 5 and "contribution_pct" in groups.columns
    else:
        from pypdf import PdfReader
        text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(response.content)).pages)
        assert "Saved change" in text and "contribution_pct" in text


def test_saved_change_limit_and_duplicate_names_leave_input_unchanged():
    from ai4bi_web_api.change_analysis import settings_command
    snapshot, contracts = snapshot_fixture()
    body = snapshot["report"]
    for index in range(30):
        body = settings_command(body, "save_change_analysis", {**saved_payload(), "name": f"Change {index}"}, contracts)
    before = copy.deepcopy(body)
    for name, code in [(" change 0 ", "DUPLICATE_CHANGE_SETTINGS"), ("Overflow", "CHANGE_SETTINGS_LIMIT")]:
        with pytest.raises(AppError) as error:
            settings_command(body, "save_change_analysis", {**saved_payload(), "name": name}, contracts)
        assert error.value.code == code
        assert body == before
    aid = body["web_extensions"]["change_analyses"][0]["analysis_id"]
    payload = {**saved_payload(period="quarter"), "analysis_id": aid}
    payload.pop("name")
    updated = settings_command(body, "update_change_analysis", payload, contracts)
    assert len(updated["web_extensions"]["change_analyses"]) == 30
    assert updated["web_extensions"]["change_analyses"][0]["period"] == "quarter"


def test_saved_change_validates_all_definitions_before_any_query(monkeypatch):
    from ai4bi_web_api import change_analysis
    snapshot, contracts = snapshot_fixture()
    body = change_analysis.settings_command(snapshot["report"], "save_change_analysis", saved_payload(), contracts)
    body = change_analysis.settings_command(body, "save_change_analysis", {**saved_payload(), "name": "Second"}, contracts)
    body["web_extensions"]["change_analyses"][1]["metric_signature"] = "0" * 64
    calls = []
    monkeypatch.setattr(change_analysis, "analyze_snapshot", lambda *args: calls.append(args))
    with pytest.raises(AppError) as error:
        change_analysis.run_saved_analyses({**snapshot, "report": body}, contracts)
    assert error.value.code == "CHANGE_SETTINGS_INCOMPATIBLE"
    assert calls == []


@pytest.mark.parametrize("field", ["test_date", "product_family"])
def test_saved_change_rejects_field_type_changes(field):
    from ai4bi_web_api.change_analysis import settings_command, validate_saved_analyses
    from ai4bi_web_api.report_extensions import extensions
    snapshot, contracts = snapshot_fixture()
    body = settings_command(snapshot["report"], "save_change_analysis", saved_payload(), contracts)
    column = next(c for c in contracts["fab_wafer_yield"].columns if c.name == field)
    column.data_type = "string" if field == "test_date" else "integer"
    with pytest.raises(AppError) as error:
        validate_saved_analyses(body, contracts, extensions(body).change_analyses)
    assert error.value.code == "CHANGE_SETTINGS_INCOMPATIBLE"


@pytest.mark.parametrize("active_index", [0, 1])
@pytest.mark.parametrize("ratio", [False, True])
@pytest.mark.parametrize("drilled", [False, True])
def test_saved_change_pages_match_independent_scoped_periods(active_index, ratio, drilled):
    from ai4bi_web_api.change_analysis import settings_command, run_saved_analyses
    from ai4bi_web_api.report_extensions import duplicate_page
    snapshot, contracts = snapshot_fixture(anchor="2026-09-06", ratio=ratio)
    records = contracts["fab_wafer_yield"].data_source.records
    records.extend([{**records[0], "wafer_id": "B-prev", "product_family": "B", "good_die": 30},
                    {**records[1], "wafer_id": "exclude", "good_die": 150}])
    snapshot["datasets"] = [dict(dataset_id=key, version="v1", contract=value.model_dump(mode="json"))
                            for key, value in contracts.items()]
    body = settings_command(snapshot["report"], "save_change_analysis", saved_payload(
        metric_name="weighted_yield_pct" if ratio else "good_die", anchor="2026-09-06"), contracts)
    body = duplicate_page(body, "main")
    definitions = body["web_extensions"]["change_analyses"]
    conditions = []
    for index, item in enumerate(definitions):
        visual = body["pages"][item["page_id"]]["visuals"][item["selected_component_id"]]
        visual["visualization"].setdefault("extra", {})["drill_hierarchy"] = ["product_family", "lot_id"]
        visual["query"]["filters"] = [dict(block_id="fab_wafer_yield", column_name="good_die", operator="gt", value=10)]
        conditions.extend([
            dict(filter_id=f"page_{index}", scope="page", page_id=item["page_id"], block_id="fab_wafer_yield",
                 column_name="product_family", data_type="string", operator="eq", value=["A", "B"][index]),
            dict(filter_id=f"visual_{index}", scope="visual", page_id=item["page_id"], visual_id=item["selected_component_id"],
                 block_id="fab_wafer_yield", column_name="good_die", data_type="integer", operator="lt", value=100),
        ])
        if drilled and index == active_index:
            # Both products pass this page; only the actual drill path removes the other one.
            conditions[-2].update(operator="in", value=["A", "B"])
    body["web_extensions"]["persistent_filters"] = conditions
    active = definitions[active_index]
    snapshot.update(report=body, exploration_page_id=active["page_id"],
                    filters=[dict(block_id="fab_wafer_yield", column_name="good_die", operator="gte", value=60)])
    if drilled:
        snapshot["drill_state"] = {active["selected_component_id"]:dict(block_id="fab_wafer_yield",
            hierarchy=["product_family", "lot_id"], field_types=["string", "string"],
            path=[dict(column="product_family", value=["A", "B"][active_index])])}
    before = copy.deepcopy(snapshot)
    results = run_saved_analyses(snapshot, contracts)
    assert snapshot == before
    frame = pd.DataFrame(records)
    for index, item in enumerate(definitions):
        result = results[item["analysis_id"]]
        expected = frame[(frame.product_family == ["A", "B"][index]) & (frame.good_die > 10) & (frame.good_die < 100)]
        if index == active_index:
            expected = expected[expected.good_die >= 60]
        values = []
        for lo, hi in [("2026-08-31", "2026-09-06"), ("2026-08-24", "2026-08-30")]:
            part = expected[expected.test_date.between(lo, hi)]
            values.append(None if ratio and part.empty else part.good_die.sum() / part.tested_die.sum() * 100 if ratio else part.good_die.sum())
        for key, value in zip(("overall_current", "overall_previous"), values):
            assert result[key] == (None if value is None else pytest.approx(value))
        delta = None if None in values else values[0] - values[1]
        assert result["overall_delta"] == (None if delta is None else pytest.approx(delta))
        assert result["group_count"] == 1 and result["rows"][0]["group"] == ["A", "B"][index]
        assert bool(result["filters"]) == (index == active_index)
        assert bool(result["drill_context"] and result["drill_context"]["path"]) == (drilled and index == active_index)
        assert result["settings"] == item


def test_saved_change_bookmark_replays_old_filter_after_current_filter_changes(client):
    from ai4bi_web_api.core import load_contracts
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.change_analysis import run_saved_analyses
    from ai4bi.blocks.datastore import materialize_dataframe
    ids, path, _ = workspace(client)
    assert saved_command(client, path, 1, "save_change_analysis", saved_payload()).status_code == 200
    condition = dict(scope="report", block_id="fab_wafer_yield", column_name="product_family", operator="eq", value="Logic-A")
    filtered = saved_command(client, path, 2, "add_filter", {"filter": condition})
    assert filtered.status_code == 200, filtered.text
    fid = filtered.json()["report"]["web_extensions"]["persistent_filters"][0]["filter_id"]
    captured = saved_command(client, path, 3, "save_bookmark", dict(name="Captured Logic-A",
        view=dict(page_id="main", selected_visual_id="bar_yield_prod", filters=[])))
    assert captured.status_code == 200, captured.text
    bid = captured.json()["report"]["web_extensions"]["bookmarks"][0]["bookmark_id"]
    assert saved_command(client, path, 4, "delete_filter", dict(filter_id=fid)).status_code == 200
    assert saved_command(client, path, 5, "add_filter", {"filter": {**condition, "value": "Logic-B"}}).status_code == 200
    store = client.app.state.store
    observed = []
    for bookmark_id, product in [(None, "Logic-B"), (bid, "Logic-A")]:
        snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 6,
                                 dict(exploration_page_id="main", filter_bookmark_id=bookmark_id))
        before = copy.deepcopy(snapshot)
        contracts = load_contracts(store.root, snapshot["datasets"])
        result = next(iter(run_saved_analyses(snapshot, contracts).values()))
        frame = materialize_dataframe(contracts["fab_wafer_yield"])
        frame = frame[frame.product_family == product].copy()
        frame["test_date"] = pd.to_datetime(frame.test_date)
        anchor = frame.test_date.max()
        expected = []
        for lo, hi in [(anchor-pd.Timedelta(days=6), anchor), (anchor-pd.Timedelta(days=13), anchor-pd.Timedelta(days=7))]:
            part = frame[frame.test_date.between(lo, hi)]
            expected.append(None if part.empty else part.good_die.sum()/part.tested_die.sum()*100)
        assert result["anchor"] == anchor.date().isoformat()
        assert result["rows"][0]["group"] == product and result["group_count"] == 1
        for field, value in zip(("overall_current", "overall_previous"), expected):
            assert result[field] == (None if value is None else pytest.approx(value))
        assert snapshot == before and result["filter_bookmark_id"] == bookmark_id
        observed.append(result)
    assert observed[0]["rows"] != observed[1]["rows"]
    assert observed[0]["data_versions"] == observed[1]["data_versions"]


def change_delivery_fixture(*, ratio=False, empty=False, huge=False):
    from ai4bi_web_api.change_analysis import settings_command, run_saved_analyses
    snapshot, contracts = snapshot_fixture(anchor="2026-09-06", ratio=ratio)
    if huge:
        records = contracts["fab_wafer_yield"].data_source.records
        contracts["fab_wafer_yield"].data_source.records = [
            {**records[0], "good_die": 2**53+1}, {**records[1], "good_die": 2**53+2}]
    if empty:
        snapshot["filters"] = [dict(block_id="fab_wafer_yield", column_name="product_family", operator="eq", value="absent")]
    snapshot["report"] = settings_command(snapshot["report"], "save_change_analysis", saved_payload(
        metric_name="weighted_yield_pct" if ratio else "good_die", anchor="2026-09-06"), contracts)
    result = {key: snapshot[key] for key in ("snapshot_id", "revision", "execution_contract")}
    result.update(data_versions={}, change_analyses=run_saved_analyses(snapshot, contracts))
    return snapshot["report"], result


@pytest.mark.parametrize("ratio", [False, True])
@pytest.mark.parametrize("empty", [False, True])
def test_change_delivery_accepts_complete_results_and_commit_receipt(ratio, empty):
    from ai4bi_web_api.change_analysis import delivery_checks, validate_delivery_checks
    body, result = change_delivery_fixture(ratio=ratio, empty=empty)
    before = copy.deepcopy(result)
    receipt = delivery_checks(body, result)
    validate_delivery_checks(body, receipt)
    assert result == before
    assert next(iter(receipt.values()))["status"] == ("empty" if empty else "ready")


def test_change_delivery_keeps_exact_large_integer_arithmetic():
    from ai4bi_web_api.change_analysis import delivery_checks
    body, result = change_delivery_fixture(huge=True)
    delivery_checks(body, result)
    analysis = next(iter(result["change_analyses"].values()))
    assert analysis["overall_delta"] == 1
    assert analysis["overall_previous"] == str(2**53+1)


@pytest.mark.parametrize("path,value", [
    (("analysis_id",), "wrong"), (("name",), "wrong"), (("page_id",), "wrong"),
    (("settings", "period"), "year"), (("period",), "month"),
    (("timezone",), "local"), (("filter_policy",), "keep"),
    (("data_versions",), {"other": "v2"}), (("snapshot_id",), "other"),
    (("revision",), 999), (("execution_contract",), "old"),
    (("group_count",), 1), (("status",), "empty"), (("additive",), 1),
    (("anchor",), "2026-09-07"), (("windows", "current"), ["2026-08-30", "2026-09-06"]),
    (("overall_delta",), 999), (("overall_current",), "230"),
    (("rows", 0, "delta"), None), (("rows", 0, "delta_pct"), 999),
    (("rows", 0, "contribution_pct"), 999), (("rows", 0, "current"), True),
    (("rows", 0, "current"), float("nan")), (("rows", 0, "current"), "1e10"),
])
def test_change_delivery_rejects_corrupted_results(path, value):
    from ai4bi_web_api.change_analysis import delivery_checks
    body, result = change_delivery_fixture()
    target = next(iter(result["change_analyses"].values()))
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(AppError) as error:
        delivery_checks(body, result)
    assert error.value.code == "CHANGE_DELIVERY_INVALID"


@pytest.mark.parametrize("mode", ["missing_analysis", "duplicate_group", "extra_analysis", "missing_value"])
def test_change_delivery_rejects_missing_extra_or_duplicate_content(mode):
    from ai4bi_web_api.change_analysis import delivery_checks
    body, result = change_delivery_fixture()
    analyses = result["change_analyses"]
    item = next(iter(analyses.values()))
    if mode == "missing_analysis":
        analyses.clear()
    elif mode == "extra_analysis":
        analyses["unknown"] = copy.deepcopy(item)
    elif mode == "missing_value":
        del item["overall_current"]
    else:
        item["rows"][1]["group"] = item["rows"][0]["group"]
    with pytest.raises(AppError) as error:
        delivery_checks(body, result)
    assert error.value.code == "CHANGE_DELIVERY_INVALID"


@pytest.mark.parametrize("field,value", [("settings_digest", "0"*64), ("analysis_contract", "change-v1"),
    ("group_count", True), ("group_count", 10001), ("anchor", "2026-02-30"), ("windows", None)])
def test_change_publication_receipt_rejects_tampering(field, value):
    from ai4bi_web_api.change_analysis import delivery_checks, validate_delivery_checks
    body, result = change_delivery_fixture()
    receipt = delivery_checks(body, result)
    next(iter(receipt.values()))[field] = value
    with pytest.raises(AppError) as error:
        validate_delivery_checks(body, receipt)
    assert error.value.code == "CHANGE_DELIVERY_INVALID"


def test_change_publication_replays_after_draft_delete_and_exports_fixed_results(client):
    _, path, _ = workspace(client)
    saved = saved_command(client, path, 1, "save_change_analysis", saved_payload())
    definition = saved.json()["report"]["web_extensions"]["change_analyses"][0]
    accepted = client.post(path+"/publications", json=dict(base_revision=2, idempotency_key="change-fixed-publish"))
    assert accepted.status_code == 202, accepted.text
    job = wait_job(client, accepted.json()["job_id"])
    assert job["status"] == "succeeded", job
    target = path+"/publications/"+job["result"]["publication_id"]
    detail = client.get(target).json()
    assert detail["checks"]["execution_contract"] == "web-query-v7"
    assert detail["checks"]["change_analyses"][definition["analysis_id"]]["group_count"] == 5
    assert saved_command(client, path, 2, "delete_change_analysis", dict(analysis_id=definition["analysis_id"])).status_code == 200
    assert client.get(target).json()["report"]["web_extensions"]["change_analyses"] == [definition]
    queried = client.post(target+"/queries", json=dict(base_revision=2, idempotency_key="change-fixed-query", include_change=True))
    query = wait_job(client, queried.json()["job_id"])
    assert query["status"] == "succeeded", query
    original = query["result"]["change_analyses"][definition["analysis_id"]]
    exported = client.post(target+"/exports", json=dict(base_revision=2, idempotency_key="change-fixed-export", format="json"))
    export = wait_job(client, exported.json()["job_id"])
    assert export["status"] == "succeeded", export
    document = client.get("/api/v1/artifacts/"+export["result"]["artifact_id"]).json()
    replay = document["analysis"]["change_analyses"][definition["analysis_id"]]
    for field in ("rows", "settings", "overall_current", "overall_previous", "overall_delta", "data_versions"):
        assert replay[field] == original[field]


def test_change_v5_snapshot_is_rejected_before_reading_sources(monkeypatch, tmp_path):
    from ai4bi_web_api import core
    snapshot, _ = snapshot_fixture()
    snapshot["execution_contract"] = "web-query-v5"
    monkeypatch.setattr(core, "load_contracts", lambda *args: pytest.fail("Old snapshot read data"))
    with pytest.raises(AppError) as error:
        core.run_query(tmp_path, snapshot)
    assert error.value.code == "SNAPSHOT_RUNTIME_INCOMPATIBLE"


@pytest.mark.parametrize("format", ["json", "csv", "xlsx", "pdf"])
@pytest.mark.parametrize("kind", ["huge", "decimal", "long", "empty"])
def test_change_export_projection_preserves_full_rows_and_exact_values(tmp_path, monkeypatch, format, kind):
    import io, json, zipfile, csv
    from decimal import Decimal
    from ai4bi_web_api import exports
    from ai4bi_web_api.core import clean
    from ai4bi_web_api.change_analysis import settings_command, run_saved_analyses
    if kind == "long":
        snapshot, contracts = snapshot_fixture(anchor="2026-09-06")
        record = contracts["fab_wafer_yield"].data_source.records[0]
        contracts["fab_wafer_yield"].data_source.records = [
            {**record, "wafer_id": str(i), "product_family": f"GROUP-{i:04d}", "test_date": "2026-09-06", "good_die": i+1}
            for i in range(160)]
        body = settings_command(snapshot["report"], "save_change_analysis", saved_payload(metric_name="good_die", anchor="2026-09-06"), contracts)
        result = {key: snapshot[key] for key in ("snapshot_id", "revision", "execution_contract")}
        result.update(data_versions={}, change_analyses=run_saved_analyses({**snapshot, "report": body}, contracts))
    else:
        body, result = change_delivery_fixture(huge=kind == "huge", empty=kind == "empty")
    aid, analysis = next(iter(result["change_analyses"].items()))
    if kind == "decimal":
        executor = Executor()
        previous = Decimal("9007199254740993.125")
        current = Decimal("9007199254740993.125000000000000001")
        def exact(spec):
            value = current if spec.spec_id.endswith("gcur") else previous
            return pd.DataFrame({spec.dimensions[0].alias: ["Exact"], spec.metrics[0].alias: [value]})
        executor.run = exact
        analysis.update(clean(run(executor)))
    result.update(visuals={}, exploration_page_id="main")
    snapshot = dict(report=body, revision=1, format=format, datasets=[])
    original = copy.deepcopy(result)
    monkeypatch.setattr(exports, "run_query", lambda *args: copy.deepcopy(result))
    exports.export_snapshot(tmp_path, snapshot, tmp_path)
    output = tmp_path/("export."+exports.export_suffix(format))
    assert result == original
    if format == "json":
        actual = json.loads(output.read_text(encoding="utf-8"))["analysis"]["change_analyses"][aid]
        assert actual == analysis
    elif format == "csv":
        with zipfile.ZipFile(output) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            table = next(item for item in manifest["tables"] if item.get("kind") == "change_groups")
            rows = list(csv.DictReader(io.StringIO(archive.read(table["file"]).decode("utf-8-sig"))))
            assert table["row_count"] == len(rows) == analysis["group_count"]
            for actual, expected in zip(rows, analysis["rows"]):
                assert actual == {key: "" if value is None else str(value) for key, value in expected.items()}
            assert json.loads(archive.read("analysis.json"))["analysis"]["change_analyses"][aid] == analysis
    elif format == "xlsx":
        from openpyxl import load_workbook
        book = load_workbook(output, data_only=False)
        sheet = book["CH_002_groups"]
        assert sheet.max_row == analysis["group_count"]+1
        headers = [cell.value for cell in sheet[1]]
        for actual, expected in zip(sheet.iter_rows(min_row=2), analysis["rows"]):
            for key, cell in zip(headers, actual):
                value = expected[key]
                assert cell.value == (pytest.approx(value) if type(value) in (float, int) else value)
                if isinstance(value, str):
                    assert cell.data_type == "s"
    else:
        from pypdf import PdfReader
        reader = PdfReader(output)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        compact = "".join(text.split())
        assert aid in compact and "Savedchange" in compact
        for row in analysis["rows"]:
            assert row["group"] in text
        if kind in ("huge", "decimal"):
            for key in ("overall_current", "overall_previous"):
                assert analysis[key] in compact
        if kind == "empty":
            assert "empty" in text
