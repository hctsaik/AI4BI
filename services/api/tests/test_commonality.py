import pandas as pd
import pytest

from ai4bi_web_api.commonality import scan
from ai4bi_web_api.errors import AppError
from test_workspace_api import client, workspace, wait_job, command


def request(**changes):
    return {"base_revision": 1, "idempotency_key": "commonality-scan-1",
            "block_id": "fab_process_move", "outcome_block_id": "fab_wafer_yield",
            "entity_column": "tool_id", "group_column": "wafer_id",
            "outcome_group_column": "wafer_id", "value_column": "yield_pct",
            "threshold": 80.0, "exploration_page_id": "main", **changes}


def saved_settings(**changes):
    settings = {k: v for k, v in request().items() if k not in {"base_revision", "idempotency_key", "exploration_page_id"}}
    return {"name": "Yield commonality", "settings": settings, "page_id": "main",
            "selected_component_id": "bar_qt_step", **changes}


def test_commonality_settings_history_and_checkpoint(client):
    import copy
    _, path, _ = workspace(client)
    payload = saved_settings()
    response = command(client, path, 1, "save_commonality_analysis", payload, key="commonality-save-settings")
    assert response.status_code == 200, response.text
    state = response.json()
    definition = state["report"]["web_extensions"]["commonality_analyses"][0]
    assert definition["field_types"] == {"entity_column": "string", "group_column": "string", "outcome_group_column": "string", "value_column": "float"}
    assert command(client, path, 1, "save_commonality_analysis", payload, key="commonality-save-settings").json() == state
    updated = copy.deepcopy(payload["settings"])
    updated["threshold"] = 85
    response = command(client, path, 2, "update_commonality_analysis", {"analysis_id": definition["analysis_id"],
        "settings": updated, "page_id": "main", "selected_component_id": "bar_qt_step"}, key="commonality-update")
    assert response.status_code == 200, response.text
    assert command(client, path, 3, "rename_commonality_analysis", {"analysis_id": definition["analysis_id"], "name": "Renamed"}, key="commonality-rename").status_code == 200
    assert command(client, path, 4, "save", key="commonality-checkpoint").status_code == 200
    saved = client.get(path).json()
    assert not saved["dirty"]
    deleted = command(client, path, saved["revision"], "delete_commonality_analysis", {"analysis_id": definition["analysis_id"]}, key="commonality-delete")
    assert deleted.status_code == 200
    assert client.get(path).json()["report"]["web_extensions"]["commonality_analyses"] == []
    undo = command(client, path, deleted.json()["revision"], "undo", key="commonality-undo")
    assert undo.status_code == 200
    assert undo.json()["report"]["web_extensions"]["commonality_analyses"] == saved["report"]["web_extensions"]["commonality_analyses"]


def test_commonality_settings_duplicate_page_remaps_and_prunes(client):
    from ai4bi_web_api.report_extensions import prune_removed_content
    import copy
    _, path, _ = workspace(client)
    assert command(client, path, 1, "save_commonality_analysis", saved_settings(), key="commonality-page-save").status_code == 200
    duplicated = command(client, path, 2, "duplicate_page", {"page_id": "main"}, key="commonality-page-copy")
    assert duplicated.status_code == 200, duplicated.text
    body = duplicated.json()["report"]
    first, second = body["web_extensions"]["commonality_analyses"]
    assert first["analysis_id"] != second["analysis_id"] and first["name"] != second["name"]
    assert second["selected_component_id"] in body["pages"][second["page_id"]]["visuals"]
    edited = copy.deepcopy(body)
    del edited["pages"][second["page_id"]]
    assert prune_removed_content(edited, body)["web_extensions"]["commonality_analyses"] == [first]


def test_commonality_settings_offline_metadata_repair(client, monkeypatch):
    _, path, _ = workspace(client)
    saved = command(client, path, 1, "save_commonality_analysis", saved_settings(), key="commonality-offline-save")
    aid = saved.json()["report"]["web_extensions"]["commonality_analyses"][0]["analysis_id"]
    monkeypatch.setattr("ai4bi_web_api.core.load_contracts", lambda *args: pytest.fail("Metadata repair read source"))
    assert command(client, path, 2, "rename_commonality_analysis", {"analysis_id": aid, "name": "Offline"}, key="commonality-offline-rename").status_code == 200
    assert command(client, path, 3, "delete_commonality_analysis", {"analysis_id": aid}, key="commonality-offline-delete").status_code == 200


def test_commonality_saved_settings_survive_service_restart(tmp_path):
    from fastapi.testclient import TestClient
    from ai4bi_web_api.app import create_app
    from test_workspace_api import CODE
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.core import load_contracts
    from ai4bi_web_api.commonality import run_saved_analyses
    data = tmp_path / "restart-data"
    def pair(c):
        assert c.post("/api/v1/session", json={"code": CODE}).status_code == 200
        c.headers.update({"x-ai4bi-request": "1"})
    with TestClient(create_app(data, CODE)) as c:
        pair(c)
        ids, path, _ = workspace(c)
        saved = command(c, path, 1, "save_commonality_analysis", saved_settings(), key="commonality-restart-save")
        assert saved.status_code == 200
        expected = saved.json()["report"]["web_extensions"]["commonality_analyses"]
        assert command(c, path, 2, "save", key="commonality-restart-checkpoint").status_code == 200
        snapshot = make_snapshot(c.app.state.store, ids["workspace_id"], ids["report_id"], 2, {})
        replay = run_saved_analyses(snapshot, load_contracts(data, snapshot["datasets"]))
    with TestClient(create_app(data, CODE)) as c:
        pair(c)
        assert c.get(path).json()["report"]["web_extensions"]["commonality_analyses"] == expected
        assert run_saved_analyses(snapshot, load_contracts(data, snapshot["datasets"])) == replay


def test_commonality_rejects_invalid_drill_before_loading_source(client, monkeypatch):
    from ai4bi_web_api.commonality import run_commonality, ANALYSIS_CONTRACT
    from ai4bi_web_api.jobs import make_snapshot
    ids, _, _ = workspace(client)
    store = client.app.state.store
    snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 1,
                             {**request(), "analysis_contract": ANALYSIS_CONTRACT})
    snapshot["drill_state"] = {"bar_qt_step": {"path": "invalid"}}
    monkeypatch.setattr("ai4bi_web_api.core.load_contracts", lambda *args: pytest.fail("Invalid drill read data"))
    with pytest.raises(AppError) as caught:
        run_commonality(store.root, snapshot)
    assert caught.value.code == "INVALID_DRILL"


def test_saved_commonality_replay_keeps_snapshot_after_draft_deletion(client):
    from ai4bi_web_api.commonality import run_saved_analyses
    from ai4bi_web_api.core import load_contracts
    from ai4bi_web_api.jobs import make_snapshot
    ids, path, _ = workspace(client)
    saved = command(client, path, 1, "save_commonality_analysis", saved_settings(), key="commonality-replay-save")
    aid = saved.json()["report"]["web_extensions"]["commonality_analyses"][0]["analysis_id"]
    store = client.app.state.store
    snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 2, {})
    contracts = load_contracts(store.root, snapshot["datasets"])
    result = run_saved_analyses(snapshot, contracts)
    assert result[aid]["population_count"] == 100
    assert result[aid]["qualifying_count"] == 11
    assert result[aid]["rows"][0] == {"entity": "ETCH-02", "qualifying_count": 11,
                                     "coverage_percent": 100.0, "lift": 1.82, "p_value": 0.0008}
    assert result[aid]["settings"]["threshold"] == 80
    assert command(client, path, 2, "delete_commonality_analysis", {"analysis_id": aid}, key="commonality-replay-delete").status_code == 200
    assert run_saved_analyses(snapshot, load_contracts(store.root, snapshot["datasets"])) == result


def test_saved_commonality_cross_page_scope_reuses_verified_sources(client, monkeypatch):
    import copy
    from ai4bi_web_api import core
    from ai4bi_web_api.commonality import run_saved_analyses
    from ai4bi_web_api.jobs import make_snapshot
    ids, path, _ = workspace(client)
    assert command(client, path, 1, "save_commonality_analysis", saved_settings(), key="commonality-scope-save").status_code == 200
    duplicated = command(client, path, 2, "duplicate_page", {"page_id": "main"}, key="commonality-scope-copy")
    assert duplicated.status_code == 200
    defs = duplicated.json()["report"]["web_extensions"]["commonality_analyses"]
    first, second = (item["analysis_id"] for item in defs)
    options = {"exploration_page_id": "main", "filters": [{"source_visual_id": "bar_qt_step",
        "block_id": "fab_process_move", "column_name": "step_name", "operator": "eq", "value": "Etch"}]}
    store = client.app.state.store
    snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 3, options)
    before = copy.deepcopy(snapshot)
    reads = []
    read = core._read_source
    def observed(*args):
        reads.append(args[1]["dataset_id"])
        return read(*args)
    monkeypatch.setattr(core, "_read_source", observed)
    contracts = core.load_contracts(store.root, snapshot["datasets"])
    result = run_saved_analyses(snapshot, contracts)
    assert len(reads) == len(snapshot["datasets"])
    assert len(result[first]["rows"]) == 1 and len(result[second]["rows"]) == 11
    assert result[first]["population_count"] == result[second]["population_count"] == 100
    assert result[first]["applied_filters"] == options["filters"] and result[second]["applied_filters"] == []
    assert result[first]["selected_component_id"] != result[second]["selected_component_id"]
    assert result[first]["snapshot_id"] == result[second]["snapshot_id"] == snapshot["snapshot_id"]
    assert result[first]["data_versions"] == result[second]["data_versions"]
    assert snapshot == before


def test_saved_commonality_checks_all_definitions_before_computation(client, monkeypatch):
    from ai4bi_web_api import commonality, core
    from ai4bi_web_api.jobs import make_snapshot
    ids, path, _ = workspace(client)
    assert command(client, path, 1, "save_commonality_analysis", saved_settings(), key="commonality-check-all-save").status_code == 200
    assert command(client, path, 2, "duplicate_page", {"page_id": "main"}, key="commonality-check-all-copy").status_code == 200
    store = client.app.state.store
    snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 3, {})
    snapshot["report"]["web_extensions"]["commonality_analyses"][1]["field_types"]["value_column"] = "integer"
    contracts = core.load_contracts(store.root, snapshot["datasets"])
    monkeypatch.setattr(commonality, "scan_snapshot", lambda *args: pytest.fail("Computed before validating every definition"))
    with pytest.raises(AppError) as caught:
        commonality.run_saved_analyses(snapshot, contracts)
    assert caught.value.code == "COMMONALITY_SETTINGS_INCOMPATIBLE"


def test_saved_commonality_analysis_failure_never_returns_partial_result(client, monkeypatch):
    from ai4bi_web_api import commonality, core
    from ai4bi_web_api.jobs import make_snapshot
    ids, path, _ = workspace(client)
    assert command(client, path, 1, "save_commonality_analysis", saved_settings(), key="commonality-fail-save").status_code == 200
    assert command(client, path, 2, "duplicate_page", {"page_id": "main"}, key="commonality-fail-copy").status_code == 200
    store = client.app.state.store
    snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 3, {})
    contracts = core.load_contracts(store.root, snapshot["datasets"])
    scan = commonality.scan_snapshot
    calls = []
    def fail_second(current, sources):
        calls.append(current["analysis_id"])
        if len(calls) == 2:
            raise AppError("COMMONALITY_LIMIT", "Injected analysis limit")
        return scan(current, sources)
    monkeypatch.setattr(commonality, "scan_snapshot", fail_second)
    with pytest.raises(AppError) as caught:
        commonality.run_saved_analyses(snapshot, contracts)
    assert len(calls) == 2 and caught.value.code == "COMMONALITY_LIMIT"


def test_commonality_settings_limit(client):
    _, path, _ = workspace(client, key="commonality-limit-workspace")
    saved = command(client, path, 1, "save_commonality_analysis", saved_settings(), key="commonality-limit-save")
    body = saved.json()["report"]
    first = body["web_extensions"]["commonality_analyses"][0]
    body["web_extensions"]["commonality_analyses"] = [{**first, "analysis_id": f"cm_{i}", "name": f"Analysis {i}"} for i in range(30)]
    assert command(client, path, 2, "replace_report", {"report": body}, key="commonality-limit-report").status_code == 200
    failure = command(client, path, 3, "duplicate_page", {"page_id": "main"}, key="commonality-limit-copy")
    assert failure.status_code == 400 and client.get(path).json()["revision"] == 3


@pytest.mark.parametrize("format", ["csv", "xlsx", "pdf"])
def test_commonality_document_projection_retains_metadata_and_all_entities(client, tmp_path, format):
    import csv
    import io
    import json
    import zipfile
    from ai4bi_web_api import core, exports
    from ai4bi_web_api.commonality import run_saved_analyses
    from ai4bi_web_api.jobs import make_snapshot
    ids, path, _ = workspace(client)
    payload = saved_settings(name="=CM/$literal$")
    assert command(client, path, 1, "save_commonality_analysis", payload, key="commonality-document-save").status_code == 200
    store = client.app.state.store
    snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 2, {})
    analyses = run_saved_analyses(snapshot, core.load_contracts(store.root, snapshot["datasets"]))
    aid, analysis = next(iter(analyses.items()))
    result = {"snapshot_id": snapshot["snapshot_id"], "execution_contract": snapshot["execution_contract"],
              "visuals": {}, "commonality_analyses": analyses}
    tables = list(exports.commonality_tables(snapshot, result))
    assert [part for _, part, _ in tables] == ["summary", "entities"]
    metadata = {row["field"]: row["value"] for row in tables[0][2]["rows"]}
    assert metadata["threshold"] == 80 and metadata["population_count"] == 100
    assert json.loads(metadata["field_types"]) == analysis["settings"]["field_types"]
    assert json.loads(metadata["data_versions"]) == analysis["data_versions"]
    assert tables[1][2]["rows"] == analysis["rows"] and len(analysis["rows"]) == 11
    output = tmp_path / ("analysis." + format)
    if format == "csv":
        exports.csv_bundle(output, snapshot, result)
        with zipfile.ZipFile(output) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            summary, entities = manifest["tables"]
            assert [item["kind"] for item in manifest["tables"]] == ["commonality_summary", "commonality_entities"]
            assert all(item["analysis_id"] == aid for item in manifest["tables"])
            assert summary["protected_cells"] and entities["row_count"] == 11
            rows = list(csv.DictReader(io.StringIO(archive.read(entities["file"]).decode("utf-8-sig"))))
            assert [r["entity"] for r in rows] == [r["entity"] for r in analysis["rows"]]
            for actual, expected in zip(rows, analysis["rows"]):
                for key in ("qualifying_count", "coverage_percent", "lift", "p_value"):
                    assert float(actual[key]) == expected[key]
            assert json.loads(archive.read("analysis.json"))["analysis"]["commonality_analyses"] == analyses
    elif format == "xlsx":
        import openpyxl
        with pd.ExcelWriter(output, engine="xlsxwriter", engine_kwargs={"options": {"strings_to_formulas": False, "strings_to_urls": False}}) as writer:
            pd.DataFrame([{"existing": "keep"}]).to_excel(writer, sheet_name="CM_001_summary", index=False)
            exports.analysis_excel(writer, snapshot, result, {"cm_001_summary"})
        workbook = openpyxl.load_workbook(output)
        summary = workbook["CM_001_summary_2"]
        entities = workbook["CM_002_entities"]
        assert summary["A1"].comment.text == entities["A1"].comment.text == aid
        assert any(row[0].value == "name" and row[1].value == "=CM/$literal$" and row[1].data_type == "s" for row in summary.iter_rows(min_row=2))
        rows = list(entities.values)
        assert len(rows) == 12
        assert [dict(zip(rows[0], row)) for row in rows[1:]] == analysis["rows"]
    else:
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib.backends.backend_pdf import PdfPages
        from pypdf import PdfReader
        with matplotlib.rc_context({"font.sans-serif": ["Microsoft JhengHei"], "pdf.fonttype": 42}):
            with PdfPages(output) as pdf:
                exports.pdf_commonality_pages(pdf, snapshot, result, "Snapshot " + snapshot["snapshot_id"])
        reader = PdfReader(output)
        text = "".join(page.extract_text() or "" for page in reader.pages)
        compact = "".join(text.split())
        assert aid in compact and snapshot["snapshot_id"] in compact
        assert "=CM/$literal$" in text and "commonality-v1" in text
        assert all(row["entity"] in text for row in analysis["rows"])
        assert "0.0008" in text and len(reader.pages) > 1


@pytest.mark.parametrize("threshold,status", [(0, "no_qualifying_groups"), (101, "no_comparison_groups")])
def test_commonality_documents_preserve_degenerate_states(client, tmp_path, threshold, status):
    import json
    import zipfile
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.backends.backend_pdf import PdfPages
    from pypdf import PdfReader
    from ai4bi_web_api import core, exports
    from ai4bi_web_api.commonality import run_saved_analyses
    from ai4bi_web_api.jobs import make_snapshot
    ids, path, _ = workspace(client)
    payload = saved_settings(name="Degenerate")
    payload["settings"]["threshold"] = threshold
    assert command(client, path, 1, "save_commonality_analysis", payload, key="commonality-degenerate-save").status_code == 200
    store = client.app.state.store
    snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 2, {})
    analyses = run_saved_analyses(snapshot, core.load_contracts(store.root, snapshot["datasets"]))
    aid, analysis = next(iter(analyses.items()))
    assert analysis["status"] == status
    assert all(row["p_value"] is None for row in analysis["rows"])
    result = {"snapshot_id": snapshot["snapshot_id"], "visuals": {}, "commonality_analyses": analyses}
    output = tmp_path / "degenerate.zip"
    exports.csv_bundle(output, snapshot, result)
    with zipfile.ZipFile(output) as archive:
        assert json.loads(archive.read("analysis.json"))["analysis"]["commonality_analyses"][aid] == analysis
        entry = json.loads(archive.read("manifest.json"))["tables"][1]
        assert entry["columns"][-1] == "p_value" and entry["row_count"] == len(analysis["rows"])
    output = tmp_path / "degenerate.pdf"
    with matplotlib.rc_context({"font.sans-serif": ["Microsoft JhengHei"], "pdf.fonttype": 42}):
        with PdfPages(output) as pdf:
            exports.pdf_commonality_pages(pdf, snapshot, result, "Snapshot")
    text = "".join(page.extract_text() or "" for page in PdfReader(output).pages)
    # Long status words wrap within table cells; compare without whitespace.
    assert status in "".join(text.split())


def test_commonality_settings_validation_is_atomic(client):
    import copy
    from ai4bi_web_api.commonality import validate_saved_analyses
    from ai4bi_web_api.report_extensions import extensions
    from ai4bi_web_api.core import load_contracts
    from ai4bi_web_api.jobs import make_snapshot
    ids, path, _ = workspace(client)
    payload = saved_settings()
    payload["settings"]["value_column"] = "wafer_id"
    failed = command(client, path, 1, "save_commonality_analysis", payload, key="commonality-invalid-save")
    assert failed.status_code == 409 and client.get(path).json()["revision"] == 1
    saved = command(client, path, 1, "save_commonality_analysis", saved_settings(), key="commonality-valid-save")
    assert saved.status_code == 200, saved.text
    assert command(client, path, 2, "save_commonality_analysis", saved_settings(name="YIELD COMMONALITY"), key="commonality-duplicate-name").status_code == 400
    snapshot = make_snapshot(client.app.state.store, ids["workspace_id"], ids["report_id"], 2, {})
    contracts = load_contracts(client.app.state.store.root, snapshot["datasets"])
    definitions = extensions(snapshot["report"]).commonality_analyses
    changed = copy.deepcopy(contracts)
    next(c for c in changed["fab_wafer_yield"].columns if c.name == "yield_pct").data_type = "integer"
    with pytest.raises(AppError) as caught:
        validate_saved_analyses(snapshot["report"], changed, definitions)
    assert caught.value.code == "COMMONALITY_SETTINGS_INCOMPATIBLE"


@pytest.mark.parametrize("operation", ["publish", "json", "csv", "xlsx", "pdf"])
def test_commonality_delivery_contains_all_saved_results(client, tmp_path, operation):
    import json, zipfile
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.exports import export_snapshot, export_suffix
    from ai4bi_web_api.publications import check_publication
    ids, path, _ = workspace(client)
    assert command(client, path, 1, "save_commonality_analysis", saved_settings(), key="commonality-delivery-save").status_code == 200
    snapshot = make_snapshot(client.app.state.store, ids["workspace_id"], ids["report_id"], 2, {"format": operation})
    aid = snapshot["report"]["web_extensions"]["commonality_analyses"][0]["analysis_id"]
    if operation == "publish":
        checks = check_publication(client.app.state.store.root, snapshot)["checks"]
        assert checks["execution_contract"] == "web-query-v7"
        assert checks["commonality_analyses"][aid]["population_count"] == 100
    else:
        output = tmp_path / "delivery"
        output.mkdir()
        export_snapshot(client.app.state.store.root, snapshot, output)
        artifact = output / ("export." + export_suffix(operation))
        assert artifact.stat().st_size > 100
        if operation == "json":
            analysis = json.loads(artifact.read_text(encoding="utf-8"))["analysis"]
            assert analysis["commonality_analyses"][aid]["qualifying_count"] == 11
            assert analysis["execution_contract"] == "web-query-v7"
        elif operation == "csv":
            with zipfile.ZipFile(artifact) as archive:
                analysis = json.loads(archive.read("analysis.json"))["analysis"]
                assert analysis["commonality_analyses"][aid]["qualifying_count"] == 11
                assert "commonality/001-entities.csv" in archive.namelist()
        elif operation == "xlsx":
            from openpyxl import load_workbook
            book = load_workbook(artifact)
            assert book["CM_002_entities"].max_row == 12
            assert book["CM_002_entities"]["A1"].comment.text == aid
        else:
            from pypdf import PdfReader
            reader = PdfReader(artifact)
            text = "".join(page.extract_text() or "" for page in reader.pages)
            assert aid in "".join(text.split()) and "0.0008" in text


def test_published_commonality_remains_fixed_after_draft_changes(client):
    _, path, _ = workspace(client)
    saved = command(client, path, 1, "save_commonality_analysis", saved_settings(), key="commonality-publish-save")
    item = saved.json()["report"]["web_extensions"]["commonality_analyses"][0]
    accepted = client.post(path + "/publications", json={"base_revision": 2, "idempotency_key": "commonality-publish"})
    published = wait_job(client, accepted.json()["job_id"])
    assert published["status"] == "succeeded", published
    target = path + "/publications/" + published["result"]["publication_id"]
    detail = client.get(target).json()
    assert detail["checks"]["commonality_analyses"][item["analysis_id"]]["qualifying_count"] == 11
    assert command(client, path, 2, "delete_commonality_analysis", {"analysis_id": item["analysis_id"]}, key="commonality-published-delete").status_code == 200
    accepted = client.post(target + "/queries", json={"base_revision": 2, "idempotency_key": "commonality-published-query", "include_commonality": True})
    result = wait_job(client, accepted.json()["job_id"])
    assert result["status"] == "succeeded", result
    analysis = result["result"]["commonality_analyses"][item["analysis_id"]]
    assert analysis["settings"] == item and analysis["qualifying_count"] == 11
    assert client.get(target).json()["report"]["web_extensions"]["commonality_analyses"] == [item]
    assert client.post(path + "/exports", json={"base_revision": 3, "idempotency_key": "commonality-no-export-optout", "include_commonality": False}).status_code == 422
    assert client.post(path + "/queries", json={"base_revision": 3, "idempotency_key": "commonality-invalid-include", "include_commonality": "yes"}).status_code == 422


@pytest.mark.parametrize("kind", ["publish", "json", "csv", "xlsx", "pdf"])
def test_saved_commonality_failure_prevents_partial_delivery(client, tmp_path, monkeypatch, kind):
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.publications import check_publication
    from ai4bi_web_api.exports import export_snapshot
    ids, path, _ = workspace(client)
    assert command(client, path, 1, "save_commonality_analysis", saved_settings(), key="commonality-failed-delivery-save").status_code == 200
    snapshot = make_snapshot(client.app.state.store, ids["workspace_id"], ids["report_id"], 2, {"format": kind})
    def fail(*args):
        raise AppError("COMMONALITY_LIMIT", "Injected limit")
    monkeypatch.setattr("ai4bi_web_api.commonality.scan_snapshot", fail)
    output = tmp_path / "failed-delivery"
    output.mkdir()
    with pytest.raises(AppError) as caught:
        if kind == "publish":
            check_publication(client.app.state.store.root, snapshot)
        else:
            export_snapshot(client.app.state.store.root, snapshot, output)
    assert caught.value.code == "COMMONALITY_LIMIT" and list(output.iterdir()) == []


@pytest.mark.parametrize("mutation", ["missing", "extra", "bool_count", "wrong_total", "wrong_status", "old_contract"])
def test_commonality_delivery_rejects_inconsistent_checks(client, mutation):
    from ai4bi_web_api.commonality import validate_delivery_checks
    _, path, _ = workspace(client)
    saved = command(client, path, 1, "save_commonality_analysis", saved_settings(), key="commonality-checks-save")
    body = saved.json()["report"]
    aid = body["web_extensions"]["commonality_analyses"][0]["analysis_id"]
    checks = {aid: {"analysis_contract": "commonality-v1", "status": "ready", "population_count": 100, "qualifying_count": 11, "comparison_count": 89}}
    if mutation == "missing":
        checks = {}
    elif mutation == "extra":
        checks["other"] = checks[aid]
    elif mutation == "bool_count":
        checks[aid]["qualifying_count"] = True
    elif mutation == "wrong_total":
        checks[aid]["comparison_count"] = 90
    elif mutation == "wrong_status":
        checks[aid]["status"] = "empty"
    else:
        checks[aid]["analysis_contract"] = "old"
    with pytest.raises(AppError) as caught:
        validate_delivery_checks(body, checks)
    assert caught.value.code == "COMMONALITY_DELIVERY_INVALID"


def test_default_chart_query_does_not_run_commonality(client, monkeypatch):
    from ai4bi_web_api.core import run_query
    from ai4bi_web_api.jobs import make_snapshot
    ids, path, _ = workspace(client)
    assert command(client, path, 1, "save_commonality_analysis", saved_settings(), key="commonality-default-query-save").status_code == 200
    store = client.app.state.store
    snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 2, {})
    monkeypatch.setattr("ai4bi_web_api.commonality.run_saved_analyses", lambda *args: pytest.fail("Default chart query ran saved analyses"))
    assert run_query(store.root, snapshot)["commonality_analyses"] == {}


def test_http_worker_commonality_and_idempotent_snapshot(client):
    ids, path, _ = workspace(client)
    body = request()
    accepted = client.post(path + "/analyses/commonality", json=body)
    assert accepted.status_code == 202, accepted.text
    job = wait_job(client, accepted.json()["job_id"])
    assert job["status"] == "succeeded", job
    result = job["result"]
    assert result["population_count"] == 100 and result["status"] == "ready"
    assert any(row["entity"] == "ETCH-02" and row["lift"] > 1 for row in result["rows"])
    assert result["analysis_contract"] == "commonality-v1" and result["data_versions"]
    assert command(client, path, 1, "save", key="save-after-commonality").status_code == 200
    assert client.post(path + "/analyses/commonality", json=body).json() == accepted.json()
    conflict = client.post(path + "/analyses/commonality", json=request(threshold=0.9))
    assert conflict.status_code == 409


def test_commonality_saved_and_transient_scope_intersect(client):
    _, path, _ = workspace(client)
    saved = command(client, path, 1, "add_filter", {"filter": {
        "scope": "report", "block_id": "fab_process_move", "column_name": "step_name",
        "operator": "eq", "value": "Etch"}}, key="commonality-saved-filter")
    assert saved.status_code == 200, saved.text
    body = request(base_revision=2, selected_component_id="bar_qt_step", filters=[{
        "source_visual_id": "bar_qt_step", "block_id": "fab_process_move", "column_name": "step_name",
        "operator": "eq", "value": "Litho"}])
    accepted = client.post(path + "/analyses/commonality", json=body)
    assert accepted.status_code == 202, accepted.text
    job = wait_job(client, accepted.json()["job_id"])
    assert job["status"] == "succeeded", job
    assert job["result"]["status"] == "empty"
    assert job["result"]["applied_filters"] == body["filters"]


def test_commonality_invalid_field_fails_job_without_partial_result(client):
    _, path, _ = workspace(client)
    accepted = client.post(path + "/analyses/commonality", json=request(value_column="missing"))
    job = wait_job(client, accepted.json()["job_id"])
    assert job["status"] == "failed" and job["result"] is None
    assert job["error"]["code"] == "INVALID_COMMONALITY"
    assert client.post(path + "/analyses/commonality", json=request(threshold=True)).status_code == 422


def test_commonality_old_contract_rejected_before_source_read(client, monkeypatch):
    from ai4bi_web_api.commonality import run_commonality
    from ai4bi_web_api.jobs import make_snapshot
    ids, _, _ = workspace(client)
    snapshot = make_snapshot(client.app.state.store, ids["workspace_id"], ids["report_id"], 1,
                             {**request(), "analysis_contract": "old"})
    monkeypatch.setattr("ai4bi_web_api.core.load_contracts", lambda *args: pytest.fail("Read incompatible source"))
    with pytest.raises(AppError) as caught:
        run_commonality(client.app.state.store.root, snapshot)
    assert caught.value.code == "COMMONALITY_INCOMPATIBLE"


def run(detail=None, outcomes=None, **options):
    if detail is None:
        detail = pd.DataFrame({"lot": list("aabbcd"), "tool": ["X", "X", "X", "X", "Y", "Y"]})
    if outcomes is None:
        outcomes = pd.DataFrame({"id": list("abcd"), "yield": [0.5, 0.6, 0.9, 1.0]})
    return scan(detail, outcomes, entity_column="tool", group_column="lot",
                outcome_group_column="id", value_column="yield", threshold=options.pop("threshold", 0.8), **options)


def test_known_contingency_and_duplicate_exposures():
    result = run()
    assert result["population_count"] == 4
    assert result["qualifying_count"] == result["comparison_count"] == 2
    assert result["rows"] == [{"entity": "X", "qualifying_count": 2,
                               "coverage_percent": 100.0, "lift": 2.0, "p_value": 0.1667}]


def test_population_intersection_precedes_statistics():
    detail = pd.DataFrame({"lot": list("abcde"), "tool": list("XXYYX")})
    outcomes = pd.DataFrame({"id": list("abcdf"), "yield": [0.5, 0.6, 0.9, 1.0, 0.1]})
    result = run(detail, outcomes)
    assert result["rows"] == run()["rows"]
    assert result["unmeasured_group_count"] == result["unexposed_group_count"] == 1


@pytest.mark.parametrize("threshold,status", [(0, "no_qualifying_groups"), (2, "no_comparison_groups")])
def test_degenerate_population_is_explicit(threshold, status):
    result = run(threshold=threshold)
    assert result["status"] == status
    assert all(row["p_value"] is None for row in result["rows"])


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), True, "0.8"])
def test_reject_invalid_threshold(threshold):
    with pytest.raises(AppError, match="門檻"):
        run(threshold=threshold)


def test_aggregate_outcomes_before_matching_and_do_not_mutate():
    outcomes = pd.DataFrame({"id": list("aabcd"), "yield": [0.1, 0.9, 0.6, 0.9, 1.0]})
    original = outcomes.copy(deep=True)
    assert run(outcomes=outcomes)["rows"] == run()["rows"]
    assert run(outcomes=outcomes, aggregation="sum")["qualifying_count"] == 1
    pd.testing.assert_frame_equal(outcomes, original)


def test_reject_mixed_key_types_and_nonfinite_values():
    with pytest.raises(AppError, match="識別型別"):
        run(outcomes=pd.DataFrame({"id": [1, "b"], "yield": [0.1, 0.2]}))
    with pytest.raises(AppError, match="非有限"):
        run(outcomes=pd.DataFrame({"id": ["a"], "yield": [float("inf")]}))


def test_null_exposure_does_not_enter_population():
    result = run(detail=pd.DataFrame({"lot": ["a", "b", None], "tool": [None, "X", "Y"]}))
    assert result["population_count"] == 1
    assert result["excluded_detail_rows"] == 2
    assert result["unexposed_group_count"] == 3


def test_empty_intersection_is_not_a_negative_finding():
    result = run(outcomes=pd.DataFrame({"id": ["z"], "yield": [0.1]}))
    assert result["status"] == "empty" and result["rows"] == []
    assert result["population_count"] == 0


@pytest.mark.parametrize("comparison,count", [("lt", 1), ("lte", 2), ("gt", 2), ("gte", 3)])
def test_threshold_boundary(comparison, count):
    assert run(threshold=0.6, comparison=comparison)["qualifying_count"] == count


def test_entity_limit_rejects_instead_of_truncating(monkeypatch):
    monkeypatch.setattr("ai4bi_web_api.commonality.MAX_ENTITIES", 1)
    with pytest.raises(AppError) as caught:
        run()
    assert caught.value.code == "COMMONALITY_LIMIT"


def test_missing_statistical_dependency_fails_explicitly(monkeypatch):
    from ai4bi.analysis import crossfact
    original = crossfact.commonality
    monkeypatch.setattr(crossfact, "commonality", lambda *args: original(*args).drop(columns="p_value"))
    with pytest.raises(AppError) as caught:
        run()
    assert caught.value.code == "COMMONALITY_STATISTICS_UNAVAILABLE"


def test_categorical_unused_entities_are_not_in_population():
    detail = pd.DataFrame({"lot": list("abcd"),
                           "tool": pd.Categorical(list("XXYY"), categories=list("XYZ"))})
    assert run(detail=detail)["rows"] == run()["rows"]
