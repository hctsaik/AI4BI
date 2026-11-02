from __future__ import annotations

import copy
import math

import pandas as pd
import pytest

from ai4bi_web_api.errors import AppError
from ai4bi_web_api.spc import scan, run_spc, ANALYSIS_CONTRACT
from test_workspace_api import client, workspace, wait_job, command


def saved_settings(**changes):
    return {"name": "Queue by tool", "page_id": "main", "selected_component_id": "bar_qt_step",
            "settings": {"block_id": "fab_process_move", "entity_column": "tool_id",
                         "value_column": "queue_time_hr", "aggregation": "mean", "k": 1.5}, **changes}


def test_spc_settings_history_checkpoint_and_idempotency(client):
    ids, path, _ = workspace(client)
    response = command(client, path, 1, "save_spc_analysis", saved_settings(), key="save-spc-settings")
    assert response.status_code == 200, response.text
    state = response.json()
    item = state["report"]["web_extensions"]["spc_analyses"][0]
    assert item["entity_type"] and item["value_type"] and item["analysis_contract"] == ANALYSIS_CONTRACT
    assert item["page_id"] == "main" and item["selected_component_id"] == "bar_qt_step"
    assert state["revision"] == 2 and state["dirty"] and state["can_undo"]
    assert command(client, path, 1, "save_spc_analysis", saved_settings(), key="save-spc-settings").json() == state
    assert command(client, path, 1, "save_spc_analysis", saved_settings(name="Changed"), key="save-spc-settings").status_code == 409
    checkpoint = command(client, path, 2, "save", key="checkpoint-spc-settings")
    assert checkpoint.status_code == 200 and not checkpoint.json()["dirty"]
    payload = saved_settings()
    del payload["name"]
    payload.update(analysis_id=item["analysis_id"], settings={**payload["settings"], "k": 2., "aggregation": "sum"})
    update = command(client, path, 2, "update_spc_analysis", payload, key="update-spc-settings")
    assert update.status_code == 200, update.text
    updated = update.json()["report"]["web_extensions"]["spc_analyses"][0]
    assert updated == {**item, "k": 2., "aggregation": "sum"}
    undo = command(client, path, 3, "undo", key="undo-spc-settings")
    assert undo.json()["report"]["web_extensions"]["spc_analyses"] == [item]
    redo = command(client, path, 4, "redo", key="redo-spc-settings")
    assert redo.json()["report"]["web_extensions"]["spc_analyses"] == [updated]
    restored = command(client, path, 5, "restore_saved", key="restore-spc-settings")
    assert restored.json()["report"]["web_extensions"]["spc_analyses"] == [item]
    assert command(client, path, 2, "delete_spc_analysis", {"analysis_id": item["analysis_id"]}, key="stale-spc-delete").status_code == 409


def test_spc_settings_survive_service_restart(tmp_path):
    from fastapi.testclient import TestClient
    from ai4bi_web_api.app import create_app
    from test_workspace_api import CODE
    root = tmp_path / "restart-data"
    with TestClient(create_app(root, CODE)) as first:
        assert first.post("/api/v1/session", json={"code": CODE}).status_code == 200
        first.headers.update({"x-ai4bi-request": "1"})
        _, path, _ = workspace(first)
        saved = command(first, path, 1, "save_spc_analysis", saved_settings(), key="restart-spc-settings")
        assert saved.status_code == 200, saved.text
        checkpoint = command(first, path, 2, "save", key="restart-spc-checkpoint")
        assert checkpoint.status_code == 200, checkpoint.text
    with TestClient(create_app(root, CODE)) as second:
        assert second.post("/api/v1/session", json={"code": CODE}).status_code == 200
        second.headers.update({"x-ai4bi-request": "1"})
        assert second.get(path).json() == checkpoint.json()
        replay = command(second, path, 1, "save_spc_analysis", saved_settings(), key="restart-spc-settings")
        assert replay.json() == saved.json()


def test_spc_settings_save_reuses_verified_visual_proofs(client, monkeypatch):
    _, path, original = workspace(client)
    warm = command(client, path, 1, "replace_report", {"report": original["report"]}, key="warm-spc-proof")
    assert warm.status_code == 200, warm.text
    def no_decoding(*args, **kwargs):
        raise AssertionError("Saving settings must reuse unchanged visual validation")
    monkeypatch.setattr("ai4bi_web_api.core._parse_contracts", no_decoding)
    saved = command(client, path, 2, "save_spc_analysis", saved_settings(), key="cached-spc-settings")
    assert saved.status_code == 200, saved.text


def test_spc_settings_metadata_repair_without_source_reads(client, monkeypatch):
    _, path, _ = workspace(client)
    response = command(client, path, 1, "save_spc_analysis", saved_settings(), key="spc-before-offline")
    assert response.status_code == 200, response.text
    item = response.json()["report"]["web_extensions"]["spc_analyses"][0]
    def no_reads(*args, **kwargs):
        raise AssertionError("Metadata repair must not read offline data")
    monkeypatch.setattr("ai4bi_web_api.core._read_source", no_reads)
    renamed = command(client, path, 2, "rename_spc_analysis", {"analysis_id": item["analysis_id"], "name": "Fixed"}, key="spc-offline-rename")
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["report"]["web_extensions"]["spc_analyses"][0]["name"] == "Fixed"
    deleted = command(client, path, 3, "delete_spc_analysis", {"analysis_id": item["analysis_id"]}, key="spc-offline-delete")
    assert deleted.status_code == 200 and deleted.json()["report"]["web_extensions"]["spc_analyses"] == []


@pytest.mark.parametrize("patch", [
    {"page_id": "missing"}, {"selected_component_id": "missing"}, {"name": " "},
    {"settings": {**saved_settings()["settings"], "k": True}},
    {"settings": {**saved_settings()["settings"], "value_column": "step_name"}},
    {"settings": {**saved_settings()["settings"], "entity_column": "queue_time_hr"}},
    {"settings": {**saved_settings()["settings"], "entity_type": "spoofed"}},
    {"filters": []}, {"settings": None},
])
def test_spc_settings_reject_invalid_definitions(patch):
    from ai4bi_web_api.core import template
    from ai4bi_web_api.spc import settings_command
    body, contracts = template("fab")
    original = copy.deepcopy(body)
    with pytest.raises(AppError):
        settings_command(body, "save_spc_analysis", saved_settings(**patch), contracts)
    assert body == original


def test_spc_settings_page_ownership_and_schema_drift():
    from ai4bi_web_api.core import template
    from ai4bi_web_api.spc import settings_command, validate_saved_analyses
    from ai4bi_web_api.report_extensions import extensions, duplicate_page, prune_removed_content
    body, contracts = template("fab")
    body = settings_command(body, "save_spc_analysis", saved_settings(), contracts)
    with pytest.raises(AppError) as duplicate:
        settings_command(body, "save_spc_analysis", saved_settings(name="queue BY TOOL"), contracts)
    assert duplicate.value.code == "DUPLICATE_SPC_SETTINGS"
    cloned = duplicate_page(body, "main")
    original, copied = extensions(cloned).spc_analyses
    assert original.analysis_id != copied.analysis_id and original.name != copied.name
    assert copied.page_id != "main" and copied.selected_component_id in cloned["pages"][copied.page_id]["visuals"]
    assert copied.selected_component_id != original.selected_component_id
    validate_saved_analyses(cloned, contracts, extensions(cloned).spc_analyses)
    deleted_visual = copy.deepcopy(cloned)
    del deleted_visual["pages"]["main"]["visuals"]["bar_qt_step"]
    with pytest.raises(AppError) as missing:
        validate_saved_analyses(deleted_visual, contracts, extensions(deleted_visual).spc_analyses)
    assert missing.value.code == "SPC_SETTINGS_INCOMPATIBLE"
    del cloned["pages"]["main"]
    cloned["web_extensions"]["page_order"].remove("main")
    pruned = prune_removed_content(cloned, body)
    assert extensions(pruned).spc_analyses == [copied]
    changed = copy.deepcopy(contracts)
    next(c for c in changed[original.block_id].columns if c.name == original.value_column).data_type = "integer"
    with pytest.raises(AppError) as drift:
        validate_saved_analyses(body, changed, [original])
    assert drift.value.code == "SPC_SETTINGS_INCOMPATIBLE"
    repaired = settings_command(body, "update_spc_analysis", {
        **{k:v for k,v in saved_settings().items() if k != "name"}, "analysis_id": original.analysis_id}, changed)
    assert extensions(repaired).spc_analyses[0].value_type == "integer"


def test_spc_settings_limits_are_atomic():
    from ai4bi_web_api.core import template
    from ai4bi_web_api.spc import settings_command
    from ai4bi_web_api.report_extensions import duplicate_page, extensions
    body, contracts = template("fab")
    for i in range(30):
        body = settings_command(body, "save_spc_analysis", saved_settings(name=f"SPC {i}"), contracts)
    original = copy.deepcopy(body)
    for action in (lambda: settings_command(body, "save_spc_analysis", saved_settings(name="Overflow"), contracts),
                   lambda: duplicate_page(body, "main")):
        with pytest.raises(AppError) as limit:
            action()
        assert limit.value.code == "SPC_SETTINGS_LIMIT"
        assert body == original and len(extensions(body).spc_analyses) == 30


def test_saved_spc_execution_uses_own_page_and_reads_sources_once(client, monkeypatch):
    from ai4bi_web_api import core
    from ai4bi_web_api.jobs import make_snapshot
    ids, path, _ = workspace(client)
    saved = command(client, path, 1, "save_spc_analysis", saved_settings(), key="spc-scope-save")
    assert saved.status_code == 200, saved.text
    copied = command(client, path, 2, "duplicate_page", {"page_id": "main"}, key="spc-scope-copy")
    assert copied.status_code == 200, copied.text
    definitions = copied.json()["report"]["web_extensions"]["spc_analyses"]
    options = {"include_spc": True, "exploration_page_id": "main", "filters": [
        {"source_visual_id": "bar_qt_step", "block_id": "fab_process_move", "column_name": "step_name", "operator": "eq", "value": "Etch"}]}
    snapshot = make_snapshot(client.app.state.store, ids["workspace_id"], ids["report_id"], 3, options)
    calls = []
    read = core._read_source
    def observed(*args):
        calls.append(args[1]["dataset_id"])
        return read(*args)
    monkeypatch.setattr(core, "_read_source", observed)
    results = core.run_query(client.app.state.store.root, snapshot)["spc_analyses"]
    assert len(calls) == len(snapshot["datasets"])
    first, second = [results[item["analysis_id"]] for item in definitions]
    assert first["input_rows"] == 100 and second["input_rows"] == 600
    assert first["applied_filters"] == options["filters"] and second["applied_filters"] == []
    assert first["snapshot_id"] == second["snapshot_id"] == snapshot["snapshot_id"]
    assert first["selected_component_id"] != second["selected_component_id"]
    def no_scan(*args):
        pytest.fail("Ordinary chart queries must not execute saved analyses")
    monkeypatch.setattr("ai4bi_web_api.spc.run_saved_analyses", no_scan)
    assert core.run_query(client.app.state.store.root, {**snapshot, "include_spc": False})["spc_analyses"] == {}


@pytest.mark.parametrize("format", ["json", "csv", "xlsx", "pdf"])
def test_saved_spc_four_format_exports_contain_complete_analysis(client, tmp_path, format):
    import csv
    import io
    import json
    import zipfile
    from ai4bi_web_api.core import run_query
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.exports import export_snapshot, export_suffix
    ids, path, _ = workspace(client)
    saved = command(client, path, 1, "save_spc_analysis", saved_settings(name="=SPC/$not-math"), key="spc-format-save")
    assert saved.status_code == 200, saved.text
    aid = saved.json()["report"]["web_extensions"]["spc_analyses"][0]["analysis_id"]
    snapshot = make_snapshot(client.app.state.store, ids["workspace_id"], ids["report_id"], 2, {"format": format, "include_spc": True})
    expected = run_query(client.app.state.store.root, snapshot)["spc_analyses"][aid]
    output = tmp_path / "exported"
    output.mkdir()
    exported = export_snapshot(client.app.state.store.root, {**snapshot, "include_spc": False}, output)
    assert exported["snapshot_id"] == snapshot["snapshot_id"]
    file = output / ("export." + export_suffix(format))
    if format == "json":
        assert json.loads(file.read_text(encoding="utf-8"))["analysis"]["spc_analyses"][aid] == expected
    elif format == "csv":
        with zipfile.ZipFile(file) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["format_version"] == 2 and manifest["execution_contract"] == "web-query-v7"
            entries = [item for item in manifest["tables"] if item.get("analysis_id") == aid]
            assert {item["kind"] for item in entries} == {"spc_summary", "spc_points", "spc_outliers"}
            point_entry = next(item for item in entries if item["kind"] == "spc_points")
            points = list(csv.DictReader(io.StringIO(archive.read(point_entry["file"]).decode("utf-8-sig"))))
            assert [{"entity": p["entity"], "value": float(p["value"])} for p in points] == expected["points"]
            summary = next(item for item in entries if item["kind"] == "spc_summary")
            assert summary["protected_cells"]
            assert "'=SPC/$not-math" in archive.read(summary["file"]).decode("utf-8-sig")
            assert json.loads(archive.read("analysis.json"))["analysis"]["spc_analyses"][aid] == expected
            assert not any("$not-math" in name for name in archive.namelist())
    elif format == "xlsx":
        import openpyxl
        workbook = openpyxl.load_workbook(file)
        points = workbook["SPC_002_points"]
        assert points["A1"].comment.text == aid
        rows = list(points.values)[1:]
        assert [row[0] for row in rows] == [point["entity"] for point in expected["points"]]
        assert [row[1] for row in rows] == pytest.approx([point["value"] for point in expected["points"]], rel=1e-14, abs=1e-12)
        summary = workbook["SPC_001_summary"]
        name_cell = next(row[1] for row in summary if row[0].value == "name")
        assert name_cell.value == "=SPC/$not-math" and name_cell.data_type == "s"
        metadata = dict(list(summary.values)[1:])
        assert metadata["entity_count"] == expected["entity_count"]
        assert metadata["mean"] == pytest.approx(expected["limits"]["mean"])
        assert metadata["execution_contract"] == "web-query-v7"
    else:
        import pypdf
        reader = pypdf.PdfReader(file)
        assert "web-query-v7" in reader.metadata.subject
        text = "\n".join(page.extract_text() for page in reader.pages)
        assert "SPC" in text and "not-math" in text and "ucl" in text and "lcl" in text
        compact = "".join(text.split())
        assert aid in compact and "web-query-v7" in compact
        for point in expected["points"]:
            assert str(point["entity"]) in compact
        assert len(reader.pages) > 5


def test_spc_publication_keeps_definition_after_draft_changes(client):
    ids, path, _ = workspace(client)
    saved = command(client, path, 1, "save_spc_analysis", saved_settings(), key="publish-spc-save")
    assert saved.status_code == 200, saved.text
    item = saved.json()["report"]["web_extensions"]["spc_analyses"][0]
    accepted = client.post(path + "/publications", json={"base_revision": 2, "idempotency_key": "publish-spc-report"})
    assert accepted.status_code == 202, accepted.text
    published = wait_job(client, accepted.json()["job_id"])
    assert published["status"] == "succeeded", published
    target = path + "/publications/" + published["result"]["publication_id"]
    detail = client.get(target).json()
    assert detail["checks"]["spc_analyses"][item["analysis_id"]]["input_rows"] == 600
    deleted = command(client, path, 2, "delete_spc_analysis", {"analysis_id": item["analysis_id"]}, key="published-spc-delete-draft")
    assert deleted.status_code == 200, deleted.text
    query = client.post(target + "/queries", json={"base_revision": 2, "idempotency_key": "published-spc-query", "include_spc": True})
    assert query.status_code == 202, query.text
    result = wait_job(client, query.json()["job_id"])
    assert result["status"] == "succeeded", result
    analysis = result["result"]["spc_analyses"][item["analysis_id"]]
    assert analysis["settings"] == item and analysis["input_rows"] == 600
    assert client.get(target).json()["report"]["web_extensions"]["spc_analyses"] == [item]
    assert client.post(path + "/exports", json={"base_revision": 3, "idempotency_key": "no-spc-export-opt-out", "include_spc": False}).status_code == 422
    assert client.post(path + "/queries", json={"base_revision": 3, "idempotency_key": "invalid-spc-include", "include_spc": "yes"}).status_code == 422


@pytest.mark.parametrize("kind", ["publish", "json", "csv", "xlsx", "pdf"])
def test_saved_spc_failure_prevents_partial_delivery(client, tmp_path, monkeypatch, kind):
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.publications import check_publication
    from ai4bi_web_api.exports import export_snapshot
    ids, path, _ = workspace(client)
    saved = command(client, path, 1, "save_spc_analysis", saved_settings(), key="spc-failure-save")
    assert saved.status_code == 200, saved.text
    snapshot = make_snapshot(client.app.state.store, ids["workspace_id"], ids["report_id"], 2, {"format": kind})
    def failed(*args, **kwargs):
        raise AppError("SPC_ENTITY_LIMIT", "Too many entities")
    monkeypatch.setattr("ai4bi_web_api.spc.scan", failed)
    output = tmp_path / "rejected-export"
    output.mkdir()
    with pytest.raises(AppError) as caught:
        if kind == "publish":
            check_publication(client.app.state.store.root, snapshot)
        else:
            export_snapshot(client.app.state.store.root, snapshot, output)
    assert caught.value.code == "SPC_ENTITY_LIMIT"
    assert list(output.iterdir()) == []


def test_published_spc_replays_after_service_restart(tmp_path):
    from fastapi.testclient import TestClient
    from ai4bi_web_api.app import create_app
    from test_workspace_api import CODE
    root = tmp_path / "published-spc-restart"
    with TestClient(create_app(root, CODE)) as first:
        assert first.post("/api/v1/session", json={"code": CODE}).status_code == 200
        first.headers.update({"x-ai4bi-request": "1"})
        _, path, _ = workspace(first)
        saved = command(first, path, 1, "save_spc_analysis", saved_settings(), key="spc-restart-publish-save")
        assert saved.status_code == 200, saved.text
        accepted = first.post(path + "/publications", json={"base_revision": 2, "idempotency_key": "spc-restart-publish"})
        published = wait_job(first, accepted.json()["job_id"])
        assert published["status"] == "succeeded", published
        target = path + "/publications/" + published["result"]["publication_id"]
        before = first.get(target).json()
    with TestClient(create_app(root, CODE)) as second:
        assert second.post("/api/v1/session", json={"code": CODE}).status_code == 200
        second.headers.update({"x-ai4bi-request": "1"})
        assert second.get(target).json() == before
        query = second.post(target + "/queries", json={"base_revision": 2, "idempotency_key": "spc-restart-replay", "include_spc": True})
        result = wait_job(second, query.json()["job_id"])
        assert result["status"] == "succeeded", result
        analysis = next(iter(result["result"]["spc_analyses"].values()))
        assert analysis["settings"] == before["report"]["web_extensions"]["spc_analyses"][0]
        assert analysis["data_versions"] == before["data_versions"]
        assert analysis["input_rows"] == 600 and analysis["status"] == "ready"


def test_population_sigma_uses_entity_means_not_row_weighting():
    frame = pd.DataFrame({"tool": ["a", "a", "b", "c", "d", None, "e"],
                          "queue": [0., 2., 1., 1., 9., 500., None]})
    result = scan(frame, "tool", "queue", k=1.5)
    assert result["status"] == "ready"
    assert result["limits"] == {"mean": 3., "sigma": round(math.sqrt(12), 3),
        "ucl": round(3+1.5*math.sqrt(12), 3), "lcl": round(3-1.5*math.sqrt(12), 3), "k": 1.5, "n": 4}
    assert result["used_rows"] == 5 and result["excluded_rows"] == 2
    assert result["outliers"].to_dict("records")[0]["entity"] == "d"
    assert result["outliers"].to_dict("records")[0]["z_score"] == 1.73
    assert scan(frame, "tool", "queue", aggregation="sum")["points"][0]["value"] == 2


@pytest.mark.parametrize("values,status", [([], "empty"), ([1., 9.], "insufficient_groups"), ([2., 2., 2.], "zero_variance")])
def test_unavailable_limits_are_explicit(values, status):
    result = scan(pd.DataFrame({"entity": range(len(values)), "value": pd.Series(values, dtype=float)}), "entity", "value")
    assert result["status"] == status and result["limits"] is None


def test_zero_outliers_still_returns_valid_limits_and_all_points():
    result = scan(pd.DataFrame({"x": ["a", "b", "c"], "y": [1., 2., 3.]}), "x", "y")
    assert result["status"] == "ready" and result["outliers"].empty
    assert len(result["points"]) == 3


@pytest.mark.parametrize("options", [{"k": 0}, {"k": float("inf")}, {"k": True}, {"aggregation": "median"}])
def test_reject_invalid_parameters(options):
    with pytest.raises(AppError):
        scan(pd.DataFrame({"x": [1, 2, 3], "y": [1., 2., 3.]}), "x", "y", **options)


@pytest.mark.parametrize("values", [[1., float("inf"), 3.], ["1", "2", "3"], [True, False, True]])
def test_reject_invalid_numeric_data(values):
    with pytest.raises(AppError):
        scan(pd.DataFrame({"x": [1, 2, 3], "y": values}), "x", "y")


def test_entity_limit_and_unused_categories():
    with pytest.raises(AppError) as caught:
        scan(pd.DataFrame({"x": range(5001), "y": range(5001)}), "x", "y")
    assert caught.value.code == "SPC_ENTITY_LIMIT"
    result = scan(pd.DataFrame({"x": pd.Categorical(["a", "b", "c"], categories=["a", "b", "c", "absent"]),
                               "y": [1., 2., 9.]}), "x", "y", aggregation="sum")
    assert result["entity_count"] == result["limits"]["n"] == 3


def test_spc_real_worker_snapshot_filters_and_idempotency(client):
    ids, path, original = workspace(client)
    request = {"base_revision": 1, "idempotency_key": "spc-before-edit", "block_id": "fab_process_move",
               "entity_column": "tool_id", "value_column": "queue_time_hr", "k": 1.5}
    accepted = client.post(path + "/analyses/spc", json=request)
    assert accepted.status_code == 202, accepted.text
    job = wait_job(client, accepted.json()["job_id"])
    assert job["status"] == "succeeded", job
    result = job["result"]
    assert result["analysis_contract"] == ANALYSIS_CONTRACT
    assert result["entity_count"] >= 3 and result["input_rows"] > 0
    changed = command(client, path, 1, "add_filter", {"filter": {"scope": "report", "block_id": "fab_process_move",
        "column_name": "step_name", "operator": "eq", "value": "Etch"}}, key="spc-scope-filter")
    assert changed.status_code == 200, changed.text
    assert client.post(path + "/analyses/spc", json=request).json() == accepted.json()
    assert client.post(path + "/analyses/spc", json={**request, "k": 2.}).status_code == 409
    response = client.post(path + "/analyses/spc", json={**request, "base_revision": 2, "idempotency_key": "spc-after-filter"})
    scoped = wait_job(client, response.json()["job_id"])
    assert scoped["status"] == "succeeded", scoped
    assert scoped["result"]["input_rows"] < result["input_rows"]
    assert scoped["result"]["data_versions"] == result["data_versions"]
    assert scoped["result"]["snapshot_id"] != result["snapshot_id"]
    assert client.get(path).json()["revision"] == 2
    from ai4bi_web_api.jobs import make_snapshot
    snapshot = make_snapshot(client.app.state.store, ids["workspace_id"], ids["report_id"], 2,
        {**request, "aggregation": "mean", "analysis_contract": ANALYSIS_CONTRACT})
    for field, value, code in [("analysis_contract", "spc-entity-v1", "SPC_INCOMPATIBLE"),
                               ("selected_component_id", "deleted", "INVALID_SPC_CONTEXT"),
                               ("value_column", "unknown", "INVALID_SPC")]:
        with pytest.raises(AppError) as caught:
            run_spc(client.app.state.store.root, {**snapshot, field: value})
        assert caught.value.code == code


def test_spc_http_rejects_bad_inputs(client):
    _, path, _ = workspace(client)
    request = {"base_revision": 1, "idempotency_key": "spc-invalid-input", "block_id": "fab_process_move",
               "entity_column": "tool_id", "value_column": "queue_time_hr"}
    for extra in ({"k": 0}, {"k": True}, {"k": "3"}, {"aggregation": "median"}, {"analysis_contract": "fake"}):
        assert client.post(path + "/analyses/spc", json={**request, **extra}).status_code == 422


def test_spc_cross_filter_includes_selected_source_and_intersects_page_scope(client):
    ids, path, _ = workspace(client)
    predicate = {"source_visual_id": "bar_qt_step", "block_id": "fab_process_move",
                 "column_name": "step_name", "operator": "eq", "value": "Etch"}
    request = {"base_revision": 1, "idempotency_key": "spc-cross-filter", "block_id": "fab_process_move",
               "entity_column": "tool_id", "value_column": "queue_time_hr", "filters": [predicate],
               "selected_component_id": "bar_qt_step", "exploration_page_id": "main"}
    accepted = client.post(path + "/analyses/spc", json=request)
    assert accepted.status_code == 202, accepted.text
    job = wait_job(client, accepted.json()["job_id"])
    assert job["status"] == "succeeded", job
    result = job["result"]
    assert result["input_rows"] == 100 and result["entity_count"] == 2
    assert result["applied_filters"] == result["filters"] == [predicate]
    assert {point["entity"] for point in result["points"]} == {"ETCH-01", "ETCH-02"}
    assert client.post(path + "/analyses/spc", json=request).json() == accepted.json()
    assert client.post(path + "/analyses/spc", json={**request, "filters": []}).status_code == 409
    changed = command(client, path, 1, "add_filter", {"filter": {"scope": "page", "page_id": "main",
        "block_id": "fab_process_move", "column_name": "queue_time_hr", "operator": "gt", "value": 4}}, key="spc-page-scope")
    assert changed.status_code == 200, changed.text
    # No selection still uses the explicit page scope; both predicates apply.
    accepted2 = client.post(path + "/analyses/spc", json={**request, "base_revision": 2,
        "idempotency_key": "spc-cross-page", "selected_component_id": None})
    narrowed = wait_job(client, accepted2.json()["job_id"])
    assert narrowed["status"] == "succeeded", narrowed
    from ai4bi_web_api.core import load_contracts
    from ai4bi.blocks.datastore import materialize_dataframe
    frame = materialize_dataframe(load_contracts(client.app.state.store.root, client.app.state.store.datasets(ids["workspace_id"]))["fab_process_move"])
    expected = frame[(frame.step_name == "Etch") & (frame.queue_time_hr > 4)]
    assert narrowed["result"]["input_rows"] == len(expected) < 100
    assert {p["entity"]:p["value"] for p in narrowed["result"]["points"]} == expected.groupby("tool_id").queue_time_hr.mean().to_dict()
    assert client.get(path).json()["revision"] == 2


@pytest.mark.parametrize("patch", [{"column_name": "missing"}, {"source_visual_id": "kpi_moves"},
    {"operator": "sql"}, {"column_name": "queue_time_hr", "value": "bad", "source_visual_id": None},
    {"block_id": "missing"}])
def test_spc_rejects_invalid_exploration_filters(patch):
    from ai4bi_web_api.core import template
    from ai4bi_web_api.spc import exploration_context
    body, contracts = template("fab")
    predicate = {"block_id": "fab_process_move", "column_name": "step_name", "operator": "eq", "value": "Etch",
                 "source_visual_id": "bar_qt_step", **patch}
    with pytest.raises(AppError):
        exploration_context({"report":body, "exploration_page_id":"main", "filters":[predicate]}, contracts)


def test_spc_rejects_old_contract_before_loading_data(tmp_path, monkeypatch):
    from ai4bi_web_api import core
    from ai4bi_web_api.publications import EXECUTION_CONTRACT
    def unexpected(*args):
        pytest.fail("Old SPC contract must be rejected before loading data")
    monkeypatch.setattr(core, "load_contracts", unexpected)
    with pytest.raises(AppError) as caught:
        run_spc(tmp_path, {"analysis_contract":"spc-entity-v1", "execution_contract":EXECUTION_CONTRACT})
    assert caught.value.code == "SPC_INCOMPATIBLE"


def test_spc_cross_filter_source_can_be_drilled_without_being_selected():
    from ai4bi_web_api.core import template
    from ai4bi_web_api.spc import exploration_context
    body, contracts = template("fab")
    vid = "bar_qt_step"
    body["pages"]["main"]["visuals"][vid]["visualization"]["extra"]["drill_hierarchy"] = ["step_name", "tool_id"]
    state = {"block_id":"fab_process_move", "hierarchy":["step_name","tool_id"],
        "field_types":["string","string"], "path":[{"column":"step_name","value":"Etch"}]}
    snapshot = {"report":body, "exploration_page_id":"main", "selected_component_id":"kpi_moves", "drill_state":{vid:state},
        "filters":[{"block_id":"fab_process_move", "column_name":"tool_id", "operator":"eq", "value":"ETCH-02", "source_visual_id":vid}]}
    page_id, predicates, _ = exploration_context(snapshot, contracts)
    assert page_id == "main" and predicates[0].value == "ETCH-02"
    with pytest.raises(AppError):
        exploration_context({**snapshot, "drill_state":{}}, contracts)
    other = copy.deepcopy(body["pages"]["main"])
    other.update(page_id="other", visuals={}, visual_order=[])
    body["pages"]["other"] = other
    with pytest.raises(AppError):
        exploration_context({**snapshot, "exploration_page_id":"other"}, contracts)


def test_spc_selected_query_filters_use_core_global_inheritance(client):
    ids, path, original = workspace(client)
    body = copy.deepcopy(original["report"])
    body["global_filters"] = {"fab_process_move.step_name": ["Etch"]}
    body["pages"]["main"]["visuals"]["kpi_moves"]["query"]["filters"] = [
        {"block_id":"fab_process_move", "column_name":"step_name", "operator":"in", "value":["CVD"], "inherit_global_filter":True}]
    response = command(client, path, 1, "replace_report", {"report":body}, key="spc-static-query-filter")
    assert response.status_code == 200, response.text
    from ai4bi_web_api.jobs import make_snapshot
    snapshot = make_snapshot(client.app.state.store, ids["workspace_id"], ids["report_id"], 2,
        {"block_id":"fab_process_move", "entity_column":"tool_id", "value_column":"queue_time_hr", "k":3.,
         "aggregation":"mean", "analysis_contract":ANALYSIS_CONTRACT, "selected_component_id":"kpi_moves", "exploration_page_id":"main"})
    result = run_spc(client.app.state.store.root, snapshot)
    assert result["input_rows"] == 100
    assert result["selected_query_filters"][0]["value"] == ["Etch"]
    assert run_spc(client.app.state.store.root, {**snapshot,"selected_component_id":None})["input_rows"] == 600
