"""Job acceptance transactions, lost responses and persisted request identity."""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from ai4bi_web_api.app import create_app
from ai4bi_web_api.errors import AppError
from ai4bi_web_api.jobs import Jobs, make_snapshot
from ai4bi_web_api.storage import Store, digest


@pytest.fixture
def accepted_app(tmp_path):
    app = create_app(tmp_path / "data", "job-acceptance-pairing")
    with TestClient(app) as client:
        assert client.post("/api/v1/session", json={"code":"job-acceptance-pairing"}).status_code == 200
        client.headers.update({"x-ai4bi-request":"1"})
        # Acceptance is tested independently of workers; real workers run in the
        # workspace API tests. No subprocess should race these transaction probes.
        app.state.jobs.close()
        ids = client.post("/api/v1/workspaces", json={"title":"Acceptance", "template":"blank",
                                                    "idempotency_key":"create-acceptance"}).json()
        path = f"/api/v1/workspaces/{ids['workspace_id']}/reports/{ids['report_id']}"
        yield client, app.state.store, app.state.jobs, ids, path


def advance_report(store, ids):
    return store.command(ids["workspace_id"], ids["report_id"], {
        "base_revision":1, "command_type":"replace_report", "idempotency_key":"advance-report"},
        lambda report: {**report, "title":"Changed after acceptance"})


@pytest.mark.parametrize("endpoint,options,changed", [
    ("queries", {}, {"visual_ids":["another-chart"]}),
    ("exports", {"format":"json"}, {"format":"xlsx"}),
    ("assistant", {"prompt":"Summarize this report"}, {"prompt":"Rename the report"}),
])
def test_lost_response_retry_keeps_job_after_report_and_dataset_changes(accepted_app, endpoint, options, changed):
    client, store, jobs, ids, path = accepted_app
    request = {"base_revision":1, "idempotency_key":"lost-acceptance-response", **options}
    first = client.post(path + "/" + endpoint, json=request)
    assert first.status_code == 202, first.text
    jid = first.json()["job_id"]
    with store.connect() as db:
        original = db.execute("SELECT input FROM jobs WHERE id=?", (jid,)).fetchone()[0]
    snapshot = json.loads(original)
    from ai4bi_web_api.publications import EXECUTION_CONTRACT
    assert snapshot["execution_contract"] == EXECUTION_CONTRACT
    assert snapshot["revision"] == 1 and snapshot["as_of"]
    assert snapshot["snapshot_id"] == digest({k:v for k,v in snapshot.items() if k != "snapshot_id"})
    advance_report(store, ids)
    # Represent a subsequently registered dataset without involving import workers.
    with store.transaction() as db:
        db.execute("INSERT INTO datasets VALUES(?,?,?,?,?,?,?)",
                   ("later-data", ids["workspace_id"], "{}", "later.parquet", "later-version", "damaged", "later"))
    jobs.cancel(jid)
    replay = client.post(path + "/" + endpoint, json=request)
    assert replay.status_code == 202 and replay.json() == first.json()
    assert jobs.get(jid)["status"] == "cancelled"
    conflict = client.post(path + "/" + endpoint, json={**request, **changed})
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    stale = client.post(path + "/" + endpoint, json={**request, "idempotency_key":"new-but-stale-request"})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "REVISION_CONFLICT"
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert db.execute("SELECT input FROM jobs WHERE id=?", (jid,)).fetchone()[0] == original


def test_snapshot_capture_and_acceptance_hold_the_same_write_transaction(accepted_app, monkeypatch):
    client, store, jobs, ids, path = accepted_app
    import ai4bi_web_api.jobs as module
    capture = module.make_snapshot
    observed = []

    def snapshot(*args, **kwargs):
        result = capture(*args, **kwargs)
        # A competing report/data writer cannot enter between snapshot capture and
        # queue insertion. Use an actual second SQLite connection, no timing sleep.
        competitor = sqlite3.connect(store.db_path, timeout=0)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                competitor.execute("BEGIN IMMEDIATE")
        finally:
            competitor.close()
        observed.append(result["snapshot_id"])
        return result

    monkeypatch.setattr(module, "make_snapshot", snapshot)
    response = client.post(path + "/queries", json={"base_revision":1,"idempotency_key":"atomic-query-snapshot"})
    assert response.status_code == 202
    with store.connect() as db:
        raw = db.execute("SELECT input FROM jobs WHERE id=?", (response.json()["job_id"],)).fetchone()[0]
        assert observed == [json.loads(raw)["snapshot_id"]]


def test_failure_after_queue_insert_rolls_back_job_and_retry_record(accepted_app):
    client, store, jobs, ids, path = accepted_app
    with store.transaction() as db:
        db.execute("CREATE TRIGGER fail_acceptance BEFORE INSERT ON dedup WHEN NEW.scope LIKE 'job:%' "
                   "BEGIN SELECT RAISE(ABORT, 'acceptance write failed'); END")
    request = {"base_revision":1,"idempotency_key":"rollback-acceptance"}
    with pytest.raises(sqlite3.IntegrityError, match="acceptance write failed"):
        client.post(path + "/queries", json=request)
    with store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM dedup WHERE scope LIKE 'job:%'").fetchone()[0] == 0
        db.execute("DROP TRIGGER fail_acceptance")
    response = client.post(path + "/queries", json=request)
    assert response.status_code == 202
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_concurrent_retries_and_full_queue_do_not_duplicate_jobs(accepted_app):
    client, store, jobs, ids, path = accepted_app
    def submit(key):
        return jobs.submit_report(ids["workspace_id"], ids["report_id"], "query", 1,
                                  {"visual_ids":[], "filters":[]}, key)
    with ThreadPoolExecutor(max_workers=8) as pool:
        replies = list(pool.map(submit, ["concurrent-retry"] * 16))
    assert all(reply == replies[0] for reply in replies)
    for index in range(20):
        submit(f"queue-request-{index}")
    assert submit("concurrent-retry") == replies[0]
    with pytest.raises(AppError) as exc:
        submit("queue-overflow")
    assert exc.value.code == "QUEUE_LIMIT"
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 21


@pytest.mark.parametrize("legacy", [False, True])
def test_retry_after_restart_preserves_original_identity_and_terminal_state(tmp_path, legacy):
    from ai4bi_web_api.core import template
    store = Store(tmp_path / "data")
    jobs = Jobs(store)
    jobs.close()
    body, _ = template("blank")
    ids = store.create_workspace("Restart", body, "restart-workspace", "blank")
    wid, rid, key = ids["workspace_id"], ids["report_id"], "restart-accepted-job"
    options = {"visual_ids":[], "filters":[], "format":"json"}
    if legacy:
        snapshot = make_snapshot(store, wid, rid, 1, options)
        snapshot.pop("as_of")
        snapshot.pop("snapshot_id")
        snapshot["snapshot_id"] = digest(snapshot)
        first = jobs.submit(wid, "export", snapshot, key)
    else:
        first = jobs.submit_report(wid, rid, "export", 1, options, key)
    advance_report(store, ids)
    with store.transaction() as db:
        db.execute("UPDATE jobs SET status='running' WHERE id=?", (first["job_id"],))
    store.close()
    reopened = Store(store.root)
    resumed = Jobs(reopened)
    resumed.close()
    try:
        assert resumed.submit_report(wid, rid, "export", 1, options, key) == first
        job = resumed.get(first["job_id"])
        assert job["status"] == "failed" and job["error"]["code"] == "JOB_INTERRUPTED"
        for changed in ({**options,"format":"xlsx"}, {**options,"filters":[{"field":"x"}]}):
            with pytest.raises(AppError) as exc:
                resumed.submit_report(wid, rid, "export", 1, changed, key)
            assert exc.value.code == "IDEMPOTENCY_CONFLICT"
        with reopened.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    finally:
        resumed.close()
        reopened.close()
