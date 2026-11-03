from __future__ import annotations

import copy
import json
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest

from ai4bi_web_api.app import create_app
from ai4bi_web_api.storage import Store
from ai4bi_web_api.errors import AppError


CODE = "a-local-test-pairing-code"


@pytest.mark.parametrize("mode", ["strict", "partitioned"])
def test_session_cookie_transport_preserves_authentication_and_origin_guards(tmp_path, mode):
    with TestClient(create_app(tmp_path / mode, CODE, session_cookie_mode=mode),
                    base_url="https://localhost") as client:
        response = client.post("/api/v1/session", json={"code": CODE}, headers={"origin": "https://other.example"})
        assert response.status_code == 403
        assert "set-cookie" not in response.headers
        response = client.post("/api/v1/session", json={"code": CODE}, headers={"origin": "https://localhost"})
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "Path=/" in cookie and "Max-Age=43200" in cookie
        assert "Domain=" not in cookie
        assert ("Secure" in cookie) == (mode == "partitioned")
        assert ("Partitioned" in cookie) == (mode == "partitioned")
        assert ("SameSite=none" in cookie) == (mode == "partitioned")
        assert ("SameSite=strict" in cookie) == (mode == "strict")
        # TestClient does not implement browser partitioning. It proves only the
        # HTTP contract and unchanged guards; real Electron covers persistence.
        assert client.get("/api/v1/workspaces").status_code == 200
        assert client.get("/api/v1/workspaces", headers={"origin": "https://other.example"}).status_code == 403
        assert client.post("/api/v1/workspaces", json={}).status_code == 403
        assert client.post("/api/v1/workspaces", json={}, headers={"x-ai4bi-request": "1"}).status_code == 422
        assert client.post("/api/v1/session", json={"code": CODE}).status_code == 401
        token = response.json()["token"]
        client.cookies.clear()
        assert client.get("/api/v1/workspaces").status_code == 401
        assert client.get("/api/v1/workspaces", headers={"authorization": "Bearer " + token}).status_code == 200
    with TestClient(create_app(tmp_path / mode, "next-launch", session_cookie_mode=mode),
                    base_url="https://localhost") as restarted:
        assert restarted.get("/api/v1/workspaces", headers={"authorization": "Bearer " + token}).status_code == 401


def test_unknown_cookie_mode_fails_before_creating_workspace(tmp_path):
    data = tmp_path / "data"
    with pytest.raises(ValueError, match="Invalid session cookie mode"):
        create_app(data, CODE, session_cookie_mode="none")
    assert not data.exists()


def test_ready_requires_expected_launch_identity_and_keeps_build_pinned(tmp_path):
    from ai4bi_web_api.static_assets import write_manifest
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>test</html>", encoding="utf-8")
    (static / "app.js").write_text("console.log('test')", encoding="utf-8")
    build = write_manifest(static)["build_id"]
    data = tmp_path / "data"
    with pytest.raises(AppError) as caught:
        create_app(data, CODE, static, instance_id="launch-one", expected_build_id="0" * 64)
    assert caught.value.code == "BUILD_ID_MISMATCH"
    assert not data.exists()
    with TestClient(create_app(data, CODE, static, instance_id="launch-one", expected_build_id=build)) as client:
        for params in ({"expected_instance_id": "launch-old"}, {"expected_build_id": "0" * 64}):
            response = client.get("/ready", params=params)
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "READY_IDENTITY_MISMATCH"
            assert response.headers["cache-control"] == "no-store"
        response = client.get("/ready", params={"expected_instance_id": "launch-one", "expected_build_id": build})
        assert response.status_code == 200
        assert response.json()["instance_id"] == "launch-one"
        assert response.json()["build_id"] == build
        assert client.get("/ready", params={"expected_instance_id": "bad/id"}).status_code == 422
        (static / "app.js").write_text("console.log('another valid build')", encoding="utf-8")
        write_manifest(static)
        assert client.get("/ready").json()["error"]["code"] == "BUILD_ID_MISMATCH"
        assert client.get("/health").status_code == 200


def test_cli_occupied_port_exits_without_creating_data_or_printing_pairing_code(tmp_path):
    import socket
    import subprocess
    import sys
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        result = subprocess.run([sys.executable, "-m", "ai4bi_web_api", "--port",
                                 str(occupied.getsockname()[1]), "--data-root", str(tmp_path / "data")],
                                capture_output=True, timeout=15)
    assert result.returncode == 1
    assert b"HTTP_BIND_FAILED" in result.stderr
    assert result.stdout == b""
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("option,value,expected", [
    ("--instance-id", "bad/id", b"Invalid instance ID"),
    ("--expected-build-id", "not-a-hash", b"Invalid expected build ID"),
    ("--expected-build-id", "0" * 64, b"BUILD_ID_MISMATCH"),
])
def test_cli_rejects_invalid_identity_before_loading_runtime(tmp_path, option, value, expected):
    import socket
    import subprocess
    import sys
    from ai4bi_web_api.static_assets import write_manifest
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>test</html>", encoding="utf-8")
    (static / "app.js").write_text("console.log('test')", encoding="utf-8")
    write_manifest(static)
    code = "\n".join([
        "import importlib.abc, runpy, sys",
        "class NoRuntime(importlib.abc.MetaPathFinder):",
        "    def find_spec(self, fullname, path=None, target=None):",
        "        if fullname in {'ai4bi_web_api.app', 'pandas', 'uvicorn'}:",
        "            raise AssertionError('Runtime loaded before rejecting identity')",
        "sys.meta_path.insert(0, NoRuntime())",
        "sys.argv[0] = 'ai4bi-web'",
        "runpy.run_module('ai4bi_web_api', run_name='__main__')",
    ])
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    data = tmp_path / "data"
    result = subprocess.run([sys.executable, "-c", code, "--port", str(port),
        "--data-root", str(data), "--static-root", str(static), option, value],
        capture_output=True, timeout=20)
    assert result.returncode == 1 and expected in result.stderr
    assert result.stdout == b"" and not data.exists()


def test_lazy_metadata_startup_does_not_load_analysis_runtime(tmp_path):
    import subprocess
    import sys
    from ai4bi_web_api.core import template
    from ai4bi_web_api.static_assets import write_manifest
    data, static = tmp_path / "data", tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>test</html>", encoding="utf-8")
    (static / "app.js").write_text("console.log('test')", encoding="utf-8")
    write_manifest(static)
    store = Store(data)
    try:
        ids = store.create_workspace("Metadata", template("blank")[0], "metadata-startup", "blank")
    finally:
        store.close()
    code = "\n".join([
        "import importlib.abc, sys",
        "from pathlib import Path",
        "class NoAnalysis(importlib.abc.MetaPathFinder):",
        "    def find_spec(self, fullname, path=None, target=None):",
        "        if fullname in {'pandas', 'ai4bi_web_api.core'}:",
        "            raise AssertionError('Metadata startup loaded analysis runtime')",
        "sys.meta_path.insert(0, NoAnalysis())",
        "from ai4bi_web_api.app import create_app",
        "from fastapi.testclient import TestClient",
        "app = create_app(Path(sys.argv[1]), 'metadata-startup-code', Path(sys.argv[2]))",
        "with TestClient(app) as client:",
        "    assert client.get('/ready').status_code == 200",
        "    assert client.get('/api/v1/workspaces').status_code == 401",
        "    assert client.post('/api/v1/session', json={'code': 'metadata-startup-code'}).status_code == 200",
        "    client.headers['x-ai4bi-request'] = '1'",
        "    assert len(client.get('/api/v1/workspaces').json()) == 1",
        "    path = '/api/v1/workspaces/' + sys.argv[3]",
        "    assert client.get(path + '/datasets').json() == []",
        "    assert client.get(path + '/imports').json() == []",
        "    assert client.get(path + '/reports/' + sys.argv[4]).json()['revision'] == 1",
        "    assert 'pandas' not in sys.modules and 'ai4bi_web_api.core' not in sys.modules",
    ])
    result = subprocess.run([sys.executable, "-c", code, str(data), str(static),
        ids["workspace_id"], ids["report_id"]], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")


def test_native_launcher_forwards_public_launch_identity(tmp_path, monkeypatch):
    import runpy
    import sys
    import ai4bi_web_api.__main__ as cli
    launcher = Path(__file__).resolve().parents[3] / "integrations/nativeapp/launcher.py"
    captured = []
    monkeypatch.setattr(cli, "main", lambda: captured.extend(sys.argv))
    monkeypatch.setenv("AI4BI_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("AI4BI_INSTANCE_ID", "host-launch-123")
    monkeypatch.setenv("AI4BI_EXPECTED_BUILD_ID", "a" * 64)
    monkeypatch.setattr(sys, "argv", [str(launcher), "--host", "127.0.0.1", "--port", "8765",
                                     "--root", str(tmp_path / "installation")])
    runpy.run_path(str(launcher), run_name="__main__")
    assert captured[captured.index("--instance-id") + 1] == "host-launch-123"
    assert captured[captured.index("--expected-build-id") + 1] == "a" * 64
    assert captured[captured.index("--session-cookie-mode") + 1] == "partitioned"
    assert Path(captured[captured.index("--data-root") + 1]) == (tmp_path / "data").resolve()


def test_cli_serves_reserved_socket_and_rejects_stale_instance(tmp_path):
    import socket
    import subprocess
    import sys
    from urllib.request import urlopen
    from urllib.error import HTTPError, URLError
    from ai4bi_web_api.static_assets import write_manifest
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>test</html>", encoding="utf-8")
    (static / "app.js").write_text("console.log('test')", encoding="utf-8")
    build = write_manifest(static)["build_id"]
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    args = [sys.executable, "-m", "ai4bi_web_api", "--host", "localhost", "--port", str(port),
            "--data-root", str(tmp_path / "data"), "--static-root", str(static),
            "--instance-id", "fresh-launch", "--expected-build-id", build]
    with (tmp_path / "server.log").open("wb") as log:
        process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 20
            address = f"http://127.0.0.1:{port}/ready"
            while True:
                assert process.poll() is None, "Server exited before readiness"
                try:
                    with urlopen(address + "?expected_instance_id=fresh-launch&expected_build_id=" + build, timeout=1) as response:
                        ready = json.load(response)
                    break
                except (URLError, TimeoutError):
                    assert time.monotonic() < deadline, "Server did not become ready"
                    time.sleep(0.1)
            assert ready["instance_id"] == "fresh-launch" and ready["build_id"] == build
            assert (tmp_path / "data/metadata.sqlite").exists()
            with pytest.raises(HTTPError) as rejected:
                urlopen(address + "?expected_instance_id=previous-launch", timeout=2)
            assert rejected.value.code == 409
            rejected.value.close()
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
    wrong = args[:-1] + ["0" * 64]
    wrong[wrong.index("--data-root") + 1] = str(tmp_path / "rejected-data")
    result = subprocess.run(wrong, capture_output=True, timeout=20)
    assert result.returncode == 1 and b"BUILD_ID_MISMATCH" in result.stderr
    assert result.stdout == b"" and not (tmp_path / "rejected-data").exists()


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "data", CODE)) as client:
        assert client.post("/api/v1/session", json={"code": CODE}).status_code == 200
        client.headers.update({"x-ai4bi-request": "1"})
        yield client


def workspace(client, template="fab", key="create-workspace-1"):
    response = client.post("/api/v1/workspaces", json={"title": "製程分析", "template": template, "idempotency_key": key})
    assert response.status_code == 200, response.text
    ids = response.json()
    path = f"/api/v1/workspaces/{ids['workspace_id']}/reports/{ids['report_id']}"
    return ids, path, client.get(path).json()


def command(client, path, revision, kind, payload=None, key="edit-report-1"):
    return client.post(path + "/commands", json={"request_id": key, "idempotency_key": key,
                                               "base_revision": revision, "command_type": kind,
                                               "payload": payload or {}})


def wait_job(client, jid):
    end = time.monotonic() + 45
    while time.monotonic() < end:
        body = client.get("/api/v1/jobs/" + jid).json()
        if body["status"] in ("succeeded", "failed", "cancelled"):
            return body
        time.sleep(0.1)
    pytest.fail("Job did not reach terminal status")


def test_summary_request_accepts_only_legacy_supported_periods_and_alert_operators(client):
    _, path, report = workspace(client)
    base = {"idempotency_key": "summary-request-check", "base_revision": report["revision"],
            "page_id": "main", "alert_rules": []}
    for extra in ({"period": "quarter"},
                  {"period": "week", "alert_rules": [{"block_id": "fab_process_move",
                    "metric_name": "moves", "operator": "gte", "threshold": 3}]}):
        response = client.post(path + "/summaries", json={**base, **extra,
            "idempotency_key": "summary-request-" + str(len(extra)) + str(extra.get("period"))})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_summary_job_rejects_alerts_for_unregistered_fact_metrics(client):
    _, path, report = workspace(client)
    response = client.post(path + "/summaries", json={
        "idempotency_key": "summary-invalid-metric-check", "base_revision": report["revision"],
        "page_id": "main", "period": "week", "alert_rules": [{
            "block_id": "not-a-fact", "metric_name": "arbitrary_metric", "operator": "gt", "threshold": 1,
        }],
    })
    assert response.status_code == 202
    result = wait_job(client, response.json()["job_id"])
    assert result["status"] == "failed"
    assert result["error"]["code"] == "INVALID_ALERT_RULE"


def test_alert_job_evaluates_any_fact_metric_with_an_explicit_scope(client):
    _, path, report = workspace(client)
    response = client.post(path + "/alerts", json={
        "idempotency_key": "fact-metric-scoped-alert",
        "base_revision": report["revision"],
        "alert_rules": [{
            "rule_id": "lots-in-etch", "block_id": "fab_process_move",
            "metric_name": "unique_lots", "operator": "gt", "threshold": -1,
            "filter_column": "step_name", "filter_value": "Etch",
        }],
    })
    assert response.status_code == 202, response.text
    result = wait_job(client, response.json()["job_id"])
    assert result["status"] == "succeeded", result
    alert = result["result"]["alerts"][0]
    assert alert["rule_id"] == "lots-in-etch"
    assert alert["fired"] is True and alert["value"] > 0
    assert "Etch" in alert["message"]
    assert result["result"]["revision"] == report["revision"]


def test_alert_request_requires_scope_column_and_value_together(client):
    _, path, report = workspace(client)
    response = client.post(path + "/alerts", json={
        "idempotency_key": "alert-scope-requires-value",
        "base_revision": report["revision"],
        "alert_rules": [{
            "rule_id": "scoped-rule", "block_id": "fab_process_move",
            "metric_name": "unique_lots", "operator": "gt", "threshold": 0,
            "filter_column": "step_name",
        }],
    })
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize("kind,payload", [
    ("add_filter", {"filter":{"scope":"report","block_id":"fab_process_move","column_name":"step_name","operator":"eq","value":"Etch"}}),
    ("save_bookmark", {"name":"Shared verification","view":{"page_id":"main","selected_visual_id":"kpi_moves","filters":[]}}),
])
def test_edit_uses_one_verified_source_set_but_next_request_rechecks(client, monkeypatch, kind, payload):
    import ai4bi_web_api.core as module
    ids, path, _ = workspace(client)
    store = client.app.state.store
    original = module._read_source
    loads = []

    def load(root, dataset):
        loads.append(dataset["version"])
        return original(root, dataset)

    monkeypatch.setattr(module, "_read_source", load)
    source_count = len(store.datasets(ids["workspace_id"]))
    first = command(client, path, 1, kind, payload, "one-source-read")
    assert first.status_code == 200, first.text
    assert len(loads) == source_count
    # An accepted retry performs no work; a new edit must verify sources again.
    assert command(client, path, 1, kind, payload, "one-source-read").json() == first.json()
    assert len(loads) == source_count
    dataset = store.datasets(ids["workspace_id"])[0]
    source = store.root / dataset["path"]
    source.write_bytes(source.read_bytes() + b"corrupt-next-request")
    second = command(client, path, 2, kind, payload, "new-source-read")
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "SOURCE_CORRUPT"
    assert len(loads) == source_count + 1
    assert client.get(path).json()["revision"] == 2


def test_filter_group_snapshot_bookmark_publication_and_ai_lifecycle(client,tmp_path):
    from test_report_extensions import grouped_filter_payload
    from ai4bi_web_api.core import load_contracts,run_query,run_assistant
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.exports import export_snapshot
    ids,path,initial=workspace(client)
    metric=initial["report"]["pages"]["main"]["visuals"]["kpi_moves"]["query"]["metrics"][0]
    column=metric["alias"] or metric["metric_name"]
    store=client.app.state.store
    added=command(client,path,1,"add_filter",{"filter":grouped_filter_payload()},"add-nested-group")
    assert added.status_code==200,added.text
    assert command(client,path,1,"add_filter",{"filter":grouped_filter_payload()},"add-nested-group").json()==added.json()
    current=added.json()
    group=current["report"]["web_extensions"]["persistent_filters"][0]
    assert group["expression"]["children"][1]["children"][1]["data_type"]=="float"
    old=make_snapshot(store,ids["workspace_id"],ids["report_id"],2,{"visual_ids":["kpi_moves"]})
    rows=load_contracts(store.root,old["datasets"])["fab_process_move"].data_source.records
    expected=sum(r["step_name"]=="Etch" or (r["priority"]=="Hot" and r["queue_time_hr"]>2) for r in rows)
    def moves(snapshot):return run_query(store.root,snapshot)["visuals"]["kpi_moves"]["rows"][0][column]
    assert moves(old)==expected
    saved=command(client,path,2,"save_bookmark",{"name":"Nested conditions","view":{"page_id":"main","selected_visual_id":"kpi_moves","filters":[]}},"bookmark-nested-group")
    assert saved.status_code==200,saved.text
    bookmark=saved.json()["report"]["web_extensions"]["bookmarks"][0]
    assert bookmark["persistent_filters"]==[group]
    published=client.post(path+"/publications",json={"base_revision":3,"idempotency_key":"publish-nested-group"})
    assert published.status_code==202,published.text
    result=wait_job(client,published.json()["job_id"])
    assert result["status"]=="succeeded",result
    pubpath=path+"/publications/"+result["result"]["publication_id"]
    removed=command(client,path,3,"delete_filter",{"filter_id":group["filter_id"]},"delete-nested-group")
    assert removed.status_code==200
    assert moves(make_snapshot(store,ids["workspace_id"],ids["report_id"],4,{}))==600
    undone=command(client,path,4,"undo",key="undo-nested-group")
    assert undone.json()["report"]["web_extensions"]["persistent_filters"]==[group]
    redone=command(client,path,5,"redo",key="redo-nested-group")
    assert redone.json()["report"]["web_extensions"]["persistent_filters"]==[]
    resolved=client.get(path+"/bookmarks/"+bookmark["bookmark_id"],params={"base_revision":6})
    assert resolved.status_code==200,resolved.text
    captured=make_snapshot(store,ids["workspace_id"],ids["report_id"],6,{"filter_bookmark_id":bookmark["bookmark_id"]})
    assert moves(captured)==expected and moves(old)==expected
    answer=run_assistant(store.root,{**captured,"prompt":"rename this chart to Grouped moves","selected_component_id":"kpi_moves"})
    assert answer["candidate_report"]["web_extensions"]["persistent_filters"]==[]
    destination=tmp_path/"nested-export"
    destination.mkdir()
    export_snapshot(store.root,{**captured,"format":"json"},destination)
    exported=json.loads((destination/"export.json").read_text(encoding="utf-8"))
    assert exported["report"]["web_extensions"]["persistent_filters"]==[group]
    query=client.post(pubpath+"/queries",json={"base_revision":3,"idempotency_key":"query-published-group","visual_ids":["kpi_moves"]})
    assert query.status_code==202,query.text
    result=wait_job(client,query.json()["job_id"])
    assert result["status"]=="succeeded",result
    assert result["result"]["visuals"]["kpi_moves"]["rows"][0][column]==expected


def test_having_saved_snapshot_publication_and_invalid_metric_are_isolated(client,tmp_path):
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.core import run_query
    from ai4bi_web_api.exports import export_snapshot
    ids,path,initial=workspace(client)
    body=copy.deepcopy(initial["report"])
    vid="bar_qt_step"
    query=body["pages"]["main"]["visuals"][vid]["query"]
    metric=query["metrics"][0]
    condition={"block_id":metric["block_id"],"metric_name":metric["metric_name"],"operator":"gt","value":5}
    query["having"]=[condition]
    added=command(client,path,1,"replace_report",{"report":body},"having-report-edit")
    assert added.status_code==200,added.text
    store=client.app.state.store
    old=make_snapshot(store,ids["workspace_id"],ids["report_id"],2,{"visual_ids":[vid]})
    filtered=run_query(store.root,old)["visuals"][vid]
    assert filtered["row_count"]==1 and list(filtered["rows"][0].values())[0]=="Etch"
    invalid=copy.deepcopy(added.json()["report"])
    invalid["pages"]["main"]["visuals"][vid]["query"]["metrics"][0]["metric_name"]="move_count"
    denied=command(client,path,2,"replace_report",{"report":invalid},"having-invalid-metric")
    assert denied.status_code==400 and denied.json()["error"]["code"]=="INVALID_HAVING_METRIC"
    assert client.get(path).json()==added.json()
    publication=client.post(path+"/publications",json={"base_revision":2,"idempotency_key":"having-publication"})
    assert publication.status_code==202,publication.text
    published=wait_job(client,publication.json()["job_id"])
    assert published["status"]=="succeeded",published
    body=copy.deepcopy(added.json()["report"])
    body["pages"]["main"]["visuals"][vid]["query"]["having"]=[]
    removed=command(client,path,2,"replace_report",{"report":body},"having-remove")
    assert removed.status_code==200
    current=make_snapshot(store,ids["workspace_id"],ids["report_id"],3,{"visual_ids":[vid]})
    assert run_query(store.root,current)["visuals"][vid]["row_count"]==6
    undone=command(client,path,3,"undo",key="having-undo")
    assert undone.json()["report"]["pages"]["main"]["visuals"][vid]["query"]["having"]==[condition]
    saved=command(client,path,4,"save",key="having-save")
    assert saved.status_code==200 and not saved.json()["dirty"]
    assert client.get(path).json()["report"]["pages"]["main"]["visuals"][vid]["query"]["having"]==[condition]
    export_snapshot(store.root,{**old,"format":"json"},tmp_path)
    exported=json.loads((tmp_path/"export.json").read_text(encoding="utf-8"))
    assert exported["analysis"]["visuals"][vid]["rows"]==filtered["rows"]
    pid=published["result"]["publication_id"]
    accepted=client.post(path+"/publications/"+pid+"/queries",json={"base_revision":2,"idempotency_key":"having-published-query","visual_ids":[vid]})
    assert accepted.status_code==202,accepted.text
    result=wait_job(client,accepted.json()["job_id"])
    assert result["status"]=="succeeded" and result["result"]["visuals"][vid]["rows"]==filtered["rows"]


def test_page_filter_group_copies_scope_and_delete_is_undoable(client):
    from test_report_extensions import grouped_filter_payload
    ids,path,_=workspace(client)
    raw={**grouped_filter_payload(),"scope":"page","page_id":"main"}
    added=command(client,path,1,"add_filter",{"filter":raw},"add-page-group")
    assert added.status_code==200,added.text
    group=added.json()["report"]["web_extensions"]["persistent_filters"][0]
    copied=command(client,path,2,"duplicate_page",{"page_id":"main"},"copy-page-group")
    assert copied.status_code==200,copied.text
    body=copied.json()["report"]
    groups=body["web_extensions"]["persistent_filters"]
    assert len(groups)==2 and groups[0]["filter_id"]!=groups[1]["filter_id"]
    assert groups[0]["expression"]==groups[1]["expression"]
    pid=groups[1]["page_id"]
    del body["pages"][pid]
    body["web_extensions"]["page_order"].remove(pid)
    # Submit the stale attached group: the API must prune it before validation.
    deleted=command(client,path,3,"replace_report",{"report":body},"delete-copy-group")
    assert deleted.status_code==200,deleted.text
    assert deleted.json()["report"]["web_extensions"]["persistent_filters"]==[group]
    restored=command(client,path,4,"undo",key="undo-delete-copy-group")
    assert restored.json()["report"]["web_extensions"]["persistent_filters"]==groups


def test_drill_hierarchy_queries_bookmarks_and_snapshot_export(client,tmp_path):
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.core import run_query,load_contracts
    from ai4bi_web_api.exports import export_snapshot
    ids,path,original = workspace(client)
    body = copy.deepcopy(original["report"])
    vid = "bar_qt_step"
    body["pages"]["main"]["visuals"][vid]["visualization"]["extra"]["drill_hierarchy"] = ["step_name","tool_id","lot_id"]
    edited = command(client,path,1,"replace_report",{"report":body},"configure-drill-hierarchy")
    assert edited.status_code == 200,edited.text
    store = client.app.state.store
    base = make_snapshot(store,ids["workspace_id"],ids["report_id"],2,{})
    top = run_query(store.root,base)
    config = top["visuals"][vid]["drill"]
    assert config["hierarchy"] == ["step_name","tool_id","lot_id"]
    state = {**config,"path":[{"column":"step_name","value":"Etch"}]}
    snap = make_snapshot(store,ids["workspace_id"],ids["report_id"],2,{"drill_state":{vid:state},"format":"json"})
    first = run_query(store.root,snap)
    result = first["visuals"][vid]
    assert result["query"]["dimensions"][0]["column_name"] == "tool_id"
    assert result["row_count"] > 0 and result["drill"]["path"] == state["path"]
    records = load_contracts(store.root,snap["datasets"])["fab_process_move"].data_source.records
    for row in result["rows"]:
        selected = [r["queue_time_hr"] for r in records if r["step_name"] == "Etch" and r["tool_id"] == row["tool_id"]]
        assert row[result["columns"][1]] == pytest.approx(sum(selected)/len(selected))
    assert first["visuals"]["kpi_moves"]["rows"] == top["visuals"]["kpi_moves"]["rows"]
    assert list(first["visuals"]["kpi_moves"]["rows"][0].values()) == [600]
    deep = {**state,"path":[*state["path"],{"column":"tool_id","value":result["rows"][0]["tool_id"]}]}
    next_result = run_query(store.root,{**snap,"drill_state":{vid:deep}})["visuals"][vid]
    assert next_result["query"]["dimensions"][0]["column_name"] == "lot_id"
    assert next_result["row_count"] > 0
    view = {"page_id":"main","selected_visual_id":vid,"filters":[],"drill_state":{vid:deep}}
    saved = command(client,path,2,"save_bookmark",{"name":"Deep","view":view},"save-drill-bookmark")
    assert saved.status_code == 200,saved.text
    bid = saved.json()["report"]["web_extensions"]["bookmarks"][0]["bookmark_id"]
    resolved = client.get(path+f"/bookmarks/{bid}",params={"base_revision":3})
    assert resolved.status_code == 200,resolved.text
    assert resolved.json()["view"]["drill_state"] == {vid:deep}
    changed = copy.deepcopy(saved.json()["report"])
    changed["pages"]["main"]["visuals"][vid]["visualization"]["extra"]["drill_hierarchy"] = []
    disabled = command(client,path,3,"replace_report",{"report":changed},"disable-drill-hierarchy")
    assert disabled.status_code == 200,disabled.text
    assert client.get(path+f"/bookmarks/{bid}",params={"base_revision":4}).status_code == 409
    # An accepted export retains its hierarchy even after the draft disables it.
    export_snapshot(store.root,snap,tmp_path)
    exported = json.loads((tmp_path/"export.json").read_text(encoding="utf-8"))
    assert exported["analysis"]["visuals"][vid]["rows"] == result["rows"]
    assert exported["analysis"]["drill_state"] == {vid:state}
    assert client.get(path).json() == disabled.json()


@pytest.mark.parametrize("change", ["order","type","value","depth","missing"])
def test_invalid_drill_rejected_before_job_acceptance(client,change):
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.core import run_query
    ids,path,original = workspace(client)
    body = copy.deepcopy(original["report"])
    vid = "bar_qt_step"
    body["pages"]["main"]["visuals"][vid]["visualization"]["extra"]["drill_hierarchy"] = ["step_name","tool_id"]
    edited = command(client,path,1,"replace_report",{"report":body},"configure-invalid-drill")
    assert edited.status_code == 200,edited.text
    store = client.app.state.store
    state = run_query(store.root,make_snapshot(store,ids["workspace_id"],ids["report_id"],2,{}))["visuals"][vid]["drill"]
    state["path"] = [{"column":"step_name","value":"Etch"}]
    if change == "order": state["path"][0]["column"] = "tool_id"
    elif change == "type": state["field_types"][0] = "integer"
    elif change == "value": state["path"][0]["value"] = 100
    elif change == "depth": state["path"].append({"column":"tool_id","value":"a"})
    else: vid = "missing"
    response = client.post(path+"/queries",json={"base_revision":2,"idempotency_key":"invalid-drill-query","drill_state":{vid:state}})
    assert response.status_code in (400,409),response.text
    assert client.get(path).json() == edited.json()


@pytest.mark.parametrize("kind", ["replace_report", "apply_proposal", "undo", "redo", "save", "restore_saved", "duplicate_page", "save_scenario", "update_scenario", "rename_scenario", "apply_scenario", "delete_scenario", "save_bookmark", "update_bookmark", "rename_bookmark", "delete_bookmark", "add_filter","update_filter","delete_filter", "save_spc_analysis", "update_spc_analysis", "rename_spc_analysis", "delete_spc_analysis", "save_commonality_analysis", "update_commonality_analysis", "rename_commonality_analysis", "delete_commonality_analysis", "save_crossfact_analysis", "update_crossfact_analysis", "rename_crossfact_analysis", "delete_crossfact_analysis"])
def test_read_only_report_rejects_every_mutating_command(client, kind):
    from ai4bi_web_api.core import template
    body, _ = template("blank")
    body["read_only"] = True
    ids = client.app.state.store.create_workspace("Read only", body, "read-only-fixture", "blank")
    path = f"/api/v1/workspaces/{ids['workspace_id']}/reports/{ids['report_id']}"
    original = client.get(path).json()
    candidate = copy.deepcopy(original["report"])
    candidate["read_only"] = False
    candidate["title"] = "Must not change"
    response = command(client, path, 1, kind, {"report":candidate}, "readonly-command")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "READ_ONLY"
    assert client.get(path).json() == original


def test_edit_cannot_turn_a_working_report_into_a_read_only_report(client):
    _, path, original = workspace(client, "blank")
    body = copy.deepcopy(original["report"])
    body["read_only"] = True
    assert command(client, path, 1, "replace_report", {"report":body}).status_code == 400
    assert client.get(path).json() == original


def exploration_view(body):
    source = next(vid for vid,v in body["pages"]["main"]["visuals"].items()
                  if any(d["column_name"] == "step_name" for d in v["query"]["dimensions"]))
    return {"page_id":"main","selected_visual_id":source,"filters":[
        {"source_visual_id":source,"block_id":"fab_process_move","column_name":"step_name","operator":"eq","value":"Etch"}]}


def test_persistent_filter_scopes_copy_undo_and_native_queries(client):
    from ai4bi_web_api.core import load_contracts,run_query
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.report_extensions import report_executor
    from ai4bi.query_spec import VisualQuerySpec,BlockRef,MetricRef
    ids,path,state = workspace(client)
    store = client.app.state.store
    def action(kind,payload=None):
        nonlocal state
        response = command(client,path,state["revision"],kind,payload,f"filter-command-{state['revision']}-{kind}")
        assert response.status_code == 200,response.text
        state = response.json()
        return state
    action("duplicate_page",{"page_id":"main"})
    copied = state["report"]["web_extensions"]["page_order"][1]
    copy_kpi = state["report"]["pages"][copied]["visual_order"][1]
    contracts = load_contracts(store.root,store.datasets(ids["workspace_id"]))
    records = contracts["fab_process_move"].data_source.records
    other = next(r["step_name"] for r in records if r["step_name"] != "Etch")
    move_id = next(r["move_id"] for r in records if r["step_name"] == "Etch")
    base = {"scope":"report","block_id":"fab_process_move","column_name":"step_name","operator":"in","value":["Etch",other]}
    action("add_filter",{"filter":base})
    action("add_filter",{"filter":{**base,"scope":"page","page_id":"main","operator":"eq","value":"Etch"}})
    def values():
        snap = make_snapshot(store,ids["workspace_id"],ids["report_id"],state["revision"],{})
        results = run_query(store.root,snap)["visuals"]
        return [list(results[key]["rows"][0].values())[0] for key in ["kpi_moves",copy_kpi]]
    assert values() == [100,200]
    action("add_filter",{"filter":{**base,"scope":"visual","page_id":"main","visual_id":"kpi_moves","column_name":"move_id","operator":"eq","value":move_id}})
    assert values() == [1,200]
    executor,_ = report_executor(state["report"],contracts,page_id="main")
    adhoc = VisualQuerySpec("new-nl-query",[BlockRef("fab_process_move")],metrics=[MetricRef("fab_process_move","move_count")])
    assert executor.run(adhoc).iloc[0,0] == 100
    executor,_ = report_executor(state["report"],contracts,page_id="main",visual_id="kpi_moves")
    assert executor.run(adhoc).iloc[0,0] == 1
    executor,_ = report_executor(state["report"],contracts)
    assert executor.run(adhoc).iloc[0,0] == 200
    original = copy.deepcopy(state["report"])
    visual_filter = original["web_extensions"]["persistent_filters"][-1]
    action("update_filter",{"filter_id":visual_filter["filter_id"],"filter":{**base,"scope":"visual","page_id":"main","visual_id":"kpi_moves","operator":"eq","value":"Etch"}})
    assert values() == [100,200]
    action("undo")
    assert values() == [1,200]
    action("duplicate_page",{"page_id":"main"})
    new_page = state["report"]["web_extensions"]["page_order"][1]
    filters = state["report"]["web_extensions"]["persistent_filters"]
    assert len(filters) == 5 and len({f["filter_id"] for f in filters}) == 5
    assert len([f for f in filters if f["page_id"] == new_page]) == 2
    body = copy.deepcopy(state["report"])
    del body["pages"][new_page]
    body["web_extensions"]["page_order"].remove(new_page)
    action("replace_report",{"report":body})
    assert len(state["report"]["web_extensions"]["persistent_filters"]) == 3
    action("undo")
    assert len(state["report"]["web_extensions"]["persistent_filters"]) == 5
    action("delete_filter",{"filter_id":visual_filter["filter_id"]})
    assert values() == [100,200]
    action("undo")
    assert values() == [1,200]


@pytest.mark.parametrize("changes", [
    {"column_name":"move_count","value":"1"},
    {"column_name":"move_count","value":True},
    {"column_name":"missing"},
    {"scope":"page","page_id":"missing"},
    {"scope":"visual","page_id":"main","visual_id":"missing"},
    {"data_type":"integer"},
    {"operator":"in","value":[]},
])
def test_invalid_persistent_filter_does_not_mutate_report(client,changes):
    _,path,original = workspace(client)
    predicate = {"scope":"report","block_id":"fab_process_move","column_name":"step_name","operator":"eq","value":"Etch",**changes}
    response = command(client,path,1,"add_filter",{"filter":predicate},"invalid-persistent-filter")
    assert response.status_code in (400,409),response.text
    assert client.get(path).json() == original


@pytest.mark.parametrize("scope", ["report","page","visual"])
def test_bookmark_captures_persistent_conditions_and_accepted_exports(client,tmp_path,scope):
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.core import run_query
    from ai4bi_web_api.exports import export_snapshot
    ids,path,original = workspace(client)
    predicate = {"scope":scope,"block_id":"fab_process_move","column_name":"step_name","operator":"eq","value":"Etch"}
    if scope != "report": predicate["page_id"] = "main"
    if scope == "visual": predicate["visual_id"] = "kpi_moves"
    added = command(client,path,1,"add_filter",{"filter":predicate},"add-bookmark-condition")
    assert added.status_code == 200,added.text
    fid = added.json()["report"]["web_extensions"]["persistent_filters"][0]["filter_id"]
    view = {"page_id":"main","selected_visual_id":"kpi_moves","filters":[]}
    saved = command(client,path,2,"save_bookmark",{"name":"Captured","view":view},"capture-bookmark-condition")
    assert saved.status_code == 200,saved.text
    bookmark = saved.json()["report"]["web_extensions"]["bookmarks"][0]
    bid = bookmark["bookmark_id"]
    assert bookmark["persistent_filters"][0]["filter_id"] == fid
    removed = command(client,path,3,"delete_filter",{"filter_id":fid},"delete-original-condition")
    assert removed.status_code == 200,removed.text
    resolved = client.get(path+f"/bookmarks/{bid}",params={"base_revision":4})
    assert resolved.status_code == 200,resolved.text
    assert resolved.json()["view"]["filter_bookmark_id"] == bid
    store = client.app.state.store
    def snapshot(extra):
        return make_snapshot(store,ids["workspace_id"],ids["report_id"],4,extra)
    captured = snapshot({"filter_bookmark_id":bid,"visual_ids":["kpi_moves"],"format":"json"})
    current = snapshot({"visual_ids":["kpi_moves"]})
    assert list(run_query(store.root,captured)["visuals"]["kpi_moves"]["rows"][0].values()) == [100]
    assert list(run_query(store.root,current)["visuals"]["kpi_moves"]["rows"][0].values()) == [600]
    assert client.get(path).json() == removed.json()
    from ai4bi_web_api.core import run_assistant
    proposal = run_assistant(store.root,{**captured,"prompt":"rename this chart to Captured analysis","selected_component_id":"kpi_moves"})
    assert proposal["candidate_report"]["web_extensions"]["persistent_filters"] == []
    assert proposal["candidate_report"]["pages"]["main"]["visuals"]["kpi_moves"]["visualization"]["title"] == "Captured analysis"
    # Saving while exploring captures the effective conditions, not the draft's empty set.
    cloned = command(client,path,4,"save_bookmark",{"name":"Captured again","view":{**view,"filter_bookmark_id":bid,"drill_state":{}}},"clone-active-bookmark")
    assert cloned.status_code == 200,cloned.text
    assert cloned.json()["report"]["web_extensions"]["bookmarks"][1]["persistent_filters"] == bookmark["persistent_filters"]
    updated = command(client,path,5,"update_bookmark",{"bookmark_id":bid,"view":view},"update-captured-to-empty")
    assert updated.status_code == 200,updated.text
    assert updated.json()["report"]["web_extensions"]["bookmarks"][0]["persistent_filters"] == []
    # Already accepted exports keep the old conditions after the bookmark is updated.
    directory = tmp_path / "accepted-export"
    directory.mkdir()
    exported = export_snapshot(store.root,captured,directory)
    content = json.loads((directory / "export.json").read_text(encoding="utf-8"))
    assert content["analysis"]["filter_bookmark_id"] == bid
    assert list(content["analysis"]["visuals"]["kpi_moves"]["rows"][0].values()) == [100]
    assert content["report"]["web_extensions"]["persistent_filters"] == bookmark["persistent_filters"]
    undone = command(client,path,6,"undo",key="undo-empty-bookmark")
    assert undone.status_code == 200
    assert undone.json()["report"]["web_extensions"]["bookmarks"][0]["persistent_filters"] == bookmark["persistent_filters"]


@pytest.mark.parametrize("change", ["visual","type"])
def test_bookmark_saved_condition_references_cannot_silently_disappear(client,change):
    ids,path,_ = workspace(client)
    added = command(client,path,1,"add_filter",{"filter":{"scope":"visual","page_id":"main","visual_id":"kpi_moves","block_id":"fab_process_move","column_name":"step_name","operator":"eq","value":"Etch"}},"saved-condition-reference")
    assert added.status_code == 200,added.text
    fid = added.json()["report"]["web_extensions"]["persistent_filters"][0]["filter_id"]
    saved = command(client,path,2,"save_bookmark",{"name":"Reference","view":{"page_id":"main","filters":[]}},"save-condition-reference")
    assert saved.status_code == 200,saved.text
    bid = saved.json()["report"]["web_extensions"]["bookmarks"][0]["bookmark_id"]
    removed = command(client,path,3,"delete_filter",{"filter_id":fid},"remove-condition-reference")
    assert removed.status_code == 200,removed.text
    current = removed.json()
    if change == "visual":
        body = copy.deepcopy(current["report"])
        del body["pages"]["main"]["visuals"]["kpi_moves"]
        body["pages"]["main"]["visual_order"].remove("kpi_moves")
        edited = command(client,path,4,"replace_report",{"report":body},"remove-bookmarked-visual")
        assert edited.status_code == 200,edited.text
        current = edited.json()
    else:
        with client.app.state.store.transaction() as db:
            row = next(r for r in db.execute("SELECT * FROM datasets WHERE wid=?",(ids["workspace_id"],)) if json.loads(r["contract"])["block_id"] == "fab_process_move")
            contract = json.loads(row["contract"])
            next(c for c in contract["columns"] if c["name"] == "step_name")["data_type"] = "integer"
            db.execute("UPDATE datasets SET contract=? WHERE id=?",(json.dumps(contract),row["id"]))
    result = client.get(path+f"/bookmarks/{bid}",params={"base_revision":current["revision"]})
    assert result.status_code in (400,409),result.text
    assert result.json()["error"]["code"] == ("INVALID_FILTER_SCOPE" if change == "visual" else "FILTER_FIELD_CHANGED")
    assert client.get(path).json() == current


def test_bookmark_empty_and_legacy_conditions_remain_distinct(client):
    from ai4bi_web_api.bookmarks import bookmark_filter_report
    from ai4bi_web_api.core import run_query
    from ai4bi_web_api.jobs import make_snapshot
    ids,path,original = workspace(client)
    view = {"page_id":"main","selected_visual_id":None,"filters":[]}
    saved = command(client,path,1,"save_bookmark",{"name":"Empty","view":view},"save-empty-conditions")
    assert saved.status_code == 200,saved.text
    bid = saved.json()["report"]["web_extensions"]["bookmarks"][0]["bookmark_id"]
    added = command(client,path,2,"add_filter",{"filter":{"scope":"report","block_id":"fab_process_move","column_name":"step_name","operator":"eq","value":"Etch"}},"add-after-empty-bookmark")
    assert added.status_code == 200,added.text
    body = added.json()["report"]
    legacy = copy.deepcopy(body)
    del legacy["web_extensions"]["bookmarks"][0]["persistent_filters"]
    assert bookmark_filter_report(legacy,bid) == legacy
    store = client.app.state.store
    snap = make_snapshot(store,ids["workspace_id"],ids["report_id"],3,{"filter_bookmark_id":bid,"visual_ids":["kpi_moves"]})
    assert list(run_query(store.root,snap)["visuals"]["kpi_moves"]["rows"][0].values()) == [600]
    rejected = client.post(path+"/queries",json={"base_revision":3,"idempotency_key":"missing-filter-bookmark","filter_bookmark_id":"missing"})
    assert rejected.status_code == 404
    assert client.get(path).json() == added.json()


def test_bookmark_lifecycle_replays_filters_without_editing_report(client,tmp_path):
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.core import run_query
    from ai4bi_web_api.recovery import restore_backup
    ids,path,original = workspace(client)
    view = exploration_view(original["report"])
    response = command(client,path,1,"save_bookmark",{"name":"  Etch view  ","view":view},"save-bookmark")
    assert response.status_code == 200, response.text
    saved = response.json()
    item = saved["report"]["web_extensions"]["bookmarks"][0]
    bid = item["bookmark_id"]
    assert item["name"] == "Etch view" and item["view"] == {**view,"filter_bookmark_id":None,"drill_state":{}}
    assert len(item["fields"]) == 1 and item["fields"][0]["column_name"] == "step_name"
    assert command(client,path,1,"save_bookmark",{"name":"  Etch view  ","view":view},"save-bookmark").json() == saved
    endpoint = path + f"/bookmarks/{bid}"
    resolved = client.get(endpoint,params={"base_revision":2})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["view"] == {**view,"filter_bookmark_id":bid,"drill_state":{}}
    assert client.get(path).json() == saved
    store = client.app.state.store
    snap = make_snapshot(store,ids["workspace_id"],ids["report_id"],2,{"filters":resolved.json()["view"]["filters"]})
    result = run_query(store.root,snap)["visuals"]
    assert list(result["kpi_moves"]["rows"][0].values()) == [100]
    assert len(result[view["selected_visual_id"]]["rows"]) == 6
    snap["filters"] = []
    assert list(run_query(store.root,snap)["visuals"]["kpi_moves"]["rows"][0].values()) == [600]
    assert client.get(endpoint,params={"base_revision":1}).status_code == 409
    assert client.get(endpoint.replace(ids["workspace_id"],"other-workspace"),params={"base_revision":2}).status_code == 404
    renamed = command(client,path,2,"rename_bookmark",{"bookmark_id":bid,"name":"Renamed"},"rename-bookmark").json()
    assert renamed["report"]["web_extensions"]["bookmarks"][0]["name"] == "Renamed"
    empty = {**view,"filters":[]}
    updated = command(client,path,3,"update_bookmark",{"bookmark_id":bid,"view":empty},"update-bookmark").json()
    assert client.get(endpoint,params={"base_revision":4}).json()["view"]["filters"] == []
    deleted = command(client,path,4,"delete_bookmark",{"bookmark_id":bid},"delete-bookmark").json()
    assert deleted["report"]["web_extensions"]["bookmarks"] == []
    assert client.get(endpoint,params={"base_revision":5}).status_code == 404
    restored = command(client,path,5,"undo",key="undo-bookmark-delete").json()
    assert restored["report"]["web_extensions"]["bookmarks"] == updated["report"]["web_extensions"]["bookmarks"]
    store.backup(tmp_path / "backup")
    restore_backup(tmp_path / "backup",tmp_path / "restored")
    recovered = Store(tmp_path / "restored")
    try:
        assert recovered.report(ids["workspace_id"],ids["report_id"])["report"] == restored["report"]
    finally:
        recovered.close()


@pytest.mark.parametrize("change", ["page","source","type"])
def test_stale_bookmark_is_preserved_and_refuses_to_resolve(client,change):
    ids,path,original = workspace(client)
    view = exploration_view(original["report"])
    response = command(client,path,1,"save_bookmark",{"name":"Etch","view":view},"save-bookmark")
    assert response.status_code == 200, response.text
    saved = response.json()
    bid = saved["report"]["web_extensions"]["bookmarks"][0]["bookmark_id"]
    if change == "type":
        store = client.app.state.store
        with store.transaction() as db:
            row = next(row for row in db.execute("SELECT * FROM datasets WHERE wid=?",(ids["workspace_id"],)) if json.loads(row["contract"])["block_id"] == "fab_process_move")
            contract = json.loads(row["contract"])
            next(c for c in contract["columns"] if c["name"] == "step_name")["data_type"] = "integer"
            db.execute("UPDATE datasets SET contract=? WHERE id=?",(json.dumps(contract),row["id"]))
        current = saved
    else:
        body = copy.deepcopy(saved["report"])
        if change == "page":
            body["pages"]["other"] = {"page_id":"other","title":"Other","visuals":{},"visual_order":[]}
            del body["pages"]["main"]
        else:
            page = body["pages"]["main"]
            del page["visuals"][view["selected_visual_id"]]
            page["visual_order"].remove(view["selected_visual_id"])
        response = command(client,path,2,"replace_report",{"report":body},"make-bookmark-stale")
        assert response.status_code == 200, response.text
        current = response.json()
    response = client.get(path+f"/bookmarks/{bid}",params={"base_revision":current["revision"]})
    assert response.status_code == 409 and response.json()["error"]["code"] == "BOOKMARK_INCOMPATIBLE"
    assert client.get(path).json() == current
    page_id = next(iter(current["report"]["pages"]))
    repaired = command(client,path,current["revision"],"update_bookmark",{"bookmark_id":bid,"view":{"page_id":page_id,"selected_visual_id":None,"filters":[]}},"repair-bookmark")
    assert repaired.status_code == 200, repaired.text
    assert client.get(path+f"/bookmarks/{bid}",params={"base_revision":repaired.json()["revision"]}).status_code == 200


@pytest.mark.parametrize("predicate", [
    {"operator":"eq","value":None}, {"operator":"in","value":"Etch"},
    {"operator":"is_null","value":"Etch"}, {"operator":"between","value":[1]},
    {"operator":"eq","value":{"sql":"DROP TABLE x"}}, {"operator":"invalid","value":1},
])
def test_invalid_bookmark_predicates_do_not_create_history(client,predicate):
    _,path,original = workspace(client)
    view = exploration_view(original["report"])
    view["filters"][0].update(predicate)
    response = command(client,path,1,"save_bookmark",{"name":"Bad","view":view},"invalid-bookmark")
    assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_BOOKMARK"
    assert client.get(path).json() == original


def test_readonly_bookmark_resolution_is_allowed(client):
    import pandas as pd
    from ai4bi_web_api.core import template
    from ai4bi_web_api.bookmarks import bookmark_command
    body,contracts = template("fab")
    body = bookmark_command(body,"save_bookmark",{"name":"Etch","view":exploration_view(body)},contracts)
    body["read_only"] = True
    store = client.app.state.store
    ids = store.create_workspace("Read-only bookmarks",body,"readonly-bookmarks","fab")
    for contract in contracts.values():
        store.publish_dataset(ids["workspace_id"],contract.model_dump(mode="json"),pd.DataFrame(contract.data_source.records))
    bid = body["web_extensions"]["bookmarks"][0]["bookmark_id"]
    path = f"/api/v1/workspaces/{ids['workspace_id']}/reports/{ids['report_id']}"
    original = client.get(path).json()
    response = client.get(path+f"/bookmarks/{bid}",params={"base_revision":1})
    assert response.status_code == 200, response.text
    assert client.get(path).json() == original


@pytest.mark.parametrize("kind", ["rename_bookmark","delete_bookmark"])
def test_bookmark_metadata_can_be_managed_when_source_is_unavailable(client,kind):
    ids,path,original = workspace(client)
    response = command(client,path,1,"save_bookmark",{"name":"Etch","view":exploration_view(original["report"])},"save-bookmark")
    assert response.status_code == 200, response.text
    saved = response.json()
    bid = saved["report"]["web_extensions"]["bookmarks"][0]["bookmark_id"]
    store = client.app.state.store
    dataset = store.datasets(ids["workspace_id"])[0]
    (store.root/dataset["path"]).write_bytes(b"test-owned damaged parquet")
    payload = {"bookmark_id":bid, **({"name":"Renamed"} if kind == "rename_bookmark" else {})}
    result = command(client,path,2,kind,payload,"manage-offline-bookmark")
    assert result.status_code == 200, result.text
    assert result.json()["report"]["pages"] == saved["report"]["pages"]
    restored = command(client,path,3,"undo",key="undo-offline-bookmark")
    assert restored.status_code == 200
    assert restored.json()["report"]["web_extensions"]["bookmarks"] == saved["report"]["web_extensions"]["bookmarks"]


@pytest.mark.parametrize("payload,code", [
    ({"name":"30","view":{"page_id":"main","filters":[]}},"BOOKMARK_LIMIT"),
    ({"name":"0","view":{"page_id":"main","filters":[]}},"DUPLICATE_BOOKMARK"),
    ({"name":"Extra","view":{"page_id":"main","filters":[]},"fields":[]},"INVALID_BOOKMARK"),
])
def test_bookmark_capacity_duplicate_and_forged_signatures_rejected(client,payload,code):
    _,path,original = workspace(client,"blank")
    body = original["report"]
    body["web_extensions"] = {"bookmarks":[{"bookmark_id":str(i),"name":str(i),"view":{"page_id":"main","selected_visual_id":None,"filters":[]},"fields":[]} for i in range(30)]}
    response = command(client,path,1,"replace_report",{"report":body},"setup-bookmark-limit")
    assert response.status_code == 200, response.text
    before = response.json()
    rejected = command(client,path,2,"save_bookmark",payload,"reject-bookmark-limit")
    assert rejected.json()["error"]["code"] == code
    assert client.get(path).json() == before


def test_scenario_lifecycle_is_atomic_replayable_and_recalculates(client):
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.core import run_query
    ids, path, state = workspace(client)
    body = copy.deepcopy(state["report"])
    body["web_extensions"] = {"parameters":{"discount":.1,"multiplier":2.},
        "calculated_metrics":[{"block_id":"fab_process_move","name":"adjusted","formula":"SUM(move_count) * (1 - @discount) * @multiplier"}]}
    body["pages"]["main"]["visuals"]["kpi_moves"]["query"]["metrics"][0].update(metric_name="adjusted",alias="adjusted")
    state = command(client,path,1,"replace_report",{"report":body},"setup-scenario").json()
    saved = command(client,path,2,"save_scenario",{"name":"  Base  "},"save-scenario")
    assert saved.status_code == 200, saved.text
    state = saved.json()
    scenario = state["report"]["web_extensions"]["scenarios"][0]
    sid = scenario["scenario_id"]
    assert scenario["name"] == "Base" and scenario["parameters"] == {"discount":.1,"multiplier":2.}
    store = client.app.state.store
    old = make_snapshot(store,ids["workspace_id"],ids["report_id"],3,{"visual_ids":["kpi_moves"]})
    body = copy.deepcopy(state["report"])
    body["web_extensions"]["parameters"] = {"discount":.5,"multiplier":1.,"new_parameter":7.}
    state = command(client,path,3,"replace_report",{"report":body},"adjust-current").json()
    current = make_snapshot(store,ids["workspace_id"],ids["report_id"],4,{"visual_ids":["kpi_moves"]})
    assert run_query(store.root,current)["visuals"]["kpi_moves"]["rows"][0]["adjusted"] == 300
    applied = command(client,path,4,"apply_scenario",{"scenario_id":sid},"apply-scenario").json()
    assert applied["report"]["web_extensions"]["parameters"] == {"discount":.1,"multiplier":2.,"new_parameter":7.}
    snap = make_snapshot(store,ids["workspace_id"],ids["report_id"],5,{"visual_ids":["kpi_moves"]})
    assert run_query(store.root,snap)["visuals"]["kpi_moves"]["rows"][0]["adjusted"] == 1080
    assert run_query(store.root,old)["visuals"]["kpi_moves"]["rows"][0]["adjusted"] == 1080
    undone = command(client,path,5,"undo",key="undo-scenario").json()
    assert undone["report"]["web_extensions"]["parameters"] == body["web_extensions"]["parameters"]
    redone = command(client,path,6,"redo",key="redo-scenario").json()
    assert redone["report"]["web_extensions"] == applied["report"]["web_extensions"]
    renamed = command(client,path,7,"rename_scenario",{"scenario_id":sid,"name":"Renamed"},"rename-scenario").json()
    assert renamed["report"]["web_extensions"]["scenarios"][0]["name"] == "Renamed"
    assert command(client,path,2,"save_scenario",{"name":"  Base  "},"save-scenario").json() == saved.json()
    updated = command(client,path,8,"update_scenario",{"scenario_id":sid},"update-scenario").json()
    assert updated["report"]["web_extensions"]["scenarios"][0]["parameters"]["new_parameter"] == 7.
    deleted = command(client,path,9,"delete_scenario",{"scenario_id":sid},"delete-scenario").json()
    assert deleted["report"]["web_extensions"]["scenarios"] == []
    restored = command(client,path,10,"undo",key="restore-scenario").json()
    assert restored["report"]["web_extensions"]["scenarios"] == updated["report"]["web_extensions"]["scenarios"]


@pytest.mark.parametrize("change", ["missing", "range"])
def test_incompatible_scenario_is_preserved_rejected_and_repairable(client, change):
    _, path, original = workspace(client,"blank")
    body = original["report"]
    body["web_extensions"] = {"parameters":{"p":.1,"q":1.}}
    response = command(client,path,1,"replace_report",{"report":body},"setup-scenario")
    assert response.status_code == 200, response.text
    response = command(client,path,2,"save_scenario",{"name":"Base"},"save-scenario")
    assert response.status_code == 200, response.text
    saved = response.json()
    sid = saved["report"]["web_extensions"]["scenarios"][0]["scenario_id"]
    body = copy.deepcopy(saved["report"])
    if change == "missing":
        del body["web_extensions"]["parameters"]["p"]
    else:
        body["web_extensions"]["parameters"]["p"] = .5
        body["web_extensions"]["parameter_ranges"] = {"p":{"minimum":.2,"maximum":1.,"step":.1}}
    changed = command(client,path,3,"replace_report",{"report":body},"change-scenario").json()
    refused = command(client,path,4,"apply_scenario",{"scenario_id":sid},"apply-stale")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "SCENARIO_INCOMPATIBLE"
    assert client.get(path).json() == changed
    updated = command(client,path,4,"update_scenario",{"scenario_id":sid},"repair-scenario").json()
    assert updated["report"]["web_extensions"]["scenarios"][0]["parameters"] == body["web_extensions"]["parameters"]
    assert command(client,path,5,"apply_scenario",{"scenario_id":sid},"apply-repaired").status_code == 200


@pytest.mark.parametrize("kind,payload,code", [
    ("save_scenario",{"name":" "},"INVALID_SCENARIO"),
    ("save_scenario",{"name":"X","parameters":{"p":99}},"INVALID_SCENARIO"),
    ("save_scenario",{"name":"base"},"DUPLICATE_SCENARIO"),
    ("apply_scenario",{"scenario_id":"missing"},"SCENARIO_NOT_FOUND"),
    ("delete_scenario",{"scenario_id":[]},"SCENARIO_NOT_FOUND"),
    ("update_scenario",{},"INVALID_SCENARIO"),
])
def test_invalid_scenario_commands_leave_report_unchanged(client,kind,payload,code):
    _, path, state = workspace(client,"blank")
    state["report"]["web_extensions"] = {"parameters":{"p":1.},"scenarios":[{"scenario_id":"base","name":"Base","parameters":{"p":1.}}]}
    response = command(client,path,1,"replace_report",{"report":state["report"]},"setup-scenario")
    assert response.status_code == 200, response.text
    original = response.json()
    response = command(client,path,2,kind,payload,"invalid-scenario")
    assert response.json()["error"]["code"] == code
    assert client.get(path).json() == original


@pytest.mark.parametrize("count,code", [(0,"INVALID_SCENARIO"),(30,"SCENARIO_LIMIT")])
def test_scenario_empty_parameters_and_capacity_limits(client,count,code):
    _, path, state = workspace(client,"blank")
    body = state["report"]
    body["web_extensions"] = {"parameters":{"p":1.} if count else {},
        "scenarios":[{"scenario_id":str(i),"name":str(i),"parameters":{"p":1.}} for i in range(count)]}
    response = command(client,path,1,"replace_report",{"report":body},"setup-capacity")
    assert response.status_code == 200, response.text
    original = response.json()
    refused = command(client,path,2,"save_scenario",{"name":"Another"},"save-capacity")
    assert refused.json()["error"]["code"] == code
    assert client.get(path).json() == original


def test_read_only_report_remains_queryable_and_exportable(client):
    import pandas as pd
    from ai4bi_web_api.core import template
    body, contracts = template("fab")
    body["read_only"] = True
    store = client.app.state.store
    ids = store.create_workspace("Read only analysis", body, "readonly-analysis", "fab")
    for contract in contracts.values():
        store.publish_dataset(ids["workspace_id"], contract.model_dump(mode="json"), pd.DataFrame(contract.data_source.records))
    path = f"/api/v1/workspaces/{ids['workspace_id']}/reports/{ids['report_id']}"
    original = client.get(path).json()
    response = client.post(path + "/queries", json={"base_revision":1,"idempotency_key":"readonly-query"})
    result = wait_job(client, response.json()["job_id"])
    assert result["status"] == "succeeded"
    assert list(result["result"]["visuals"]["kpi_moves"]["rows"][0].values()) == [600]
    response = client.post(path + "/exports", json={"base_revision":1,"idempotency_key":"readonly-export","format":"json"})
    exported = wait_job(client, response.json()["job_id"])
    assert exported["status"] == "succeeded"
    download = client.get("/api/v1/artifacts/" + exported["result"]["artifact_id"])
    assert download.status_code == 200 and download.json()["report"]["read_only"] is True
    assert client.get(path).json() == original


def test_pairing_origin_csrf_and_missing_routes(tmp_path):
    with TestClient(create_app(tmp_path / "data", CODE, static_root=tmp_path / "missing-ui")) as client:
        assert client.get("/api/v1/workspaces").status_code == 401
        assert client.post("/api/v1/session", headers={"origin": "https://evil.example"}, json={"code": CODE}).status_code == 403
        assert client.post("/api/v1/session", json={"code": CODE}).status_code == 200
        assert client.post("/api/v1/session", json={"code": CODE}).status_code == 401
        assert client.post("/api/v1/workspaces", json={}).status_code == 403
        assert client.get("/api/v1/not-a-route").status_code == 404
        assert client.get("/ready").status_code == 503


def test_create_idempotency_and_scope(client):
    ids, path, original = workspace(client)
    again, _, _ = workspace(client)
    assert ids == again
    assert len(client.get("/api/v1/workspaces").json()) == 1
    assert len(client.get(f"/api/v1/workspaces/{ids['workspace_id']}/datasets").json()) == 3
    other, _, _ = workspace(client, "blank", "other-workspace")
    assert client.get(f"/api/v1/workspaces/{other['workspace_id']}/reports/{ids['report_id']}").status_code == 404
    assert original["revision"] == 1


def test_duplicate_page_is_atomic_replayable_and_queryable(client):
    _, path, original = workspace(client)
    source_id = next(iter(original["report"]["pages"]))
    source = original["report"]["pages"][source_id]
    result = command(client, path, 1, "duplicate_page", {"page_id":source_id}, "duplicate-entire-page")
    assert result.status_code == 200, result.text
    duplicated = result.json()
    assert duplicated["revision"] == 2 and duplicated["saved_revision"] == 1 and duplicated["dirty"]
    order = duplicated["report"]["web_extensions"]["page_order"]
    assert order[0] == source_id and len(order) == 2
    new_id = order[1]
    page = duplicated["report"]["pages"][new_id]
    assert page["page_id"] == new_id and page["title"].endswith("副本")
    assert duplicated["report"]["pages"][source_id] == source
    assert set(source["visuals"]).isdisjoint(page["visuals"])
    for old_id, copied_id in zip(source["visual_order"], page["visual_order"], strict=True):
        old, copied = source["visuals"][old_id], page["visuals"][copied_id]
        expected = copy.deepcopy(old)
        expected["component_id"] = expected["query"]["spec_id"] = copied_id
        assert copied == expected
    assert command(client, path, 1, "duplicate_page", {"page_id":source_id}, "duplicate-entire-page").json() == duplicated
    undone = command(client, path, 2, "undo", key="undo-duplicate-page").json()
    assert len(undone["report"]["pages"]) == 1
    redone = command(client, path, 3, "redo", key="redo-duplicate-page").json()
    assert redone["report"]["pages"][new_id] == page
    query = client.post(path + "/queries", json={"base_revision":4,"idempotency_key":"query-copied-page","visual_ids":page["visual_order"]})
    job = wait_job(client, query.json()["job_id"])
    assert job["status"] == "succeeded"
    copied_moves = page["visual_order"][source["visual_order"].index("kpi_moves")]
    assert list(job["result"]["visuals"][copied_moves]["rows"][0].values()) == [600]
    changed = copy.deepcopy(redone["report"])
    changed["pages"][new_id]["visuals"][copied_moves]["visualization"]["title"] = "Only the copy"
    edited = command(client, path, 4, "replace_report", {"report":changed}, "edit-copied-page").json()
    assert edited["report"]["pages"][source_id] == source


def test_exploration_scope_is_validated_before_job_acceptance_and_is_idempotent(client):
    ids,path,original = workspace(client)
    response = command(client,path,1,"duplicate_page",{"page_id":"main"},"copy-for-exploration")
    assert response.status_code == 200, response.text
    report = response.json()["report"]
    copied = report["web_extensions"]["page_order"][1]
    filters = exploration_view(report)["filters"]
    options = {"base_revision":2,"idempotency_key":"scope-query-request","filters":filters,"exploration_page_id":"main"}
    accepted = client.post(path+"/queries",json=options)
    assert accepted.status_code == 202, accepted.text
    assert client.post(path+"/queries",json=options).json() == accepted.json()
    assert client.post(path+"/queries",json={**options,"exploration_page_id":copied}).status_code == 409
    before = client.app.state.store.report(ids["workspace_id"],ids["report_id"])
    refused = client.post(path+"/exports",json={**options,"idempotency_key":"invalid-scope-export","format":"json","exploration_page_id":copied})
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "INVALID_EXPLORATION_PAGE"
    assert client.app.state.store.report(ids["workspace_id"],ids["report_id"]) == before
    with client.app.state.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM jobs WHERE wid=?",(ids["workspace_id"],)).fetchone()[0] == 1
    job = wait_job(client,accepted.json()["job_id"])
    assert job["status"] == "succeeded", job
    assert job["result"]["exploration_page_id"] == "main"


@pytest.mark.parametrize("payload", [{"page_id":"missing"}, {"page_id":[]}, {"page_id":"main","report":{}}])
def test_duplicate_invalid_page_leaves_report_unchanged(client, payload):
    _, path, original = workspace(client, "blank")
    response = command(client, path, 1, "duplicate_page", payload, "invalid-duplicate-page")
    assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_PAGE"
    assert client.get(path).json() == original


def test_duplicate_page_limit_does_not_partially_modify_report(client):
    from ai4bi_web_api.core import template
    body, _ = template("blank")
    source = next(iter(body["pages"].values()))
    body["pages"] = {f"page_{i}":{**copy.deepcopy(source),"page_id":f"page_{i}"} for i in range(30)}
    ids = client.app.state.store.create_workspace("Full report", body, "full-page-workspace", "blank")
    path = f"/api/v1/workspaces/{ids['workspace_id']}/reports/{ids['report_id']}"
    original = client.get(path).json()
    response = command(client, path, 1, "duplicate_page", {"page_id":"page_0"}, "over-page-limit")
    assert response.status_code == 400 and response.json()["error"]["code"] == "REPORT_LIMIT"
    assert client.get(path).json() == original


def test_durable_revision_retry_save_undo_and_redo(client):
    _, path, original = workspace(client, "blank")
    edited = copy.deepcopy(original["report"])
    edited["title"] = "良率追蹤"
    first = command(client, path, 1, "replace_report", {"report": edited}).json()
    assert first["revision"] == 2 and first["dirty"]
    replay = command(client, path, 1, "replace_report", {"report": edited})
    assert replay.status_code == 200 and replay.json() == first
    different = copy.deepcopy(edited)
    different["title"] = "Different"
    assert command(client, path, 1, "replace_report", {"report": different}).status_code == 409
    assert command(client, path, 1, "replace_report", {"report": edited}, "stale-command").status_code == 409
    saved = command(client, path, 2, "save", key="save-command").json()
    assert saved["revision"] == 2 and not saved["dirty"]
    undone = command(client, path, 2, "undo", key="undo-command").json()
    assert undone["revision"] == 3 and undone["report"]["title"] == original["report"]["title"]
    redone = command(client, path, 3, "redo", key="redo-command").json()
    assert redone["revision"] == 4 and not redone["dirty"]


def test_restart_keeps_working_draft_and_lock(tmp_path):
    root = tmp_path / "data"
    with TestClient(create_app(root, CODE)) as client:
        client.post("/api/v1/session", json={"code": CODE})
        client.headers.update({"x-ai4bi-request": "1"})
        ids, path, report = workspace(client, "blank")
        imports = f"/api/v1/workspaces/{ids['workspace_id']}/imports"
        draft = client.post(imports, files={"file": ("resume.csv", b"id,value\n001,7\n", "text/csv")}).json()
        body = report["report"]
        body["title"] = "未按保存仍可恢復"
        assert command(client, path, 1, "replace_report", {"report": body}).status_code == 200
        with pytest.raises(AppError, match="已有執行"):
            Store(root)
    with TestClient(create_app(root, CODE)) as client:
        client.post("/api/v1/session", json={"code": CODE})
        restored = client.get(path).json()
        assert restored["report"]["title"] == "未按保存仍可恢復"
        assert restored["dirty"] and restored["revision"] == 2
        listed = client.get(imports).json()
        assert [item["import_id"] for item in listed] == [draft["import_id"]]
        assert client.get(imports + "/" + draft["import_id"]).json()["status"] == "validated"


def test_governed_query_in_real_worker(client):
    ids, path, report = workspace(client)
    response = client.post(path + "/queries", json={"base_revision": 1, "idempotency_key": "first-query-1"})
    assert response.status_code == 202, response.text
    job = wait_job(client, response.json()["job_id"])
    assert job["status"] == "succeeded", job
    visuals = job["result"]["visuals"]
    assert len(visuals) == 5
    assert all(v["status"] == "ready" for v in visuals.values()), visuals
    assert list(visuals["kpi_moves"]["rows"][0].values()) == [600]
    assert 0 < list(visuals["kpi_yield"]["rows"][0].values())[0] <= 100
    assert visuals["kpi_yield"]["metadata"]["blocks_used"] == ["fab_wafer_yield"]


def test_invalid_metric_does_not_mutate_report(client):
    _, path, original = workspace(client)
    body = copy.deepcopy(original["report"])
    body["pages"]["main"]["visuals"]["kpi_moves"]["query"]["metrics"][0]["metric_name"] = "not_a_metric"
    response = command(client, path, 1, "replace_report", {"report": body})
    assert response.status_code == 400
    assert client.get(path).json() == original


def test_import_confirm_retry_and_full_column_validation(client):
    ids, _, _ = workspace(client, "blank")
    path = f"/api/v1/workspaces/{ids['workspace_id']}/imports"
    response = client.post(path, files={"file": ("measurements.csv", b"tool,good,tested\nA,90,100\nA,1,10\nB,4,5\n", "text/csv")})
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["status"] == "validated" and draft["details"]["row_count"] == 3
    assert len(client.get(path).json()) == 1
    other, _, _ = workspace(client, "blank", "draft-other-workspace")
    assert client.get(f"/api/v1/workspaces/{other['workspace_id']}/imports").json() == []
    commit_path = path + "/" + draft["import_id"] + "/commit"
    payload = {"idempotency_key": "commit-import-1", "draft_revision": draft["revision"]}
    first = client.post(commit_path, json=payload)
    assert first.status_code == 200, first.text
    assert client.post(commit_path, json=payload).json() == first.json()
    assert client.get(path).json() == []
    did = first.json()["dataset_id"]
    preview = client.get(f"/api/v1/workspaces/{ids['workspace_id']}/datasets/{did}/preview?limit=2").json()
    assert len(preview["rows"]) == 2 and preview["row_count"] == 3
    assert len(client.get(f"/api/v1/workspaces/{ids['workspace_id']}/datasets").json()) == 1
    assert client.post(path + "/" + draft["import_id"] + "/validate", json={"column_types": {"tool": "string"}}).status_code == 409


def test_bad_date_outside_preview_is_not_silently_null(client):
    ids, _, _ = workspace(client, "blank")
    path = f"/api/v1/workspaces/{ids['workspace_id']}/imports"
    csv = "date,value\n" + "2026-01-01,1\n" * 1000 + "invalid-date,2\n"
    draft = client.post(path, files={"file": ("dates.csv", csv.encode(), "text/csv")}).json()
    response = client.post(path + "/" + draft["import_id"] + "/validate", json={"column_types": {"date": "date"}}).json()
    assert response["status"] == "invalid"
    commit = client.post(path + "/" + draft["import_id"] + "/commit", json={"idempotency_key": "commit-bad-date", "draft_revision": response["revision"]})
    assert commit.status_code == 409


def test_backup_contains_consistent_dataset_manifest(client, tmp_path):
    from ai4bi_web_api.recovery import restore_backup, verify_backup
    ids, _, _ = workspace(client)
    destination = tmp_path / "backup"
    client.app.state.store.backup(destination)
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["artifacts"]) == 3
    verify_backup(destination)
    restored_path = restore_backup(destination, tmp_path / "restored")
    restored = Store(restored_path)
    try:
        assert restored.get_workspace(ids["workspace_id"])["title"] == "製程分析"
        assert all(d["status"] == "ready" for d in restored.datasets(ids["workspace_id"]))
    finally:
        restored.close()


def test_backup_restores_import_draft_and_rejects_corruption(client, tmp_path):
    from ai4bi_web_api.recovery import restore_backup, verify_backup
    ids, _, _ = workspace(client, "blank")
    path = f"/api/v1/workspaces/{ids['workspace_id']}/imports"
    draft = client.post(path, files={"file": ("draft.csv", b"part_id,value\n001,7\n", "text/csv")}).json()
    backup = tmp_path / "backup-draft"
    client.app.state.store.backup(backup)
    restored_root = restore_backup(backup, tmp_path / "restored-draft")
    from ai4bi_web_api.imports import get_import, commit_import
    restored = Store(restored_root)
    try:
        assert get_import(restored, ids["workspace_id"], draft["import_id"])["status"] == "validated"
        result = commit_import(restored, ids["workspace_id"], draft["import_id"], draft["revision"], "after-restore")
        assert result["dataset_id"] == draft["import_id"]
    finally:
        restored.close()
    with pytest.raises(AppError, match="還原必須"):
        restore_backup(backup, restored_root)
    manifest = verify_backup(backup)
    artifact = backup / manifest["artifacts"][0]["path"]
    artifact.write_bytes(b"corrupted")
    with pytest.raises(AppError) as error:
        restore_backup(backup, tmp_path / "corrupt-restore")
    assert error.value.code == "BACKUP_CORRUPT"
    assert not (tmp_path / "corrupt-restore").exists()


def test_backup_rejects_missing_reference_and_path_escape(client, tmp_path):
    from ai4bi_web_api.recovery import verify_backup
    workspace(client)
    backup = tmp_path / "backup-invalid"
    client.app.state.store.backup(backup)
    manifest_path = backup / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    original = copy.deepcopy(manifest)
    manifest["artifacts"].pop()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AppError) as error:
        verify_backup(backup)
    assert error.value.code == "BACKUP_INCOMPLETE"
    original["artifacts"][0]["path"] = "../outside.csv"
    manifest_path.write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(AppError) as error:
        verify_backup(backup)
    assert error.value.code == "BACKUP_INVALID_PATH"


def test_maintenance_cli_roundtrip_and_live_root_refusal(client, tmp_path):
    import subprocess
    import sys
    from ai4bi_web_api.core import template
    source = tmp_path / "cli-data"
    store = Store(source)
    try:
        report, _ = template("blank")
        ids = store.create_workspace("CLI workspace", report, "cli-workspace", "blank")
    finally:
        store.close()
    backup, restored = tmp_path / "cli-backup", tmp_path / "cli-restored"
    def invoke(*args):
        return subprocess.run([sys.executable, "-m", "ai4bi_web_api", *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
    assert invoke("--data-root", source, "--backup-to", backup).returncode == 0
    result = invoke("--data-root", restored, "--restore-from", backup)
    assert result.returncode == 0, result.stderr
    check = Store(restored)
    try:
        assert check.get_workspace(ids["workspace_id"])["title"] == "CLI workspace"
    finally:
        check.close()
    assert invoke("--data-root", restored, "--restore-from", backup).returncode == 1
    busy = invoke("--data-root", client.app.state.store.root, "--backup-to", tmp_path / "busy-backup")
    assert busy.returncode == 1 and "DATA_ROOT_BUSY" in busy.stderr
    assert not (tmp_path / "busy-backup").exists()


def test_interrupted_backup_never_has_completion_manifest(client, tmp_path, monkeypatch):
    import ai4bi_web_api.storage as storage
    from ai4bi_web_api.recovery import verify_backup
    ids, path, original = workspace(client)
    copy_file = storage.shutil.copyfile
    calls = 0
    def fail_copy(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated disk full")
        return copy_file(source, target)
    monkeypatch.setattr(storage.shutil, "copyfile", fail_copy)
    output = tmp_path / "interrupted-backup"
    with pytest.raises(AppError) as error:
        client.app.state.store.backup(output)
    assert error.value.code == "BACKUP_COPY_FAILED"
    assert not (output / "manifest.json").exists()
    with pytest.raises(AppError):
        verify_backup(output)
    assert client.get(path).json() == original
    assert len(client.app.state.store.datasets(ids["workspace_id"])) == 3


def test_interrupted_restore_does_not_publish_target(client, tmp_path, monkeypatch):
    import ai4bi_web_api.recovery as recovery
    _, path, original = workspace(client)
    backup = tmp_path / "before-failed-restore"
    client.app.state.store.backup(backup)
    manifest = recovery.verify_backup(backup)
    copy_file = recovery.shutil.copyfile
    calls = 0
    def fail_copy(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated write failure")
        return copy_file(source, target)
    monkeypatch.setattr(recovery.shutil, "copyfile", fail_copy)
    target = tmp_path / "failed-restore"
    with pytest.raises(AppError) as error:
        recovery.restore_backup(backup, target)
    assert error.value.code == "RESTORE_WRITE_FAILED"
    assert not target.exists()
    assert recovery.verify_backup(backup) == manifest
    assert client.get(path).json() == original


def test_assistant_drill_real_analysis_and_proposal_keep_original_query(client):
    from ai4bi_web_api.core import load_contracts
    ids,path,original = workspace(client)
    body = copy.deepcopy(original["report"])
    vid = "bar_qt_step"
    body["pages"]["main"]["visuals"][vid]["visualization"]["extra"]["drill_hierarchy"] = ["step_name","tool_id"]
    edited = command(client,path,1,"replace_report",{"report":body},"configure-ai-drill")
    assert edited.status_code == 200,edited.text
    state = {"block_id":"fab_process_move","hierarchy":["step_name","tool_id"],"field_types":["string","string"],"path":[{"column":"step_name","value":"Etch"}]}
    request = {"idempotency_key":"assistant-drill-query","base_revision":2,"prompt":"average queue time by tool","selected_component_id":vid,"drill_state":{vid:state}}
    accepted = client.post(path+"/assistant",json=request)
    assert accepted.status_code == 202,accepted.text
    job = wait_job(client,accepted.json()["job_id"])
    assert job["status"] == "succeeded",job
    result = job["result"]
    assert result["drill_context"] == {"visual_id":vid,**state}
    table = result["result_table"]
    assert {row["tool_id"] for row in table["rows"]} == {"ETCH-01","ETCH-02"}
    store = client.app.state.store
    records = load_contracts(store.root,store.datasets(ids["workspace_id"]))["fab_process_move"].data_source.records
    metric_column = next(c for c in table["columns"] if c != "tool_id")
    for row in table["rows"]:
        values = [r["queue_time_hr"] for r in records if r["step_name"] == "Etch" and r["tool_id"] == row["tool_id"]]
        assert row[metric_column] == pytest.approx(sum(values)/len(values))
    assert client.get(path).json() == edited.json()
    assert client.post(path+"/assistant",json=request).json() == accepted.json()
    different = copy.deepcopy(request)
    different["drill_state"][vid]["path"][0]["value"] = "Lithography"
    assert client.post(path+"/assistant",json=different).status_code == 409
    renamed = client.post(path+"/assistant",json={**request,"idempotency_key":"assistant-drill-rename","prompt":"rename this chart to Etch overview"})
    assert renamed.status_code == 202,renamed.text
    proposal = wait_job(client,renamed.json()["job_id"])
    assert proposal["status"] == "succeeded",proposal
    candidate = proposal["result"]["candidate_report"]
    assert candidate["pages"]["main"]["visuals"][vid]["query"] == body["pages"]["main"]["visuals"][vid]["query"]
    applied = command(client,path,2,"apply_proposal",{"job_id":renamed.json()["job_id"]},"apply-ai-drill-rename")
    assert applied.status_code == 200,applied.text
    assert applied.json()["report"]["pages"]["main"]["visuals"][vid]["query"] == body["pages"]["main"]["visuals"][vid]["query"]
    assert applied.json()["report"]["pages"]["main"]["visuals"][vid]["visualization"]["title"] == "Etch overview"


@pytest.mark.parametrize("selected", [None,"kpi_moves"])
def test_assistant_refuses_drill_from_another_visual(client,selected):
    _,path,original = workspace(client)
    state = {"block_id":"fab_process_move","hierarchy":["step_name","tool_id"],"field_types":["string","string"],"path":[]}
    response = client.post(path+"/assistant",json={"base_revision":1,"idempotency_key":"wrong-ai-drill","prompt":"average queue time by tool","selected_component_id":selected,"drill_state":{"bar_qt_step":state}})
    assert response.status_code == 400,response.text
    assert response.json()["error"]["code"] == "INVALID_ASSISTANT_CONTEXT"
    assert client.get(path).json() == original


def test_assistant_uses_real_engine_and_applies_owned_proposal(client):
    _, path, original = workspace(client)
    response = client.post(path + "/assistant", json={"idempotency_key": "assistant-title-1", "base_revision": 1,
        "prompt": "rename this chart to Yield overview", "selected_component_id": "kpi_yield"})
    assert response.status_code == 202
    jid = response.json()["job_id"]
    job = wait_job(client, jid)
    assert job["status"] == "succeeded", job
    assert job["result"]["candidate_report"], job["result"]
    updated = command(client, path, 1, "apply_proposal", {"job_id": jid}, "apply-nl-proposal")
    assert updated.status_code == 200, updated.text
    assert updated.json()["report"]["pages"]["main"]["visuals"]["kpi_yield"]["visualization"]["title"] == "Yield overview"
    assert updated.json()["report"]["pages"]["main"]["visuals"]["kpi_yield"]["query"] == original["report"]["pages"]["main"]["visuals"]["kpi_yield"]["query"]


def test_explicit_rename_is_narrow_and_requires_selection():
    from ai4bi_web_api.core import explicit_rename, template
    from ai4bi.report.models import ExecutableReportSpec, apply_report_proposal
    body, _ = template("fab")
    report = ExecutableReportSpec.from_dict(body)
    assert explicit_rename("give me an overview", report, "kpi_yield") is None
    assert explicit_rename("rename this chart to Overview", report, None).proposal is None
    response = explicit_rename("將圖表標題改為「良率 overview」", report, "kpi_yield")
    updated = apply_report_proposal(report, response.proposal)
    assert updated.pages["main"].visuals["kpi_yield"].visualization.title == "良率 overview"


def test_export_job_download_contains_query_values(client, tmp_path):
    import io
    import openpyxl
    _, path, _ = workspace(client)
    response = client.post(path + "/exports", json={"idempotency_key": "xlsx-export-1", "base_revision": 1, "format": "xlsx"})
    assert response.status_code == 202, response.text
    job = wait_job(client, response.json()["job_id"])
    assert job["status"] == "succeeded", job
    download = client.get("/api/v1/artifacts/" + job["result"]["artifact_id"])
    assert download.status_code == 200
    workbook = openpyxl.load_workbook(io.BytesIO(download.content), data_only=True)
    assert "來源與版本" in workbook.sheetnames
    values = [c for sheet in workbook for row in sheet.values for c in row]
    assert 600 in values
    from ai4bi_web_api.recovery import restore_backup
    backup = tmp_path / "export-backup"
    client.app.state.store.backup(backup)
    restored = restore_backup(backup, tmp_path / "export-restored")
    copied = restored / "workspaces" / job["workspace_id"] / "artifacts" / job["job_id"] / "export.xlsx"
    assert copied.read_bytes() == download.content


@pytest.mark.parametrize("published",[False,True])
def test_csv_export_worker_download_has_snapshot_and_filters(client,published):
    import csv,io,json,zipfile
    ids,path,_=workspace(client)
    if published:
        accepted=client.post(path+"/publications",json={"base_revision":1,"idempotency_key":"csv-publication"})
        assert accepted.status_code==202,accepted.text
        checked=wait_job(client,accepted.json()["job_id"])
        assert checked["status"]=="succeeded",checked
        path+="/publications/"+checked["result"]["publication_id"]
    payload={"idempotency_key":"csv-export-fixed","base_revision":1,"format":"csv",
             "exploration_page_id":"main","filters":[{"block_id":"fab_process_move","column_name":"step_name","operator":"eq","value":"Etch"}]}
    accepted=client.post(path+"/exports",json=payload)
    assert accepted.status_code==202,accepted.text
    assert client.post(path+"/exports",json=payload).json()==accepted.json()
    job=wait_job(client,accepted.json()["job_id"])
    assert job["status"]=="succeeded",job
    download=client.get("/api/v1/artifacts/"+job["result"]["artifact_id"])
    assert download.status_code==200 and download.headers["content-type"]=="application/zip"
    assert "report.csv.zip" in download.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        manifest=json.loads(archive.read("manifest.json"))
        assert manifest["snapshot_id"]==job["result"]["snapshot_id"]
        assert manifest["exploration_filters"]==payload["filters"] and manifest["exploration_page_id"]=="main"
        assert len(manifest["datasets"])==3 and manifest["executed_core_version"]
        table=next(t for t in manifest["tables"] if t["visual_id"]=="kpi_moves")
        values=list(csv.reader(io.StringIO(archive.read(table["file"]).decode("utf-8-sig"))))
        from decimal import Decimal
        assert len(values[1])==1 and Decimal(values[1][0])==Decimal(100)
        original=json.loads(archive.read("analysis.json"))["analysis"]["visuals"]["kpi_moves"]["rows"][0]
        assert values[1]==[str(original[name]) for name in table["columns"]]


def test_queued_cancel_never_publishes_late_result(client):
    _, path, _ = workspace(client)
    with client.app.state.jobs.guard:
        response = client.post(path + "/queries", json={"idempotency_key": "cancel-query-1", "base_revision": 1})
        jid = response.json()["job_id"]
        cancelled = client.post("/api/v1/jobs/" + jid + "/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
    time.sleep(.3)
    assert client.get("/api/v1/jobs/" + jid).json()["result"] is None


def test_foreign_import_id_cannot_create_lock_files(client, tmp_path):
    ids, _, _ = workspace(client, "blank")
    response = client.post(f"/api/v1/workspaces/{ids['workspace_id']}/imports/not-owned/commit",
                           json={"idempotency_key": "bad-import-id", "draft_revision": 1})
    assert response.status_code == 404
    assert not (client.app.state.store.root / "staging/imports/not-owned").exists()


@pytest.mark.parametrize("raw,exitcode,kind,cancel,expected", [
    (b'{"result":', 0, "query", False, "WORKER_FAILED"),
    (b'[]', 0, "query", False, "WORKER_FAILED"),
    (b'{}', 0, "query", False, "WORKER_FAILED"),
    (b'{"result":null}', 0, "query", False, "WORKER_FAILED"),
    (b'{"error":"broken"}', 0, "query", False, "WORKER_FAILED"),
    (b'{"result":{"value":NaN}}', 0, "query", False, "WORKER_FAILED"),
    (b'{"result":{"value":1e999}}', 0, "query", False, "WORKER_FAILED"),
    (b'{"result":{}}', 1, "query", False, "WORKER_FAILED"),
    (None, 0, "query", False, "WORKER_FAILED"),
    (b'{"result":{"format":"xlsx"}}', 0, "export", False, "ARTIFACT_PUBLISH_FAILED"),
    (b'{"result":{"format":"../escape"}}', 0, "export", False, "ARTIFACT_PUBLISH_FAILED"),
    (b'{"result":', 0, "query", True, None),
])
def test_broken_worker_releases_slot_and_preserves_cancellation(client, monkeypatch, raw, exitcode, kind, cancel, expected):
    """Inject worker failures at the process boundary; exercise real queue/SQLite transitions."""
    from ai4bi_web_api import jobs as jobs_module
    jobs = client.app.state.jobs
    jobs.close()  # Drive ticks explicitly so failure injection is deterministic.
    ids, _, _ = workspace(client, "blank")
    calls = []

    class FinishedProcess:
        def __init__(self, code):
            self.returncode = code

        def poll(self):
            return self.returncode

    def launch(args, **kwargs):
        jid = args[-1]
        data = raw if not calls else b'{"result":{"recovered":true}}'
        code = exitcode if not calls else 0
        calls.append(jid)
        if data is not None:
            (jobs.store.root / "staging" / "jobs" / jid / "result.json").write_bytes(data)
        return FinishedProcess(code)

    monkeypatch.setattr(jobs_module.subprocess, "Popen", launch)
    first = jobs.submit(ids["workspace_id"], kind, {}, "broken-worker-1")["job_id"]
    second = jobs.submit(ids["workspace_id"], "query", {}, "following-worker-2")["job_id"]
    jobs.tick()
    assert jobs.get(first)["status"] == "running"
    assert jobs.get(second)["status"] == "queued"
    if cancel:
        assert jobs.cancel(first)["status"] == "cancelling"
    jobs.tick()
    failed = jobs.get(first)
    assert failed["status"] == ("cancelled" if cancel else "failed")
    assert failed["result"] is None
    assert (failed["error"]["code"] if failed["error"] else None) == expected
    assert jobs.get(second)["status"] == "running"
    jobs.tick()
    assert jobs.get(second)["status"] == "succeeded"
    recovered = jobs.get(second)["result"]
    assert set(recovered) == {"recovered", "timings_ms"}
    assert recovered["recovered"] is True
    timings = recovered["timings_ms"]
    assert set(timings) == {"coordinator_queue_wall", "coordinator_accepted_to_collection_wall", "coordinator_dispatch_to_collection"}
    assert timings["coordinator_accepted_to_collection_wall"] >= timings["coordinator_queue_wall"] >= 0
    assert timings["coordinator_dispatch_to_collection"] >= 0
    assert jobs.running == {}


def test_worker_start_failure_is_terminal_and_retryable_as_new_job(client, monkeypatch):
    from ai4bi_web_api import jobs as jobs_module
    jobs = client.app.state.jobs
    jobs.close()
    ids, _, _ = workspace(client, "blank")

    def unavailable(*args, **kwargs):
        raise OSError("Cannot launch process")

    monkeypatch.setattr(jobs_module.subprocess, "Popen", unavailable)
    first = jobs.submit(ids["workspace_id"], "query", {}, "start-failure-1")["job_id"]
    jobs.tick()
    assert jobs.get(first)["status"] == "failed"
    assert jobs.get(first)["error"]["code"] == "WORKER_START_FAILED"
    assert jobs.running == {}
    # Replaying an acceptance never launches it again; a new key creates a fresh job.
    assert jobs.submit(ids["workspace_id"], "query", {}, "start-failure-1")["job_id"] == first
    second = jobs.submit(ids["workspace_id"], "query", {}, "start-failure-2")["job_id"]
    assert second != first and jobs.get(second)["status"] == "queued"


@pytest.mark.parametrize("damage", [None, "manifest_missing", "manifest_broken", "asset_changed", "asset_missing",
                                  "extra_asset", "backend_mismatch", "core_mismatch", "wrong_build"])
def test_ready_verifies_build_contents_and_identity(tmp_path, damage):
    import hashlib
    from ai4bi_web_api.static_assets import MANIFEST, write_manifest, build_id
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text('<script src="/app.js"></script>', encoding="utf-8")
    (static / "app.js").write_bytes(b'console.log("packaged");')
    manifest = write_manifest(static)
    assert manifest["files"]["app.js"] == hashlib.sha256(b'console.log("packaged");').hexdigest()
    assert "app.py" in manifest["backend_files"]
    if damage == "manifest_missing":
        (static / MANIFEST).unlink()
    elif damage == "manifest_broken":
        (static / MANIFEST).write_bytes(b'{')
    elif damage == "asset_changed":
        (static / "app.js").write_bytes(b'console.log("another build");')
    elif damage == "asset_missing":
        (static / "app.js").unlink()
    elif damage == "extra_asset":
        (static / "stale.js").write_bytes(b'old build')
    elif damage in ("backend_mismatch", "core_mismatch", "wrong_build"):
        if damage == "backend_mismatch":
            manifest["backend_files"]["app.py"] = "0" * 64
        elif damage == "core_mismatch":
            manifest["core_version"] = "incompatible-core"
        manifest["build_id"] = ("0" * 64 if damage == "wrong_build" else
                                build_id({key: value for key, value in manifest.items() if key != "build_id"}))
        (static / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    with TestClient(create_app(tmp_path / "data", CODE, static)) as client:
        assert client.get("/health").status_code == 200
        ready = client.get("/ready")
        if damage:
            assert ready.status_code == 503
            assert ready.json()["error"]["code"] == "BUILD_INTEGRITY_FAILED"
        else:
            assert ready.status_code == 200
            assert ready.json()["build_id"] == manifest["build_id"]
            assert ready.json()["app_id"] == "ai4bi-web"
            assert ready.json()["instance_id"] == client.get("/health").json()["instance_id"]
