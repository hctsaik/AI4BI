"""Real process lifetime probes; never inspect or terminate unrelated processes."""
import ctypes
import json
import os
import subprocess
import sys
import time

import pytest


CHILD = "from ai4bi_web_api.worker import watch_coordinator; import time; watch_coordinator(); print('ready', flush=True); time.sleep(120)"


def test_wall_latency_handles_clock_rollback_and_invalid_timestamps():
    from ai4bi_web_api.jobs import wall_elapsed_ms
    assert wall_elapsed_ms("2026-09-06T10:00:00+00:00", "2026-09-06T18:00:02.125+08:00") == 2125
    assert wall_elapsed_ms("2026-09-06T10:00:02+00:00", "2026-09-06T10:00:00+00:00") is None
    assert wall_elapsed_ms("2026-09-06T10:00:00", "2026-09-06T10:00:02") is None
    assert wall_elapsed_ms("invalid", None) is None


@pytest.fixture
def manual_jobs(tmp_path, monkeypatch):
    from ai4bi_web_api.storage import Store
    from ai4bi_web_api.jobs import Jobs
    from ai4bi_web_api.core import template
    store = Store(tmp_path / "data")
    # Capture a no-op thread target; clearing stop_event must never revive a
    # late coordinator thread while these tests drive ticks themselves.
    with monkeypatch.context() as patch:
        patch.setattr(Jobs, "loop", lambda self: None)
        jobs = Jobs(store)
    jobs.close()
    # Deterministic ticks with real processes; close still owns every child.
    jobs.stop_event.clear()
    body, _ = template("blank")
    ids = store.create_workspace("Prewarm", body, "prewarm-create", "blank")
    from ai4bi_web_api.publications import EXECUTION_CONTRACT
    payload = {"report": body, "datasets": [], "revision": 1, "snapshot_id": "prewarm", "execution_contract": EXECUTION_CONTRACT}
    try:
        yield jobs, ids["workspace_id"], payload
    finally:
        jobs.close()
        store.close()


def wait_standby(jobs):
    jobs.tick()
    assert jobs.standby is not None
    process, folder = jobs.standby
    deadline = time.monotonic() + 30
    while not (folder / "ready").exists():
        assert process.poll() is None
        assert time.monotonic() < deadline, "Standby imports did not complete"
        time.sleep(.025)
    return process, folder


def test_worker_fatal_diagnostic_is_bounded_private_and_optional(tmp_path, monkeypatch):
    from pathlib import Path
    from ai4bi_web_api import worker
    root = tmp_path / "data"
    folder = root / "staging" / "workers" / ("a"*32)
    folder.mkdir(parents=True)
    secret = "private-query-and-token-must-not-be-logged"
    monkeypatch.setattr(worker, "_phase", "result-publish")
    monkeypatch.setattr(worker, "_job_id", "b"*32)
    monkeypatch.setattr(worker, "_sequence", 3)
    try:
        raise PermissionError(13, secret, str(tmp_path / secret))
    except PermissionError as exc:
        worker.record_failure(root, folder, exc)
    raw = (folder / "fatal.json").read_text()
    assert secret not in raw and str(tmp_path) not in raw and len(raw) < 4096
    data = worker.read_failure(root, folder)
    assert data["phase"] == "result-publish" and data["errno"] == 13 and data["sequence"] == 3
    assert data["exception"] == "PermissionError" and data["job_id"] == "b"*32
    # An OS-like exception cannot inject a string through errno.
    worker.record_failure(root, folder, OSError(secret, secret))
    assert secret not in (folder / "fatal.json").read_text()
    assert worker.read_failure(root, folder)["errno"] is None
    (folder / "fatal.json").write_text(json.dumps({**data, "message": secret}))
    assert worker.read_failure(root, folder) is None
    (folder / "fatal.json").write_bytes(b" "*4097)
    assert worker.read_failure(root, folder) is None
    outside = tmp_path / ("c"*32)
    outside.mkdir()
    worker.record_failure(root, outside, ValueError(secret))
    assert not (outside / "fatal.json").exists() and worker.read_failure(root, outside) is None
    def denied(*args, **kwargs):
        raise PermissionError(13, secret)
    monkeypatch.setattr(Path, "write_bytes", denied)
    worker.record_failure(root, folder, ValueError(secret))  # Best-effort failure is swallowed.


def test_fatal_worker_diagnostic_survives_cleanup_and_next_job_runs(manual_jobs, caplog):
    jobs, wid, payload = manual_jobs
    process, folder = wait_standby(jobs)
    jid = jobs.submit(wid, "query", payload, "fatal-diagnostic")["job_id"]
    secret = "private-input-that-must-not-escape"
    with jobs.store.transaction() as db:
        db.execute("UPDATE jobs SET input=? WHERE id=?", (secret, jid))
    result = finish_manual_job(jobs, jid)
    assert result["status"] == "failed" and result["error"]["code"] == "WORKER_FAILED"
    diagnostic = result["error"]["diagnostic"]
    assert diagnostic["phase"] == "job-decode" and diagnostic["exception"] == "JSONDecodeError"
    assert diagnostic["job_id"] == jid and diagnostic["sequence"] == 1
    assert diagnostic["module"] == "worker.py" and diagnostic["line"] > 0
    assert process.poll() == 1 and not folder.exists()
    assert secret not in caplog.text and secret not in json.dumps(result)
    later = jobs.submit(wid, "query", payload, "after-fatal-diagnostic")["job_id"]
    assert finish_manual_job(jobs, later)["status"] == "succeeded"


def test_entrypoint_import_failure_records_phase_without_exception_text(tmp_path, monkeypatch):
    from ai4bi_web_api import worker
    root = tmp_path / "data"
    folder = root / "staging" / "jobs" / ("d"*32)
    folder.mkdir(parents=True)
    monkeypatch.setattr(sys, "argv", ["worker", str(root), "d"*32])
    monkeypatch.setattr(worker, "_phase", "imports")
    def broken():
        raise ImportError("private-dependent-module-configuration")
    monkeypatch.setattr(worker, "main", broken)
    assert worker.entrypoint() == 1
    result = worker.read_failure(root, folder)
    assert result["phase"] == "imports" and result["exception"] == "ImportError"
    assert "private-dependent" not in (folder / "fatal.json").read_text()


@pytest.mark.skipif(os.name != "nt", reason="Windows file sharing semantics")
@pytest.mark.parametrize("transient", [False, True])
@pytest.mark.parametrize("locked_operation", ["read", "delete"])
def test_assignment_lock_has_bounded_recovery_or_diagnostic(manual_jobs, transient, locked_operation):
    from uuid import uuid4
    from ai4bi_web_api.worker import read_failure
    jobs, wid, payload = manual_jobs
    jid = jobs.submit(wid, "query", payload, "assignment-delete-lock")["job_id"]
    output = jobs.store.root / "staging" / "jobs" / jid
    output.mkdir(parents=True)
    token = uuid4().hex
    folder = jobs.store.root / "staging" / "workers" / token
    folder.mkdir(parents=True)
    assignment = folder / "assignment"
    assignment.write_text(jid, encoding="ascii")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
                                  ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    # Real sharing modes deny either opening for read or deleting the file.
    access, sharing = (0x40000000, 6) if locked_operation == "read" else (0x80000000, 3)
    handle = kernel.CreateFileW(str(assignment), access, sharing, None, 3, 0, None)
    assert handle != ctypes.c_void_p(-1).value
    process = jobs.spawn("--standby", token)
    try:
        deadline = time.monotonic() + 30
        while not (folder / "ready").exists():
            assert process.poll() is None and time.monotonic() < deadline
            time.sleep(.025)
        if transient:
            time.sleep(.2)
            kernel.CloseHandle(handle); handle = None
            deadline = time.monotonic() + 30
            while not (output / "result.json").exists() and process.poll() is None:
                assert time.monotonic() < deadline
                time.sleep(.025)
            assert (output / "result.json").exists(), read_failure(jobs.store.root, folder)
            assert "result" in json.loads((output / "result.json").read_text(encoding="utf-8"))
            assert read_failure(jobs.store.root, folder) is None
        else:
            assert process.wait(timeout=10) == 1
            data = read_failure(jobs.store.root, folder)
            assert data["phase"] == ("assignment-read" if locked_operation == "read" else "assignment-remove")
            assert data["exception"] == "PermissionError" and data["errno"] == 13
            assert data["winerror"] == (None if locked_operation == "read" else 32)
            assert data["job_id"] == (None if locked_operation == "read" else jid)
            assert not (output / "result.json").exists()
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)
        process.stdin.close()
        jobs.clear_worker_folder(folder)


def test_handoff_cleanup_retries_without_blocking_and_stops_after_three_attempts(manual_jobs, monkeypatch, caplog):
    from pathlib import Path
    from types import SimpleNamespace
    from ai4bi_web_api import jobs as module
    jobs, _, _ = manual_jobs
    moment = [time.monotonic()]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: moment[0]))
    jobs.last_activity = moment[0] - 61
    folder = jobs.store.root / "staging" / "workers" / ("a" * 32)
    folder.mkdir(parents=True)
    assignment = folder / "assignment"
    assignment.write_text("b" * 32)
    original = Path.unlink
    calls = []

    def locked(path, *args, **kwargs):
        if path == assignment:
            calls.append(path)
            raise PermissionError(13, "Locked test handoff")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked)
    jobs.clear_worker_folder(folder)
    assert len(calls) == 1 and assignment.exists()
    jobs.tick()
    assert len(calls) == 1  # No sleep or busy retry on the coordinator path.
    for _ in range(2):
        moment[0] += 5
        jobs.tick()
    assert len(calls) == 3 and not jobs.pending_cleanup
    moment[0] += 60
    jobs.tick()
    assert len(calls) == 3 and assignment.exists()
    assert "PermissionError" in caplog.text and "errno=13" in caplog.text and "retry=False" in caplog.text


def test_handoff_cleanup_preserves_unknown_files_and_rejects_other_directories(manual_jobs, tmp_path):
    jobs, _, _ = manual_jobs
    folder = jobs.store.root / "staging" / "workers" / ("c" * 32)
    folder.mkdir(parents=True)
    (folder / "assignment").write_text("d" * 32)
    unknown = folder / "keep.txt"
    unknown.write_text("diagnostic")
    jobs.clear_worker_folder(folder)
    assert unknown.read_text() == "diagnostic" and not (folder / "assignment").exists()
    assert not jobs.pending_cleanup
    outside = tmp_path / ("e" * 32)
    outside.mkdir()
    (outside / "assignment").write_text("preserve")
    jobs.clear_worker_folder(outside)
    assert (outside / "assignment").read_text() == "preserve"


def test_handoff_retry_queue_is_bounded_and_shutdown_retries_owned_paths(manual_jobs, monkeypatch):
    from pathlib import Path
    jobs, _, _ = manual_jobs
    original = Path.unlink
    locked = [True]

    def deny(path, *args, **kwargs):
        if locked[0] and path.name == "assignment":
            raise PermissionError(13, "Test lock")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", deny)
    folders = []
    for index in range(65):
        folder = jobs.store.root / "staging" / "workers" / f"{index:032x}"
        folder.mkdir(parents=True)
        (folder / "assignment").write_text("0" * 32)
        folders.append(folder)
        jobs.clear_worker_folder(folder)
    assert len(jobs.pending_cleanup) == 64
    locked[0] = False
    jobs.close()
    assert not jobs.pending_cleanup
    assert all(not folder.exists() for folder in folders[:64])
    # Queue overflow is reported and preserved, never scanned recursively later.
    assert (folders[64] / "assignment").exists()


@pytest.mark.skipif(os.name != "nt", reason="Real Windows sharing violation")
def test_locked_handoff_is_removed_after_handle_releases(manual_jobs, monkeypatch):
    from types import SimpleNamespace
    from ai4bi_web_api import jobs as module
    jobs, _, _ = manual_jobs
    moment = [time.monotonic()]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: moment[0]))
    jobs.last_activity = moment[0] - 61
    folder = jobs.store.root / "staging" / "workers" / ("f" * 32)
    folder.mkdir(parents=True)
    assignment = folder / "assignment"
    assignment.write_text("0" * 32)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
                                  ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    handle = kernel.CreateFileW(str(assignment), 0x80000000, 3, None, 3, 0, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        jobs.clear_worker_folder(folder)
        assert assignment.exists() and folder in jobs.pending_cleanup
    finally:
        kernel.CloseHandle(handle)
    moment[0] += 5
    jobs.tick()
    assert not folder.exists() and not jobs.pending_cleanup


def test_preloaded_worker_reuses_imports_and_retires_after_eight_jobs(manual_jobs):
    jobs, wid, payload = manual_jobs
    first_process, first_folder = wait_standby(jobs)
    first = jobs.submit(wid, "query", payload, "prewarm-first")["job_id"]
    queued = [jobs.submit(wid, "query", payload, f"prewarm-{index}")["job_id"] for index in range(2, 9)]
    second = queued[0]
    jobs.tick()
    assert jobs.running[first][0] is first_process
    assert jobs.get(second)["status"] == "queued"
    assert len(jobs.running) + int(jobs.standby is not None) + int(jobs.spare is not None) <= 2
    assert jobs.standby is not None and jobs.standby_workspace is None
    deadline = time.monotonic() + 45
    while jobs.get(queued[-1])["status"] not in {"succeeded", "failed"}:
        jobs.tick()
        assert len(jobs.running) + int(jobs.standby is not None) + int(jobs.spare is not None) <= 2
        assert len({wid for _, wid, _ in jobs.running.values()}) == len(jobs.running)
        assert all(process is first_process for process, _, _ in jobs.running.values())
        assert time.monotonic() < deadline
        time.sleep(.025)
    for index, jid in enumerate([first, *queued], 1):
        result = jobs.get(jid)
        assert result["status"] == "succeeded", result
        assert result["result"]["timings_ms"]["worker_standby"] is True
        assert result["result"]["timings_ms"]["worker_sequence"] == index
        if index > 1:
            assert result["result"]["timings_ms"]["worker_imports"] == 0
        timings = result["result"]["timings_ms"]
        assert timings["coordinator_queue_wall"] >= 0
        assert timings["coordinator_dispatch_to_collection"] > 0
        assert timings["coordinator_accepted_to_collection_wall"] >= timings["coordinator_queue_wall"]
        # Queueing is measured separately even though all eight jobs reused
        # the same imported process. Re-reading a terminal job is immutable.
        assert jobs.get(jid)["result"]["timings_ms"] == timings
    assert first_process.poll() == 0
    assert not first_folder.exists() and jobs.worker_folders == {}
    spare, folder = jobs.standby
    jobs.close()
    assert spare.poll() is not None and not folder.exists()


def test_standby_expires_without_respawning_until_more_work(manual_jobs):
    jobs, wid, payload = manual_jobs
    process, folder = wait_standby(jobs)
    jobs.last_activity -= 61
    jobs.tick()
    assert process.poll() is not None and jobs.standby is None and not folder.exists()
    jobs.tick()
    assert jobs.standby is None
    jid = jobs.submit(wid, "query", payload, "after-idle")["job_id"]
    jobs.tick()
    assert jid in jobs.running and jobs.standby is not None


def finish_manual_job(jobs, jid):
    deadline = time.monotonic() + 45
    while jobs.get(jid)["status"] not in {"succeeded", "failed", "cancelled"}:
        jobs.tick()
        assert time.monotonic() < deadline
        time.sleep(.025)
    return jobs.get(jid)


def test_reused_worker_rechecks_changed_bytes_and_retires_after_error(manual_jobs):
    import copy
    import hashlib
    import pandas as pd
    from ai4bi_web_api.core import template
    jobs, wid, payload = manual_jobs
    body, contracts = template("fab")
    page = body["pages"]["main"]
    page["visuals"] = {"kpi_moves": page["visuals"]["kpi_moves"]}
    page["visual_order"] = ["kpi_moves"]
    block = contracts["fab_process_move"]
    frame = pd.DataFrame(block.data_source.records)
    jobs.store.publish_dataset(wid, block.model_dump(mode="json"), frame)
    snapshot = {**payload, "report": body, "datasets": jobs.store.datasets(wid)}
    process, folder = wait_standby(jobs)
    first = jobs.submit(wid, "query", snapshot, "reuse-data-first")["job_id"]
    result = finish_manual_job(jobs, first)
    assert result["status"] == "succeeded", result
    assert list(result["result"]["visuals"]["kpi_moves"]["rows"][0].values()) == [600]
    assert jobs.standby[0] is process
    changed = copy.deepcopy(snapshot)
    dataset = changed["datasets"][0]
    path = jobs.store.root / dataset["path"]
    frame["move_count"] *= 2
    frame.to_parquet(path, index=False)
    dataset["version"] = hashlib.sha256(path.read_bytes()).hexdigest()
    second = jobs.submit(wid, "query", changed, "reuse-data-second")["job_id"]
    result = finish_manual_job(jobs, second)
    assert result["status"] == "succeeded", result
    assert list(result["result"]["visuals"]["kpi_moves"]["rows"][0].values()) == [1200]
    assert result["result"]["timings_ms"]["worker_sequence"] == 2
    assert jobs.standby[0] is process
    path.write_bytes(path.read_bytes() + b"changed-again")
    third = jobs.submit(wid, "query", changed, "reuse-data-corrupt")["job_id"]
    result = finish_manual_job(jobs, third)
    assert result["status"] == "failed" and result["error"]["code"] == "SOURCE_CORRUPT"
    assert process.poll() is not None and not folder.exists()


def test_completed_worker_is_not_reused_for_another_workspace(manual_jobs):
    jobs, wid, payload = manual_jobs
    process, folder = wait_standby(jobs)
    first = jobs.submit(wid, "query", payload, "owner-first")["job_id"]
    assert finish_manual_job(jobs, first)["status"] == "succeeded"
    assert jobs.standby[0] is process and jobs.standby_workspace == wid
    fresh, fresh_folder = jobs.spare
    deadline = time.monotonic() + 30
    while not (fresh_folder / "ready").exists():
        assert fresh.poll() is None and time.monotonic() < deadline
        time.sleep(.025)
    other = jobs.store.create_workspace("New owner", payload["report"], "owner-other", "blank")
    second = jobs.submit(other["workspace_id"], "query", payload, "owner-second")["job_id"]
    jobs.tick()
    assert process.poll() is not None and not folder.exists()
    assert jobs.running[second][0] is fresh
    result = finish_manual_job(jobs, second)
    assert result["status"] == "succeeded" and result["result"]["timings_ms"]["worker_sequence"] == 1


def test_reusable_and_fresh_idle_workers_expire_together(manual_jobs):
    jobs, wid, payload = manual_jobs
    process, folder = wait_standby(jobs)
    jid = jobs.submit(wid, "query", payload, "two-idle-expire")["job_id"]
    assert finish_manual_job(jobs, jid)["status"] == "succeeded"
    assert jobs.spare is not None, {
        "completed_process_exit": process.poll(),
        "standby_is_completed_process": jobs.standby is not None and jobs.standby[0] is process,
        "standby_exit": jobs.standby[0].poll() if jobs.standby else None,
        "standby_workspace": jobs.standby_workspace,
        "idle_age": time.monotonic() - jobs.last_activity,
        "prewarm_backoff": jobs.next_prewarm - time.monotonic(),
        "running_count": len(jobs.running),
    }
    fresh, fresh_folder = jobs.spare
    assert jobs.standby[0] is process and fresh is not process
    jobs.last_activity -= 61
    jobs.tick()
    assert process.poll() is not None and fresh.poll() is not None
    assert not folder.exists() and not fresh_folder.exists()
    assert jobs.standby is None and jobs.spare is None
    jobs.tick()
    assert jobs.standby is None and jobs.spare is None


@pytest.mark.parametrize("collect", [False, True])
def test_active_job_does_not_consume_idle_lifetime(manual_jobs, collect):
    jobs, wid, payload = manual_jobs
    process, folder = wait_standby(jobs)
    jid = jobs.submit(wid, "query", payload, "active-not-idle")["job_id"]
    jobs.tick()
    fresh, fresh_folder = jobs.standby
    if collect:
        deadline = time.monotonic() + 30
        marker = folder / "ready"
        while not marker.exists() or marker.read_text(encoding="ascii") != jid:
            assert process.poll() is None and time.monotonic() < deadline
            time.sleep(.025)
    # Advancing the age avoids a 60-second sleep, while both children are real.
    jobs.last_activity -= 61
    if collect:
        jobs.tick()
        assert jobs.get(jid)["status"] == "succeeded"
        assert jobs.standby[0] is process
        assert jobs.spare[0] is fresh
    else:
        jobs.prewarm()
        assert jobs.running[jid][0] is process
        assert jobs.standby[0] is fresh
    assert process.poll() is None and fresh.poll() is None
    assert folder.exists() and fresh_folder.exists()


def test_failed_fresh_spare_keeps_owned_worker_and_backs_off(manual_jobs):
    jobs, wid, payload = manual_jobs
    process, _ = wait_standby(jobs)
    jid = jobs.submit(wid, "query", payload, "spare-backoff")["job_id"]
    assert finish_manual_job(jobs, jid)["status"] == "succeeded"
    fresh, folder = jobs.spare
    fresh.stdin.close()
    assert fresh.wait(timeout=30) == 70
    jobs.tick()
    assert jobs.standby[0] is process and jobs.spare is None and not folder.exists()
    assert jobs.next_prewarm > time.monotonic()
    jobs.tick()
    assert jobs.spare is None


def test_failed_reuse_handshake_preserves_completed_result(manual_jobs, monkeypatch):
    jobs, wid, payload = manual_jobs
    code = "\n".join([
        "from pathlib import Path",
        "from ai4bi_web_api.worker import main",
        "original = Path.replace",
        "def fail_ready(path, target):",
        "    if path.name == 'ready.tmp': raise PermissionError(13, 'Test handshake lock')",
        "    return original(path, target)",
        "Path.replace = fail_ready",
        "main()",
    ])
    def spawn(*arguments):
        env = os.environ.copy()
        env["AI4BI_WORKER_PARENT_PIPE"] = "1"
        return subprocess.Popen([sys.executable, "-c", code, str(jobs.store.root), *arguments], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    monkeypatch.setattr(jobs, "spawn", spawn)
    process, folder = wait_standby(jobs)
    jid = jobs.submit(wid, "query", payload, "handshake-lock")["job_id"]
    result = finish_manual_job(jobs, jid)
    assert result["status"] == "succeeded", result
    assert process.poll() == 0 and not folder.exists()


@pytest.mark.parametrize("cancel", [False, True])
def test_reusable_completion_marker_is_job_specific_and_cancel_wins(manual_jobs, cancel):
    jobs, wid, payload = manual_jobs
    process, folder = wait_standby(jobs)
    jid = jobs.submit(wid, "query", payload, "ready-race")["job_id"]
    jobs.tick()
    marker = folder / "ready"
    deadline = time.monotonic() + 30
    while not marker.exists() or marker.read_text(encoding="ascii") != jid:
        assert process.poll() is None
        assert time.monotonic() < deadline
        time.sleep(.025)
    assert jobs.get(jid)["status"] == "running"
    assert (jobs.store.root / "staging" / "jobs" / jid / "result.json").is_file()
    marker.write_text("0" * 32, encoding="ascii")
    jobs.tick()
    assert jobs.get(jid)["status"] == "running"
    marker.write_text(jid, encoding="ascii")
    if cancel:
        jobs.cancel(jid)
    jobs.tick()
    result = jobs.get(jid)
    assert result["status"] == ("cancelled" if cancel else "succeeded")
    if cancel:
        assert result["result"] is None and process.poll() is not None and not folder.exists()
    else:
        assert process.poll() is None and jobs.standby[0] is process


@pytest.mark.skipif(os.name != "nt", reason="Windows process counters")
@pytest.mark.parametrize("working,commit,available,allowed", [
    (767, 767, True, True), (768, 500, True, False), (500, 768, True, False),
    (500, 500, False, False)])
def test_worker_reuse_memory_guard_rejects_peak_or_unknown_usage(monkeypatch, working, commit, available, allowed):
    from types import SimpleNamespace
    from ai4bi_web_api.worker import within_reuse_memory_limit
    def current():
        return 1
    def memory(handle, pointer, size):
        pointer._obj.peak_working = working * 1024 * 1024
        pointer._obj.peak_pagefile = commit * 1024 * 1024
        return available
    monkeypatch.setattr(ctypes, "WinDLL", lambda name: SimpleNamespace(GetCurrentProcess=current, GetProcessMemoryInfo=memory))
    assert within_reuse_memory_limit() is allowed


@pytest.mark.parametrize("locked", [False, pytest.param(True, marks=pytest.mark.skipif(os.name != "nt", reason="Windows directory sharing lock"))])
def test_cancelled_preloaded_job_releases_its_process_and_handoff(manual_jobs, monkeypatch, locked):
    from types import SimpleNamespace
    from ai4bi_web_api import jobs as module
    jobs, wid, payload = manual_jobs
    process, folder = wait_standby(jobs)
    handle = None
    if locked:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
                                      ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_int
        # Deny deleting this directory while allowing the worker's file I/O.
        handle = kernel.CreateFileW(str(folder), 0x80000000, 3, None, 3, 0x02000000, None)
        assert handle != ctypes.c_void_p(-1).value
    offset = [0]
    monotonic = time.monotonic
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: monotonic() + offset[0]))
    try:
        jid = jobs.submit(wid, "query", payload, "cancel-preloaded")["job_id"]
        jobs.tick()
        jobs.cancel(jid)
        jobs.tick()
        assert jobs.get(jid)["status"] == "cancelled"
        assert jobs.get(jid)["result"] is None
        assert process.poll() is not None and jid not in jobs.running
        if locked:
            assert folder.exists() and jobs.pending_cleanup[folder][0] == 1
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)
    # Sharing violations follow the existing two retries at five-second intervals.
    # Advance the scheduler clock, not the worker/import/query time limits.
    for _ in range(2):
        if not folder.exists():
            break
        assert folder in jobs.pending_cleanup
        offset[0] += 5
        jobs.tick()
        assert jobs.get(jid)["status"] == "cancelled" and jobs.get(jid)["result"] is None
    assert not folder.exists() and folder not in jobs.pending_cleanup


def test_idle_worker_parent_pipe_exit_and_restart_backoff(manual_jobs):
    jobs, _, _ = manual_jobs
    process, folder = wait_standby(jobs)
    process.stdin.close()
    assert process.wait(timeout=10) == 70
    jobs.tick()
    assert jobs.standby is None and not folder.exists()
    assert jobs.next_prewarm > time.monotonic()
    jobs.tick()
    assert jobs.standby is None


def test_two_workspaces_use_two_workers_without_a_third_standby(manual_jobs):
    jobs, wid, payload = manual_jobs
    wait_standby(jobs)
    other = jobs.store.create_workspace("Other", payload["report"], "other-prewarm", "blank")
    first = jobs.submit(wid, "query", payload, "first-workspace")["job_id"]
    second = jobs.submit(other["workspace_id"], "query", payload, "second-workspace")["job_id"]
    jobs.tick()
    assert set(jobs.running) == {first, second}
    assert jobs.standby is None
    assert jobs.running[first][0] is not jobs.running[second][0]


def test_prewarm_start_failure_keeps_cold_dispatch_available(manual_jobs, monkeypatch):
    jobs, wid, payload = manual_jobs
    original = jobs.spawn
    attempts = []

    def spawn(*arguments):
        attempts.append(arguments)
        if arguments[0] == "--standby":
            raise OSError("Prewarm unavailable")
        return original(*arguments)

    monkeypatch.setattr(jobs, "spawn", spawn)
    jobs.tick()
    assert jobs.standby is None and len(attempts) == 1
    jobs.tick()
    assert len(attempts) == 1
    jid = jobs.submit(wid, "query", payload, "cold-fallback")["job_id"]
    jobs.tick()
    assert jid in jobs.running and jobs.get(jid)["status"] == "running"
    assert attempts[-1] == (jid,)
    assert list((jobs.store.root / "staging" / "workers").iterdir()) == []


@pytest.mark.parametrize("load_core", [False, True])
def test_finished_worker_exits_normally_while_parent_pipe_is_open(load_core):
    code = "from ai4bi_web_api.worker import watch_coordinator; import time; watch_coordinator(); time.sleep(.1)"
    if load_core:
        code += "; import ai4bi_web_api.core"
    child = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        assert child.wait(timeout=30 if load_core else 10) == 0
    finally:
        child.stdin.close()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


def test_worker_exits_when_its_coordinator_pipe_closes():
    process = subprocess.Popen([sys.executable, "-c", CHILD], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        assert process.poll() is None
        process.stdin.close()
        assert process.wait(timeout=10) == 70
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def test_each_worker_has_an_independent_lifetime_pipe():
    children = [subprocess.Popen([sys.executable, "-c", CHILD], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) for _ in range(2)]
    try:
        children[0].stdin.close()
        assert children[0].wait(timeout=10) == 70
        assert children[1].poll() is None
        children[1].stdin.close()
        assert children[1].wait(timeout=10) == 70
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
            if not child.stdin.closed:
                child.stdin.close()


@pytest.mark.skipif(os.name != "nt", reason="Uses Windows process handles to avoid PID reuse")
@pytest.mark.parametrize("actual_jobs", [False, True])
def test_forced_parent_exit_closes_pipe_and_stops_live_worker(tmp_path, actual_jobs):
    marker = tmp_path / "worker.json"
    parent_script = tmp_path / "coordinator.py"
    parent_script.write_text(
        "import json, subprocess, sys, time\nfrom pathlib import Path\n"
        f"child = subprocess.Popen([sys.executable, '-c', {CHILD!r}], stdin=subprocess.PIPE, stdout=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)\n"
        "assert child.stdout.readline().strip() == b'ready'\n"
        "marker = Path(sys.argv[1]); temp = marker.with_suffix('.tmp')\n"
        "temp.write_text(json.dumps({'pid': child.pid}), encoding='utf-8'); temp.replace(marker)\n"
        "time.sleep(120)\n", encoding="utf-8")
    if actual_jobs:
        parent_script.write_text(
            "import json, sys, time\nfrom pathlib import Path\n"
            "from ai4bi_web_api.storage import Store\nfrom ai4bi_web_api.jobs import Jobs\nfrom ai4bi_web_api.core import template\n"
            "from ai4bi_web_api.publications import EXECUTION_CONTRACT\n"
            "store = Store(Path(sys.argv[2])); body, _ = template('blank')\n"
            "ids = store.create_workspace('Lifetime', body, 'lifetime-create', 'blank')\n"
            "jobs = Jobs(store)\n"
            "job = jobs.submit(ids['workspace_id'], 'query', {'report':body,'datasets':[],'revision':1,'snapshot_id':'lifetime','execution_contract':EXECUTION_CONTRACT}, 'lifetime-query')\n"
            "while True:\n"
            "    with jobs.guard:\n"
            "        if job['job_id'] in jobs.running:\n"
            "            child = jobs.running[job['job_id']][0]\n"
            "            marker = Path(sys.argv[1]); temp = marker.with_suffix('.tmp')\n"
            "            temp.write_text(json.dumps({'pid':child.pid,'job_id':job['job_id']}),encoding='utf-8'); temp.replace(marker)\n"
            "            time.sleep(120)\n"
            "    time.sleep(.01)\n", encoding="utf-8")
    root = tmp_path / "data"
    parent = subprocess.Popen([sys.executable, str(parent_script), str(marker), str(root)], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.WaitForSingleObject.restype = ctypes.c_ulong
    kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = None
    try:
        deadline = time.monotonic() + 30
        while not marker.exists() and time.monotonic() < deadline:
            assert parent.poll() is None, "Coordinator exited before its worker was ready"
            time.sleep(.05)
        assert marker.is_file(), "Worker did not become ready"
        worker_pid = json.loads(marker.read_text(encoding="utf-8"))["pid"]
        handle = kernel.OpenProcess(0x00100000 | 0x0001 | 0x1000, False, worker_pid)
        assert handle, ctypes.get_last_error()
        assert kernel.WaitForSingleObject(handle, 0) == 258  # Worker is alive.
        parent.kill()
        parent.wait(timeout=10)
        assert kernel.WaitForSingleObject(handle, 10000) == 0, "Worker survived coordinator termination"
        exitcode = ctypes.c_ulong()
        assert kernel.GetExitCodeProcess(handle, ctypes.byref(exitcode))
        assert exitcode.value == 70
        if actual_jobs:
            from ai4bi_web_api.storage import Store
            recovered = Store(root)
            try:
                with recovered.connect() as db:
                    row = db.execute("SELECT status,error,result FROM jobs WHERE id=?", (json.loads(marker.read_text())["job_id"],)).fetchone()
                assert row["status"] == "failed" and row["result"] is None
                assert json.loads(row["error"])["code"] == "JOB_INTERRUPTED"
            finally:
                recovered.close()
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=10)
        if handle:
            if kernel.WaitForSingleObject(handle, 0) != 0:
                kernel.TerminateProcess(handle, 1)
                kernel.WaitForSingleObject(handle, 10000)
            kernel.CloseHandle(handle)
