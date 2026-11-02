"""Probe an installed App through real loopback HTTP with checkout reads denied."""
from __future__ import annotations

import argparse
import csv
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-package-root", type=Path, required=True)
    parser.add_argument("--forbid-source", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    forbidden = [path.resolve() for path in args.forbid_source]
    expected = args.expected_package_root.resolve()
    output = args.output.resolve()

    def audit(event, values):
        if event == "open" and isinstance(values[0], (str, bytes)):
            candidate = Path(values[0].decode() if isinstance(values[0], bytes) else values[0]).resolve()
            if any(candidate.is_relative_to(path) for path in forbidden):
                raise PermissionError("Installed App attempted to read a source checkout")
        if event == "socket.connect" and values[1][0] not in ("127.0.0.1", "::1"):
            raise PermissionError("HTTP probe may only connect to loopback")

    sys.addaudithook(audit)
    import ai4bi
    import ai4bi_web_api
    from ai4bi_web_api.app import create_app
    from ai4bi_web_api.publications import EXECUTION_CONTRACT
    import uvicorn

    origins = {"ai4bi": str(Path(ai4bi.__file__).resolve()), "ai4bi_web_api": str(Path(ai4bi_web_api.__file__).resolve())}
    assert all(Path(path).is_relative_to(expected) for path in origins.values()), origins
    assert sys.prefix != sys.base_prefix
    assert "include-system-site-packages = false" in (expected / "pyvenv.cfg").read_text(encoding="utf-8")
    static = Path(ai4bi_web_api.__file__).parent / "static"
    manifest = json.loads((static / "asset-manifest.json").read_text(encoding="utf-8"))
    data = output.parent / "data"
    opener = build_opener(ProxyHandler({}))

    @contextmanager
    def running():
        code = secrets.token_urlsafe(24)
        instance=secrets.token_urlsafe(12)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(data, code,instance_id=instance,expected_build_id=manifest["build_id"]), host="127.0.0.1", port=port,
                                               access_log=False, log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        token = ""

        def request(path, body=None, status=200, *, raw_response=False):
            headers = {"Content-Type": "application/json", "x-ai4bi-request": "1"}
            if token:
                headers["Authorization"] = "Bearer " + token
            req = Request(f"http://127.0.0.1:{port}" + path,
                          data=json.dumps(body).encode("utf-8") if body is not None else None, headers=headers)
            try:
                response = opener.open(req, timeout=45)
            except HTTPError as exc:
                response = exc
            with response:
                raw = response.read()
                assert response.status == status, (path, response.status, raw[:300])
                if not raw_response and "application/json" in response.headers.get("Content-Type", ""):
                    return json.loads(raw)
                return raw

        try:
            deadline = time.monotonic() + 30
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("Installed server did not start")
                time.sleep(.05)
            ready = request("/ready?expected_instance_id="+instance+"&expected_build_id="+manifest["build_id"])
            assert request("/ready?expected_instance_id=previous-launch",status=409)["error"]["code"]=="READY_IDENTITY_MISMATCH"
            token = request("/api/v1/session", {"code": code})["token"]
            yield request, ready
        finally:
            server.should_exit = True
            thread.join(timeout=20)
            listener.close()
            assert not thread.is_alive(), "Installed server did not stop"

    def wait_job(request, jid):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            job = request("/api/v1/jobs/" + jid)
            if job["status"] in ("succeeded", "failed", "cancelled"):
                assert job["status"] == "succeeded", job
                return job["result"]
            time.sleep(.1)
        raise RuntimeError("Installed worker did not complete within 45 seconds")

    with running() as (request, ready):
        assert ready["build_id"] == manifest["build_id"]
        index = request("/")
        assert request("/workspace/deep/route") == index
        checked = []
        for path, checksum in manifest["files"].items():
            raw = request("/" + path, raw_response=True)
            assert hashlib.sha256(raw).hexdigest() == checksum, path
            checked.append(path)
        assert request("/api/v1/not-a-route", status=404)["error"]["code"] == "NOT_FOUND"
        assert request("/assets/missing.js", status=404)["error"]["code"] == "ASSET_NOT_FOUND"
        ids = request("/api/v1/workspaces", {"title": "Installed wheel", "template": "fab", "idempotency_key": "installed-workspace"})
        path = f"/api/v1/workspaces/{ids['workspace_id']}/reports/{ids['report_id']}"
        report = request(path)
        query = request(path + "/queries", {"base_revision": report["revision"], "idempotency_key": "installed-query"}, status=202)
        result = wait_job(request, query["job_id"])
        assert all(visual["status"] == "ready" for visual in result["visuals"].values()), result
        assert list(result["visuals"]["kpi_moves"]["rows"][0].values()) == [600]
        assert result["execution_contract"] == EXECUTION_CONTRACT
        assistant = request(path + "/assistant", {"base_revision": report["revision"], "idempotency_key": "installed-assistant",
                            "prompt": "rename this chart to Packaged moves", "selected_component_id": "kpi_moves"}, status=202)
        proposed = wait_job(request, assistant["job_id"])
        assert proposed["candidate_report"]["pages"]["main"]["visuals"]["kpi_moves"]["visualization"]["title"] == "Packaged moves"
        assert request(path) == report  # A proposal must not apply itself.
        export = request(path + "/exports", {"base_revision": report["revision"], "idempotency_key": "installed-export", "format": "xlsx"}, status=202)
        artifact = wait_job(request, export["job_id"])
        exported = request("/api/v1/artifacts/" + artifact["artifact_id"])
        with zipfile.ZipFile(io.BytesIO(exported)) as workbook:
            assert any(b"<v>600</v>" in workbook.read(name) for name in workbook.namelist() if name.startswith("xl/worksheets/"))
        pdf_job = request(path + "/exports", {"base_revision": report["revision"], "idempotency_key": "installed-pdf", "format": "pdf"}, status=202)
        pdf_artifact = wait_job(request, pdf_job["job_id"])
        pdf = request("/api/v1/artifacts/" + pdf_artifact["artifact_id"])
        assert pdf.startswith(b"%PDF-") and len(pdf) > 1000
        group={"scope":"report","block_id":"fab_process_move","expression":{"operator":"or","children":[
            {"block_id":"fab_process_move","column_name":"step_name","operator":"eq","value":name} for name in ("Etch","Lithography")]}}
        report=request(path+"/commands",{"base_revision":report["revision"],"request_id":"installed-group",
                       "idempotency_key":"installed-group","command_type":"add_filter","payload":{"filter":group}})
        definition=report["report"]
        metric=definition["pages"]["main"]["visuals"]["bar_qt_step"]["query"]["metrics"][0]
        definition["pages"]["main"]["visuals"]["bar_qt_step"]["query"]["having"]=[
            {"block_id":metric["block_id"],"metric_name":metric["metric_name"],"operator":"gt","value":3}]
        report=request(path+"/commands",{"base_revision":report["revision"],"request_id":"installed-having",
                       "idempotency_key":"installed-having","command_type":"replace_report","payload":{"report":definition}})
        spc_settings = {"block_id": "fab_process_move", "entity_column": "tool_id",
                        "value_column": "queue_time_hr", "aggregation": "mean", "k": 1.5}
        report = request(path + "/commands", {"base_revision": report["revision"], "request_id": "installed-spc-save",
            "idempotency_key": "installed-spc-save", "command_type": "save_spc_analysis",
            "payload": {"name": "Installed SPC", "page_id": "main", "selected_component_id": "bar_qt_step", "settings": spc_settings}})
        spc_definition = report["report"]["web_extensions"]["spc_analyses"][0]
        spc_job = request(path + "/analyses/spc", {"base_revision": report["revision"], "idempotency_key": "installed-spc-scan",
            **spc_settings, "selected_component_id": "bar_qt_step", "exploration_page_id": "main"}, status=202)
        spc = wait_job(request, spc_job["job_id"])
        assert spc["input_rows"] == 200 and spc["entity_count"] == 4 and spc["status"] == "ready"
        cm_settings = {"block_id": "fab_process_move", "outcome_block_id": "fab_wafer_yield",
                       "entity_column": "tool_id", "group_column": "wafer_id", "outcome_group_column": "wafer_id",
                       "value_column": "yield_pct", "threshold": 80.0, "aggregation": "mean", "comparison": "lt"}
        report = request(path + "/commands", {"base_revision": report["revision"], "request_id": "installed-cm-save",
            "idempotency_key": "installed-cm-save", "command_type": "save_commonality_analysis",
            "payload": {"name": "Installed Commonality", "page_id": "main", "selected_component_id": "bar_qt_step", "settings": cm_settings}})
        cm_definition = report["report"]["web_extensions"]["commonality_analyses"][0]
        cm_job = request(path + "/analyses/commonality", {"base_revision": report["revision"], "idempotency_key": "installed-cm-scan",
            **cm_settings, "selected_component_id": "bar_qt_step", "exploration_page_id": "main"}, status=202)
        cm = wait_job(request, cm_job["job_id"])
        assert cm["population_count"] == 100 and cm["qualifying_count"] == 11 and cm["status"] == "ready"
        assert cm["rows"][0]["entity"] == "ETCH-02" and cm["rows"][0]["p_value"] == 0.0008
        cf_settings = {"block_a": "fab_process_move", "block_b": "fab_wafer_yield", "key_a": "lot_id", "key_b": "lot_id",
                       "metric_a": {"kind": "aggregate", "column": "queue_time_hr", "aggregation": "AVG"},
                       "metric_b": {"kind": "weighted_ratio", "numerator_column": "good_die", "denominator_column": "tested_die", "scale": 100.0},
                       "operation": "ratio", "quantiles": 5}
        report = request(path + "/commands", {"base_revision": report["revision"], "request_id": "installed-cf-save",
            "idempotency_key": "installed-cf-save", "command_type": "save_crossfact_analysis",
            "payload": {"name": "Installed Crossfact", "page_id": "main", "selected_component_id": "bar_qt_step", "settings": cf_settings}})
        cf_definition = report["report"]["web_extensions"]["crossfact_analyses"][0]
        cf_job = request(path + "/analyses/crossfact", {"base_revision": report["revision"], "idempotency_key": "installed-cf-scan",
            **cf_settings, "selected_component_id": "bar_qt_step", "exploration_page_id": "main"}, status=202)
        cf = wait_job(request, cf_job["job_id"])
        assert cf["sources"]["a"]["input_rows"] == 200 and cf["aligned_count"] == cf["paired_count"] == 20
        assert cf["status"] == "ready" and len(cf["rows"]) == 20 and sum(row["count"] for row in cf["cohorts"]) == 20
        change_settings = {"block_id": "fab_wafer_yield", "metric_name": "weighted_yield_pct",
                           "date_column": "test_date", "dimension_column": "product_family", "period": "week",
                           "filter_policy": "replace", "anchor": None}
        report = request(path + "/commands", {"base_revision": report["revision"], "request_id": "installed-change-save",
            "idempotency_key": "installed-change-save", "command_type": "save_change_analysis",
            "payload": {"name": "Installed change", "page_id": "main", "selected_component_id": "bar_yield_prod", "settings": change_settings}})
        change_definition = report["report"]["web_extensions"]["change_analyses"][0]
        change_job = request(path + "/analyses/change", {"base_revision": report["revision"], "idempotency_key": "installed-change-run",
            **change_settings, "selected_component_id": "bar_yield_prod", "exploration_page_id": "main"}, status=202)
        change = wait_job(request, change_job["job_id"])
        assert change["group_count"] == len(change["rows"]) == 5 and change["additive"] is False
        assert change["analysis_contract"] == "change-v2" and change["execution_contract"] == EXECUTION_CONTRACT
        csv_job=request(path+"/exports",{"base_revision":report["revision"],"idempotency_key":"installed-csv","format":"csv"},status=202)
        csv_artifact=wait_job(request,csv_job["job_id"])
        csv_bytes=request("/api/v1/artifacts/"+csv_artifact["artifact_id"])
        with zipfile.ZipFile(io.BytesIO(csv_bytes)) as archive:
            csv_manifest=json.loads(archive.read("manifest.json"))
            analysis=json.loads(archive.read("analysis.json"))["analysis"]
            assert csv_manifest["execution_contract"] == analysis["execution_contract"] == EXECUTION_CONTRACT
            assert list(analysis["visuals"]["kpi_moves"]["rows"][0].values())==[200]
            assert analysis["visuals"]["bar_qt_step"]["row_count"]==1
            assert list(analysis["visuals"]["bar_qt_step"]["rows"][0].values())[0]=="Etch"
            table=next(t for t in csv_manifest["tables"] if t.get("visual_id")=="kpi_moves")
            csv_rows=list(csv.reader(io.StringIO(archive.read(table["file"]).decode("utf-8-sig"))))
            assert float(csv_rows[1][0])==200 and csv_manifest["revision"]==report["revision"]
            csv_spc = analysis["spc_analyses"][spc_definition["analysis_id"]]
            assert csv_manifest["format_version"] == 2 and csv_spc["settings"] == spc_definition
            assert csv_spc["points"] == spc["points"] and csv_spc["input_rows"] == 200
            csv_cm = analysis["commonality_analyses"][cm_definition["analysis_id"]]
            assert csv_cm["settings"] == cm_definition and csv_cm["rows"] == cm["rows"]
            assert csv_cm["data_versions"] == cm["data_versions"]
            csv_cf = analysis["crossfact_analyses"][cf_definition["analysis_id"]]
            csv_change = analysis["change_analyses"][change_definition["analysis_id"]]
            assert csv_change["settings"] == change_definition
            for field in ("rows", "overall_current", "overall_previous", "overall_delta", "data_versions"):
                assert csv_change[field] == change[field]
            change_table = next(t for t in csv_manifest["tables"] if t.get("kind") == "change_groups")
            change_rows = list(csv.DictReader(io.StringIO(archive.read(change_table["file"]).decode("utf-8-sig"))))
            assert change_table["row_count"] == len(change_rows) == 5
            for row, expected in zip(change_rows, change["rows"]):
                assert row == {field: "" if value is None else str(value) for field, value in expected.items()}
            assert csv_cf["settings"] == cf_definition and csv_cf["data_versions"] == cf["data_versions"]
            for field in ("rows", "correlation", "cohorts", "sources"):
                assert csv_cf[field] == cf[field]
            aligned = next(t for t in csv_manifest["tables"] if t.get("kind") == "crossfact_aligned")
            assert aligned["analysis_id"] == cf_definition["analysis_id"] and aligned["row_count"] == 20
            rows = list(csv.DictReader(io.StringIO(archive.read(aligned["file"]).decode("utf-8-sig"))))
            assert len(rows) == 20
            for row, expected in zip(rows, cf["rows"]):
                assert row["key"] == expected["key"]
                for field in ("a", "b", "result"):
                    assert float(row[field]) == expected[field]
        saved = request(path + "/commands", {"base_revision": report["revision"], "request_id": "installed-save",
                        "idempotency_key": "installed-save", "command_type": "save", "payload": {}})
        assert not saved["dirty"]
        publishing = request(path + "/publications", {"base_revision": saved["revision"],
                            "idempotency_key": "installed-publication"}, status=202)
        publication_id = wait_job(request, publishing["job_id"])["publication_id"]
        publication_path = path + "/publications/" + publication_id
        publication = request(publication_path)
        assert publication["runtime_compatible"] and publication["checks"]["execution_contract"] == EXECUTION_CONTRACT
        assert publication["checks"]["spc_analyses"][spc_definition["analysis_id"]]["input_rows"] == 200
        assert publication["checks"]["commonality_analyses"][cm_definition["analysis_id"]]["qualifying_count"] == 11
        assert publication["checks"]["crossfact_analyses"][cf_definition["analysis_id"]]["paired_count"] == 20
        assert publication["checks"]["change_analyses"][change_definition["analysis_id"]]["group_count"] == 5
    with running() as (request, restarted):
        assert restarted["instance_id"] != ready["instance_id"]
        assert restarted["build_id"] == ready["build_id"]
        assert request(path) == saved
        assert request("/api/v1/artifacts/" + artifact["artifact_id"]) == exported
        assert request("/api/v1/artifacts/"+csv_artifact["artifact_id"])==csv_bytes
        assert request(publication_path) == publication
        changed = request(path + "/commands", {"base_revision": saved["revision"], "request_id": "installed-cf-delete",
            "idempotency_key": "installed-cf-delete", "command_type": "delete_crossfact_analysis",
            "payload": {"analysis_id": cf_definition["analysis_id"]}})
        assert changed["report"]["web_extensions"]["crossfact_analyses"] == []
        assert request(publication_path)["report"]["web_extensions"]["crossfact_analyses"] == [cf_definition]
        changed = request(path + "/commands", {"base_revision": changed["revision"], "request_id": "installed-change-delete",
            "idempotency_key": "installed-change-delete", "command_type": "delete_change_analysis",
            "payload": {"analysis_id": change_definition["analysis_id"]}})
        assert changed["report"]["web_extensions"]["change_analyses"] == []
        assert request(publication_path)["report"]["web_extensions"]["change_analyses"] == [change_definition]
        published_query = request(publication_path + "/queries", {"base_revision": saved["revision"],
                                  "idempotency_key": "installed-publication-restart", "include_spc": True, "include_commonality": True, "include_crossfact": True, "include_change": True}, status=202)
        published_result = wait_job(request, published_query["job_id"])
        assert published_result["execution_contract"] == EXECUTION_CONTRACT
        assert list(published_result["visuals"]["kpi_moves"]["rows"][0].values()) == [200]
        restarted_spc = published_result["spc_analyses"][spc_definition["analysis_id"]]
        assert restarted_spc["settings"] == spc_definition and restarted_spc["points"] == spc["points"]
        assert restarted_spc["input_rows"] == 200 and restarted_spc["data_versions"] == csv_spc["data_versions"]
        restarted_cm = published_result["commonality_analyses"][cm_definition["analysis_id"]]
        assert restarted_cm["settings"] == cm_definition and restarted_cm["rows"] == cm["rows"]
        assert restarted_cm["data_versions"] == csv_cm["data_versions"]
        restarted_cf = published_result["crossfact_analyses"][cf_definition["analysis_id"]]
        assert restarted_cf["settings"] == cf_definition and restarted_cf["data_versions"] == csv_cf["data_versions"]
        for field in ("rows", "correlation", "cohorts", "sources"):
            assert restarted_cf[field] == cf[field]
        restarted_change = published_result["change_analyses"][change_definition["analysis_id"]]
        assert restarted_change["settings"] == change_definition
        for field in ("rows", "overall_current", "overall_previous", "overall_delta", "data_versions"):
            assert restarted_change[field] == change[field]
    evidence = {"origins": origins, "system_site_packages": False, "source_reads_denied": [str(path) for path in forbidden],
                "build_id": ready["build_id"], "checked_assets": checked, "deep_route": True, "api_404": True,
                "kpi_moves": 600, "xlsx_bytes": len(exported), "pdf_bytes": len(pdf), "mock_assistant_proposal": True,
                "restart_preserved_report_and_export": True}
    evidence.update(ready_identity_checked=True,group_filtered_moves=200,having_step="Etch",csv_bytes=len(csv_bytes),
                    csv_preserved_after_restart=True, execution_contract=EXECUTION_CONTRACT,
                    published_execution_contract_after_restart=True,
                    spc_input_rows=spc["input_rows"], spc_entity_count=spc["entity_count"],
                    spc_definition_id=spc_definition["analysis_id"], spc_preserved_after_restart=True,
                    commonality_definition_id=cm_definition["analysis_id"], commonality_population=cm["population_count"],
                    commonality_qualifying=cm["qualifying_count"], commonality_preserved_after_restart=True,
                    crossfact_definition_id=cf_definition["analysis_id"], crossfact_aligned=cf["aligned_count"],
                    crossfact_source_rows=cf["sources"]["a"]["input_rows"], crossfact_preserved_after_restart=True,
                    crossfact_published_replay_after_draft_delete=True,
                    change_definition_id=change_definition["analysis_id"], change_group_count=change["group_count"],
                    change_preserved_after_restart=True, change_published_replay_after_draft_delete=True)
    output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
