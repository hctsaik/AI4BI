"""Real publication validation, frozen data, transactional completion and upgrade."""
import copy
import json
import sqlite3
import time

from fastapi.testclient import TestClient
import pandas as pd
import pytest

from ai4bi_web_api.app import create_app
from ai4bi_web_api.errors import AppError
from ai4bi_web_api.publications import check_publication, get_publication, publication_snapshot
from ai4bi_web_api.storage import Store, encode


@pytest.fixture
def published_app(tmp_path):
    with TestClient(create_app(tmp_path / "data", "publication-test-pairing")) as client:
        assert client.post("/api/v1/session", json={"code":"publication-test-pairing"}).status_code == 200
        client.headers.update({"x-ai4bi-request":"1"})
        ids = client.post("/api/v1/workspaces", json={"title":"Publication", "template":"fab",
                                                    "idempotency_key":"publication-workspace"}).json()
        path = f"/api/v1/workspaces/{ids['workspace_id']}/reports/{ids['report_id']}"
        yield client, client.app.state.store, ids, path


def wait(client, response):
    assert response.status_code == 202, response.text
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        job = client.get("/api/v1/jobs/" + response.json()["job_id"]).json()
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(.1)
    pytest.fail("Publication job did not finish within 45 seconds")


def publish(client, path, revision=1, key="publish-version-one"):
    response = client.post(path + "/publications", json={"base_revision":revision,"idempotency_key":key})
    job = wait(client, response)
    assert job["status"] == "succeeded", job
    return response, job["result"]["publication_id"]


def test_published_comparison_keeps_period_after_draft_disables_it(published_app):
    client, store, ids, path = published_app
    body = client.get(path).json()["report"]
    visual = body["pages"]["main"]["visuals"]["kpi_moves"]
    visual["query"]["metrics"][0]["alias"] = "moves"
    visual["visualization"]["extra"].update(compare_period="week", compare_date_column="event_date")
    changed = client.post(path + "/commands", json={"request_id": "compare", "idempotency_key": "configure-comparison",
        "base_revision": 1, "command_type": "replace_report", "payload": {"report": body}})
    assert changed.status_code == 200, changed.text
    _, pid = publish(client, path, 2, "comparison-publication")
    del visual["visualization"]["extra"]["compare_period"]
    changed = client.post(path + "/commands", json={"request_id": "disable-compare", "idempotency_key": "disable-compare",
        "base_revision": 2, "command_type": "replace_report", "payload": {"report": body}})
    assert changed.status_code == 200, changed.text
    published_path = path + "/publications/" + pid
    job = wait(client, client.post(published_path + "/queries", json={"base_revision": 2,
        "idempotency_key": "published-comparison-query", "visual_ids": ["kpi_moves"]}))
    assert job["status"] == "succeeded", job
    data = job["result"]["visuals"]["kpi_moves"]["kpi"]["comparison"]
    assert (data["current"],data["previous"],data["delta"]) == (33,77,-44)
    assert data["anchor"] == "2026-05-07"
    job = wait(client, client.post(published_path + "/exports", json={"base_revision": 2,
        "idempotency_key": "published-comparison-export", "format": "json"}))
    assert job["status"] == "succeeded", job
    artifact = client.get("/api/v1/artifacts/" + job["result"]["artifact_id"])
    assert artifact.status_code == 200, artifact.text
    exported = artifact.json()["analysis"]["visuals"]["kpi_moves"]["kpi"]["comparison"]
    assert all(exported[field] == data[field] for field in ("current", "previous", "delta", "captions"))


@pytest.mark.parametrize("endpoint,options", [("queries", {}), ("exports", {"format":"json"})])
@pytest.mark.parametrize("mismatch", ["core", "web"])
def test_changed_core_rejects_new_and_already_queued_publication_execution(published_app, monkeypatch, endpoint, options, mismatch):
    import subprocess
    import sys
    import ai4bi_web_api.publications as module
    client, store, ids, path = published_app
    _, pid = publish(client, path)
    published_path = path + "/publications/" + pid
    original = client.get(published_path).json()
    jobs = client.app.state.jobs
    jobs.close()
    request = {"base_revision":1,"idempotency_key":"accepted-before-upgrade", **options}
    accepted = client.post(published_path + "/" + endpoint, json=request)
    assert accepted.status_code == 202
    jid = accepted.json()["job_id"]
    expected_code = "PUBLICATION_CORE_INCOMPATIBLE" if mismatch == "core" else "PUBLICATION_RUNTIME_INCOMPATIBLE"
    if mismatch == "core":
        monkeypatch.setattr(module, "version", lambda _: "different-core-version")
    else:
        monkeypatch.setattr(module, "EXECUTION_CONTRACT", "future-web-query")
    unavailable = client.get(published_path).json()
    assert unavailable["runtime_compatible"] is False
    assert unavailable["report"] == original["report"] and unavailable["checks"] == original["checks"]
    assert client.get(path + "/publications").json()[0]["runtime_compatible"] is False
    rejected = client.post(published_path + "/" + endpoint, json={**request,"idempotency_key":"after-core-upgrade"})
    assert rejected.status_code == 409 and rejected.json()["error"]["code"] == expected_code
    assert client.post(published_path + "/" + endpoint, json=request).json() == accepted.json()
    with store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2
        db.execute("UPDATE jobs SET status='running' WHERE id=?", (jid,))
    folder = store.root / "staging" / "jobs" / jid
    folder.mkdir(parents=True)
    # A separate real worker simulates a changed installed-version boundary. A
    # sentinel proves rejection happens before reading data or executing queries.
    code = '''import ai4bi_web_api.publications as publications
import ai4bi_web_api.core as core
from ai4bi_web_api.worker import main
RUNTIME_CHANGE
def unexpected_load(*args):
    raise AssertionError("Mismatched publication loaded data")
core.load_contracts = unexpected_load
main()
'''
    code = code.replace("RUNTIME_CHANGE", 'publications.version = lambda _: "different-core-version"' if mismatch == "core" else
                        'publications.EXECUTION_CONTRACT = "future-web-query"')
    process = subprocess.Popen([sys.executable,"-c",code,str(store.root),jid], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    try:
        assert process.wait(timeout=45) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
    jobs.running[jid] = process, ids["workspace_id"], time.monotonic()
    jobs.tick()
    failed = jobs.get(jid)
    assert failed["status"] == "failed" and failed["error"]["code"] == expected_code
    assert not list(folder.glob("export.*"))


def test_legacy_and_unknown_web_contracts_are_visible_but_not_executable(published_app):
    from ai4bi_web_api.storage import uid
    client, store, ids, path = published_app
    _, original_pid = publish(client, path)
    original = client.get(path + "/publications/" + original_pid).json()
    assert original["runtime_compatible"] is True
    assert original["checks"]["execution_contract"] == "web-query-v7"
    with store.connect() as db:
        row = dict(db.execute("SELECT * FROM publications WHERE id=?", (original_pid,)).fetchone())
        count = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    number = 10
    for field in ("checks", "snapshot"):
        for value in (None, "web-query-v1", "web-query-v2", "web-query-v3", "web-query-v4", "web-query-v5", "web-query-v6", "future-version", 2, {}):
            legacy = dict(row)
            data = json.loads(legacy[field])
            if value is None:
                data.pop("execution_contract")
            else:
                data["execution_contract"] = value
            legacy[field] = encode(data)
            legacy["id"], legacy["published_revision"] = uid(), number
            number += 1
            with store.transaction() as db:
                # Historical publications still own a completed publication job.
                db.execute("INSERT INTO jobs SELECT ?,wid,kind,status,?,result,error,created,updated FROM jobs WHERE id=?",
                           (legacy["id"], legacy["snapshot"], original_pid))
                db.execute("INSERT INTO publications VALUES(?,?,?,?,?,?,?,?)", tuple(legacy.values()))
                count += 1
            target = path + "/publications/" + legacy["id"]
            detail = client.get(target).json()
            assert detail["runtime_compatible"] is False and detail["runtime_message"]
            assert detail["report"] == original["report"]
            listed = next(item for item in client.get(path + "/publications").json() if item["publication_id"] == legacy["id"])
            assert listed["runtime_compatible"] is False
            for endpoint, extra in (("queries", {}), ("exports", {"format": "json"})):
                rejected = client.post(target + "/" + endpoint, json={"base_revision": 1,
                    "idempotency_key": "reject-legacy-" + legacy["id"] + endpoint, **extra})
                assert rejected.status_code == 409, rejected.text
                assert rejected.json()["error"]["code"] == "PUBLICATION_RUNTIME_INCOMPATIBLE"
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == count


@pytest.mark.parametrize("kind", ["query", "assistant", "export", "publish"])
def test_unknown_draft_contract_rejected_before_data_or_artifact_access(tmp_path, monkeypatch, kind):
    from ai4bi_web_api import core, exports
    def forbidden(*args, **kwargs):
        pytest.fail("Incompatible snapshot accessed data")
    monkeypatch.setattr(core, "load_contracts", forbidden)
    calls = {"query": core.run_query, "assistant": core.run_assistant,
             "export": lambda root, snapshot: exports.export_snapshot(root, snapshot, tmp_path),
             "publish": check_publication}
    for snapshot in ({}, {"execution_contract": "web-query-v2"}, {"execution_contract": "web-query-v3"}, {"execution_contract": "future-version"}):
        with pytest.raises(AppError) as caught:
            calls[kind](tmp_path, snapshot)
        assert caught.value.code == "SNAPSHOT_RUNTIME_INCOMPATIBLE"
    assert not list(tmp_path.iterdir())


def test_publication_freezes_report_data_and_survives_backup_restore(published_app, tmp_path):
    from ai4bi_web_api.core import run_query
    from ai4bi_web_api.recovery import restore_backup, verify_backup
    client, store, ids, path = published_app
    original = client.get(path).json()
    first, pid = publish(client, path)
    published_path = path + "/publications/" + pid
    frozen = client.get(published_path).json()
    assert frozen["report"]["read_only"] and frozen["published_revision"] == 1
    assert frozen["checks"]["visual_count"] == 5 and len(frozen["data_versions"]) == 3
    assert client.get(path).json() == original  # Publishing does not save or edit working state.
    changed = copy.deepcopy(original["report"])
    changed["title"] = "Edited draft"
    edited = client.post(path + "/commands", json={"request_id":"change-draft", "idempotency_key":"change-draft",
        "base_revision":1, "command_type":"replace_report", "payload":{"report":changed}})
    assert edited.status_code == 200 and edited.json()["dirty"]
    assert edited.json()["saved_revision"] == 1
    assert client.post(path + "/publications", json={"base_revision":1,"idempotency_key":"publish-version-one"}).json() == first.json()
    assert client.get(published_path).json() == frozen
    second, second_id = publish(client, path, 2, "publish-version-two")
    assert second_id != pid
    assert [item["published_revision"] for item in client.get(path + "/publications").json()] == [2, 1]
    assert client.get(path + "/publications/" + second_id).json()["report"]["title"] == "Edited draft"
    with store.connect() as db:
        for sql in ("UPDATE publications SET source_revision=100 WHERE id=?", "DELETE FROM publications WHERE id=?"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                db.execute(sql, (pid,))
    assert client.post(published_path + "/commands", json={}).status_code in (404, 405)
    assert client.get(published_path.replace(ids["workspace_id"], "different-workspace")).status_code == 404
    wrong = client.post(published_path + "/queries", json={"base_revision":2,"idempotency_key":"wrong-publication-revision"})
    assert wrong.status_code == 409
    # Replace the current data registry with distinct one-row versions. Old files
    # remain immutable artifacts owned by the published versions, not the registry.
    previous = store.datasets(ids["workspace_id"])
    with store.transaction() as db:
        db.execute("DELETE FROM datasets WHERE wid=?", (ids["workspace_id"],))
    for item in previous:
        frame = pd.read_parquet(store.root / item["path"]).iloc[:1]
        store.publish_dataset(ids["workspace_id"], item["contract"], frame)
    response = client.post(published_path + "/queries", json={"base_revision":1,"idempotency_key":"frozen-data-query"})
    job = wait(client, response)
    assert job["status"] == "succeeded", job
    assert list(job["result"]["visuals"]["kpi_moves"]["rows"][0].values()) == [600]
    assert job["result"]["data_versions"] == frozen["data_versions"]
    exported = wait(client, client.post(published_path + "/exports", json={"base_revision":1,
        "idempotency_key":"frozen-data-export", "format":"json"}))
    assert exported["status"] == "succeeded", exported
    downloaded = client.get("/api/v1/artifacts/" + exported["result"]["artifact_id"]).json()
    assert downloaded["report"]["title"] == original["report"]["title"] and downloaded["report"]["read_only"]
    backup, restored = tmp_path / "backup", tmp_path / "restored"
    store.backup(backup)
    manifest = verify_backup(backup)
    assert {item["path"] for item in previous} <= {item["path"] for item in manifest["artifacts"]}
    restore_backup(backup, restored)
    recovered = Store(restored)
    try:
        assert get_publication(recovered, ids["workspace_id"], ids["report_id"], pid) == frozen
        with recovered.connect() as db:
            snapshot = publication_snapshot(db, ids["workspace_id"], ids["report_id"], pid, 1, {"visual_ids":["kpi_moves"],"filters":[]})
        assert list(run_query(restored, snapshot)["visuals"]["kpi_moves"]["rows"][0].values()) == [600]
    finally:
        recovered.close()


def test_published_bookmark_uses_frozen_report_and_core_guard(published_app,monkeypatch):
    client,store,ids,path = published_app
    report = client.get(path).json()["report"]
    source = next(vid for vid,v in report["pages"]["main"]["visuals"].items() if any(d["column_name"] == "step_name" for d in v["query"]["dimensions"]))
    view = {"page_id":"main","selected_visual_id":source,"filters":[{"source_visual_id":source,"block_id":"fab_process_move","column_name":"step_name","operator":"eq","value":"Etch"}]}
    saved = client.post(path+"/commands",json={"request_id":"save-bookmark","idempotency_key":"save-bookmark","base_revision":1,"command_type":"save_bookmark","payload":{"name":"Etch","view":view}})
    assert saved.status_code == 200, saved.text
    bid = saved.json()["report"]["web_extensions"]["bookmarks"][0]["bookmark_id"]
    _,pid = publish(client,path,2,"publish-bookmark")
    published_path = path+f"/publications/{pid}"
    removed = client.post(path+"/commands",json={"request_id":"delete-bookmark","idempotency_key":"delete-bookmark","base_revision":2,"command_type":"delete_bookmark","payload":{"bookmark_id":bid}})
    assert removed.status_code == 200
    assert client.get(path+f"/bookmarks/{bid}",params={"base_revision":3}).status_code == 404
    response = client.get(published_path+f"/bookmarks/{bid}",params={"base_revision":2})
    assert response.status_code == 200 and response.json()["view"] == {**view,"filter_bookmark_id":bid,"drill_state":{}}
    job = wait(client,client.post(published_path+"/queries",json={"base_revision":2,"idempotency_key":"query-bookmark","filters":response.json()["view"]["filters"]}))
    assert job["status"] == "succeeded"
    assert list(job["result"]["visuals"]["kpi_moves"]["rows"][0].values()) == [100]
    import ai4bi_web_api.publications as publications
    monkeypatch.setattr(publications,"version",lambda _:"changed-core-version")
    response = client.get(published_path+f"/bookmarks/{bid}",params={"base_revision":2})
    assert response.status_code == 409 and response.json()["error"]["code"] == "PUBLICATION_CORE_INCOMPATIBLE"


def test_published_bookmark_restores_removed_conditions_and_exports(published_app):
    from test_workspace_api import command
    client,store,ids,path = published_app
    added = command(client,path,1,"add_filter",{"filter":{"scope":"report","block_id":"fab_process_move","column_name":"step_name","operator":"eq","value":"Etch"}},"published-bookmark-filter")
    assert added.status_code == 200,added.text
    fid = added.json()["report"]["web_extensions"]["persistent_filters"][0]["filter_id"]
    saved = command(client,path,2,"save_bookmark",{"name":"Frozen filter","view":{"page_id":"main","selected_visual_id":None,"filters":[]}},"save-published-conditions")
    assert saved.status_code == 200,saved.text
    bid = saved.json()["report"]["web_extensions"]["bookmarks"][0]["bookmark_id"]
    removed = command(client,path,3,"delete_filter",{"filter_id":fid},"remove-before-publication")
    assert removed.status_code == 200,removed.text
    _,pid = publish(client,path,4,"publish-saved-conditions")
    target = path+f"/publications/{pid}"
    before = client.get(target).json()
    resolved = client.get(target+f"/bookmarks/{bid}",params={"base_revision":4})
    assert resolved.status_code == 200,resolved.text
    assert resolved.json()["view"]["filter_bookmark_id"] == bid
    result = wait(client,client.post(target+"/queries",json={"base_revision":4,"idempotency_key":"query-saved-conditions","filter_bookmark_id":bid}))
    assert result["status"] == "succeeded",result
    assert list(result["result"]["visuals"]["kpi_moves"]["rows"][0].values()) == [100]
    exported = wait(client,client.post(target+"/exports",json={"base_revision":4,"idempotency_key":"export-saved-conditions","filter_bookmark_id":bid,"format":"json"}))
    assert exported["status"] == "succeeded",exported
    artifact = client.get("/api/v1/artifacts/"+exported["result"]["artifact_id"]).json()
    assert artifact["analysis"]["filter_bookmark_id"] == bid
    assert list(artifact["analysis"]["visuals"]["kpi_moves"]["rows"][0].values()) == [100]
    assert client.get(target).json() == before
    assert before["report"]["web_extensions"]["persistent_filters"] == []
    assert client.get(path).json() == removed.json()


def test_published_drill_bookmark_uses_frozen_hierarchy(published_app):
    from test_workspace_api import command
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.core import run_query
    client,store,ids,path = published_app
    body = client.get(path).json()["report"]
    vid = "bar_qt_step"
    body["pages"]["main"]["visuals"][vid]["visualization"]["extra"]["drill_hierarchy"] = ["step_name","tool_id"]
    edited = command(client,path,1,"replace_report",{"report":body},"published-drill-config")
    assert edited.status_code == 200,edited.text
    state = run_query(store.root,make_snapshot(store,ids["workspace_id"],ids["report_id"],2,{}))["visuals"][vid]["drill"]
    state["path"] = [{"column":"step_name","value":"Etch"}]
    saved = command(client,path,2,"save_bookmark",{"name":"Etch tools","view":{"page_id":"main","filters":[],"drill_state":{vid:state}}},"save-published-drill")
    assert saved.status_code == 200,saved.text
    bid = saved.json()["report"]["web_extensions"]["bookmarks"][0]["bookmark_id"]
    _,pid = publish(client,path,3,"publish-drill-bookmark")
    target = path+f"/publications/{pid}"
    before = client.get(target).json()
    resolved = client.get(target+f"/bookmarks/{bid}",params={"base_revision":3})
    assert resolved.status_code == 200,resolved.text
    result = wait(client,client.post(target+"/queries",json={"base_revision":3,"idempotency_key":"query-published-drill","drill_state":resolved.json()["view"]["drill_state"]}))
    assert result["status"] == "succeeded",result
    assert result["result"]["visuals"][vid]["query"]["dimensions"][0]["column_name"] == "tool_id"
    assert result["result"]["visuals"][vid]["drill"]["path"] == state["path"]
    assert list(result["result"]["visuals"]["kpi_moves"]["rows"][0].values()) == [600]
    assert client.get(target).json() == before


def test_publication_freezes_persistent_filters_after_draft_removal(published_app):
    client,store,ids,path = published_app
    request = {"request_id":"add-published-filter","idempotency_key":"add-published-filter","base_revision":1,"command_type":"add_filter",
        "payload":{"filter":{"scope":"report","block_id":"fab_process_move","column_name":"step_name","operator":"eq","value":"Etch"}}}
    response = client.post(path+"/commands",json=request)
    assert response.status_code == 200,response.text
    filter_id = response.json()["report"]["web_extensions"]["persistent_filters"][0]["filter_id"]
    _,pid = publish(client,path,2,"publish-with-filter")
    removed = client.post(path+"/commands",json={"request_id":"remove-draft-filter","idempotency_key":"remove-draft-filter","base_revision":2,"command_type":"delete_filter","payload":{"filter_id":filter_id}})
    assert removed.status_code == 200
    published = wait(client,client.post(path+f"/publications/{pid}/queries",json={"base_revision":2,"idempotency_key":"query-published-filter"}))
    assert published["status"] == "succeeded"
    assert list(published["result"]["visuals"]["kpi_moves"]["rows"][0].values()) == [100]
    draft = wait(client,client.post(path+"/queries",json={"base_revision":3,"idempotency_key":"query-unfiltered-draft"}))
    assert draft["status"] == "succeeded"
    assert list(draft["result"]["visuals"]["kpi_moves"]["rows"][0].values()) == [600]


@pytest.mark.parametrize("failure", ["empty", "corrupt", "readonly"])
def test_failed_publication_never_creates_a_version(published_app, failure):
    client, store, ids, path = published_app
    if failure in ("empty", "readonly"):
        from ai4bi_web_api.core import template
        body, _ = template("blank")
        body["read_only"] = failure == "readonly"
        ids = store.create_workspace("Invalid", body, "invalid-publication", "blank")
        path = f"/api/v1/workspaces/{ids['workspace_id']}/reports/{ids['report_id']}"
    else:
        item = store.datasets(ids["workspace_id"])[0]
        (store.root / item["path"]).write_bytes(b"damaged test-owned parquet")
    response = client.post(path + "/publications", json={"base_revision":1,"idempotency_key":"invalid-publication-job"})
    if failure == "readonly":
        assert response.status_code == 403
    else:
        job = wait(client, response)
        assert job["status"] == "failed"
        assert job["error"]["code"] == ("PUBLICATION_EMPTY" if failure == "empty" else "SOURCE_CORRUPT")
    assert client.get(path + "/publications").json() == []


@pytest.mark.parametrize("outcome", ["commit", "cancel", "bad-checks"])
def test_publication_commit_is_atomic_and_cancel_wins(published_app, outcome):
    client, store, ids, path = published_app
    jobs = client.app.state.jobs
    jobs.close()
    response = client.post(path + "/publications", json={"base_revision":1,"idempotency_key":"controlled-publication"})
    assert response.status_code == 202
    jid = response.json()["job_id"]
    with store.transaction() as db:
        snapshot = json.loads(db.execute("SELECT input FROM jobs WHERE id=?", (jid,)).fetchone()[0])
        db.execute("UPDATE jobs SET status='running' WHERE id=?", (jid,))
    folder = store.root / "staging" / "jobs" / jid
    folder.mkdir(parents=True)
    result = check_publication(store.root, snapshot)
    if outcome == "bad-checks":
        result["checks"].pop("truncated_visuals")
    (folder / "result.json").write_text(encode({"result":result}), encoding="utf-8")
    class FinishedProcess:
        returncode = 0
        def poll(self): return 0
    jobs.running[jid] = FinishedProcess(), ids["workspace_id"], time.monotonic()
    if outcome == "bad-checks":
        jobs.tick()
        assert jobs.get(jid)["status"] == "failed"
        assert jobs.get(jid)["error"]["code"] == "PUBLICATION_INVALID"
        assert client.get(path + "/publications").json() == []
    elif outcome == "cancel":
        jobs.cancel(jid)
        jobs.tick()
        assert jobs.get(jid)["status"] == "cancelled"
        assert client.get(path + "/publications").json() == []
    else:
        with store.transaction() as db:
            db.execute("CREATE TRIGGER reject_job_success BEFORE UPDATE ON jobs WHEN NEW.status='succeeded' "
                       "BEGIN SELECT RAISE(ABORT, 'finish failed'); END")
        with pytest.raises(sqlite3.IntegrityError, match="finish failed"):
            jobs.tick()
        assert jobs.get(jid)["status"] == "running"
        assert client.get(path + "/publications").json() == []
        with store.transaction() as db:
            db.execute("DROP TRIGGER reject_job_success")
        jobs.tick()
        assert jobs.get(jid)["status"] == "succeeded"
        assert len(client.get(path + "/publications").json()) == 1
        jobs.tick()
        assert len(client.get(path + "/publications").json()) == 1


def test_schema_upgrade_rolls_back_ddl_and_preserves_old_data(tmp_path):
    from ai4bi_web_api.core import template
    from ai4bi_web_api.migrations import migrate
    root = tmp_path / "legacy"
    store = Store(root)
    try:
        body, _ = template("blank")
        ids = store.create_workspace("Before upgrade", body, "before-upgrade", "blank")
    finally:
        store.close()
    db = sqlite3.connect(root / "metadata.sqlite")
    try:
        db.execute("DROP TABLE publications")
        db.execute("PRAGMA user_version=1")
        db.commit()
        db.set_authorizer(lambda action, *args: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TRIGGER else sqlite3.SQLITE_OK)
        with pytest.raises(sqlite3.DatabaseError):
            migrate(db)
        db.set_authorizer(None)
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='publications'").fetchall()
        assert db.execute("SELECT title FROM workspaces WHERE id=?", (ids["workspace_id"],)).fetchone()[0] == "Before upgrade"
    finally:
        db.close()
    upgraded = Store(root)
    try:
        with upgraded.connect() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert upgraded.report(ids["workspace_id"], ids["report_id"])["revision"] == 1
    finally:
        upgraded.close()
    from ai4bi_web_api.recovery import restore_backup, verify_backup
    backups = list(tmp_path.glob("legacy.before-schema-2-*"))
    assert len(backups) == 1
    assert verify_backup(backups[0])["database_schema"] == 1
    restored = tmp_path / "restored-legacy-backup"
    restore_backup(backups[0], restored)
    recovered = Store(restored)
    try:
        assert recovered.get_workspace(ids["workspace_id"])["title"] == "Before upgrade"
        with recovered.connect() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 2
    finally:
        recovered.close()
    with sqlite3.connect(root / "metadata.sqlite") as db:
        db.execute("PRAGMA user_version=3")
    with pytest.raises(AppError) as exc:
        Store(root)
    assert exc.value.code == "SCHEMA_INCOMPATIBLE"


@pytest.mark.parametrize("cut", ["begin", "table", "update-trigger", "delete-trigger", "version", "commit"])
def test_forced_migration_process_exit_at_each_transaction_boundary(tmp_path, cut):
    import subprocess
    import sys
    from ai4bi_web_api.core import template
    root = tmp_path / "data"
    store = Store(root)
    try:
        body, _ = template("blank")
        ids = store.create_workspace("Survives crash", body, "migration-crash-workspace", "blank")
        with store.connect() as db:
            db.execute("DROP TABLE publications")
            db.execute("PRAGMA user_version=1")
    finally:
        store.close()
    marker = tmp_path / "paused.txt"
    script = tmp_path / "migration_process.py"
    script.write_text('''import sqlite3, sys, time
from pathlib import Path
from ai4bi_web_api.migrations import migrate
db = sqlite3.connect(sys.argv[1])
marker, cut = Path(sys.argv[2]), sys.argv[3]
def pause(stage):
    if stage == cut:
        marker.write_text(stage, encoding="utf-8")
        time.sleep(120)
class ObservedConnection:
    def execute(self, sql):
        result = db.execute(sql)
        for prefix, stage in [("BEGIN IMMEDIATE", "begin"), ("CREATE TABLE publications", "table"),
                              ("CREATE TRIGGER publications_no_update", "update-trigger"),
                              ("CREATE TRIGGER publications_no_delete", "delete-trigger"),
                              ("PRAGMA user_version=2", "version")]:
            if sql.strip().startswith(prefix): pause(stage)
        return result
    def commit(self):
        db.commit()
        pause("commit")
    def rollback(self): db.rollback()
migrate(ObservedConnection())
db.close()
''', encoding="utf-8")
    child = subprocess.Popen([sys.executable, str(script), str(root / "metadata.sqlite"), str(marker), cut],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            assert child.poll() is None, "Migration exited before reaching the selected boundary"
            time.sleep(.01)
        assert marker.is_file(), "Migration did not reach the selected boundary"
        child.kill()
        child.wait(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
    with sqlite3.connect(root / "metadata.sqlite") as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA user_version").fetchone()[0] == (2 if cut == "commit" else 1)
        objects = db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'publications%'").fetchall()
        assert len(objects) == (3 if cut == "commit" else 0)
    resumed = Store(root)
    try:
        assert resumed.report(ids["workspace_id"], ids["report_id"])["report"]["title"] == body["title"]
        with resumed.connect() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 2
    finally:
        resumed.close()
