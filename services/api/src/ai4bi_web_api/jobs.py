"""Bounded process jobs; only coordinator publishes terminal results."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from .errors import AppError
from .storage import Store, now, uid, encode, digest


def wall_elapsed_ms(start: str, end: str):
    """Diagnostic only: wall clock changes must not fail a completed job."""
    try:
        first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
        if first.tzinfo is None or last.tzinfo is None:
            return None
        elapsed = (last-first).total_seconds()*1000
        return round(elapsed, 2) if elapsed >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def finished_payload(path: Path, returncode: int) -> dict:
    """A broken worker result must release its slot, never poison every tick."""
    failure = {"error": {"code": "WORKER_FAILED", "message": "分析工作未完成，請重新執行。"}}
    if returncode != 0:
        return failure
    try:
        with path.open("rb") as stream:
            raw = stream.read(20_000_001)
        if len(raw) > 20_000_000:
            return failure
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) not in ({"result"}, {"error"}):
            return failure
        if "result" in payload and not isinstance(payload["result"], dict):
            return failure
        if "error" in payload:
            error = payload["error"]
            if not isinstance(error, dict) or not all(isinstance(error.get(k), str) for k in ("code", "message")):
                return failure
        # SQLite/API encoding must also be possible (reject NaN, overflow and lone surrogates).
        encode(payload).encode("utf-8")
        return payload
    except (OSError, ValueError, UnicodeError, RecursionError):
        return failure


class Jobs:
    def __init__(self, store: Store):
        self.store = store
        self.running: dict[str, tuple[subprocess.Popen, str, float]] = {}
        self.standby: tuple[subprocess.Popen, Path] | None = None
        self.standby_workspace: str | None = None
        self.spare: tuple[subprocess.Popen, Path] | None = None
        self.worker_folders: dict[str, Path] = {}
        self.pending_cleanup: dict[Path, tuple[int, float]] = {}
        self.last_activity = time.monotonic()
        self.next_prewarm = 0.0
        self.stop_event = threading.Event()
        self.guard = threading.Lock()
        self.thread = threading.Thread(target=self.loop, name="ai4bi-job-coordinator", daemon=True)
        self.thread.start()

    def submit(self, wid: str, kind: str, payload: dict, key: str) -> dict:
        self.store.get_workspace(wid)
        with self.store.transaction() as db:
            return self.store.idempotent(db, f"job:{wid}:{kind}", key, payload,
                                         lambda: self.enqueue(db, wid, kind, payload))

    def enqueue(self, db, wid: str, kind: str, payload: dict) -> dict:
        count = db.execute("SELECT COUNT(*) FROM jobs WHERE wid=? AND status IN ('queued','running','cancelling')", (wid,)).fetchone()[0]
        if count >= 21:
            raise AppError("QUEUE_LIMIT", "工作區等待任務過多，請稍後再試。", 429)
        jid, stamp = uid(), now()
        db.execute("INSERT INTO jobs VALUES(?,?,?,'queued',?,NULL,NULL,?,?)", (jid, wid, kind, encode(payload), stamp, stamp))
        return {"job_id": jid, "workspace_id": wid, "status": "queued"}

    def submit_report(self, wid: str, rid: str, kind: str, revision: int, extra: dict, key: str) -> dict:
        """Deduplicate the request before capturing current state, in one transaction."""
        request = {"report_id": rid, "base_revision": revision, "options": extra}
        scope = f"job:{wid}:{kind}"
        with self.store.transaction() as db:
            # Previous builds hashed the captured snapshot rather than the request.
            # Recognize only that exact legacy digest plus the original request;
            # never create a second job for an already accepted key after upgrading.
            previous = db.execute("SELECT hash,response FROM dedup WHERE scope=? AND key=?", (scope, key)).fetchone()
            if previous and previous["hash"] != digest(request):
                accepted = json.loads(previous["response"])
                row = db.execute("SELECT input FROM jobs WHERE id=? AND wid=? AND kind=?",
                                 (accepted["job_id"], wid, kind)).fetchone()
                if row:
                    original = json.loads(row["input"])
                    if (previous["hash"] == digest(original)
                            and original.get("report", {}).get("audit", {}).get("report_id") == rid
                            and original.get("revision") == revision
                            and all(name in original for name in extra)
                            and digest({name: original[name] for name in extra}) == digest(extra)):
                        return accepted

            def accept():
                snapshot = make_snapshot(self.store, wid, rid, revision, extra, db=db)
                if kind == "publish":
                    if snapshot["report"].get("read_only"):
                        raise AppError("READ_ONLY", "唯讀報表不能重新發布。", 403)
                    snapshot["report"]["read_only"] = True
                    snapshot.pop("snapshot_id")
                    snapshot["snapshot_id"] = digest(snapshot)
                return self.enqueue(db, wid, kind, snapshot)
            return self.store.idempotent(db, scope, key, request, accept)

    def submit_publication(self, wid, rid, pid, kind, revision, extra, key):
        from .publications import publication_snapshot
        request = {"source_revision":revision, "options":extra}
        with self.store.transaction() as db:
            def accept():
                snapshot = publication_snapshot(db, wid, rid, pid, revision, extra)
                return self.enqueue(db, wid, kind, snapshot)
            return self.store.idempotent(db, f"published-job:{wid}:{rid}:{pid}:{kind}", key, request, accept)

    def get(self, jid: str) -> dict:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        if not row:
            raise AppError("NOT_FOUND", "找不到任務。", 404)
        return {"job_id": row["id"], "workspace_id": row["wid"], "kind": row["kind"],
                "status": row["status"], "created_at": row["created"], "updated_at": row["updated"],
                "result": json.loads(row["result"]) if row["result"] else None,
                "error": json.loads(row["error"]) if row["error"] else None}

    def cancel(self, jid: str):
        with self.store.transaction() as db:
            row = db.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()
            if not row:
                raise AppError("NOT_FOUND", "找不到任務。", 404)
            if row["status"] == "queued":
                db.execute("UPDATE jobs SET status='cancelled',updated=? WHERE id=?", (now(), jid))
            elif row["status"] == "running":
                db.execute("UPDATE jobs SET status='cancelling',updated=? WHERE id=?", (now(), jid))
        return self.get(jid)

    def spawn(self, *arguments):
        env = os.environ.copy()
        env.update(PYTHONIOENCODING="utf-8", OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", AI4BI_WORKER_PARENT_PIPE="1")
        return subprocess.Popen([sys.executable, "-m", "ai4bi_web_api.worker", str(self.store.root), *arguments],
                                env=env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def clear_worker_folder(self, folder):
        if folder is None:
            return
        import logging
        logger = logging.getLogger(__name__)
        folder = Path(folder)
        attempts = self.pending_cleanup.pop(folder, (0, 0))[0] + 1
        # Only our known handoff files; never recursively remove user paths.
        try:
            expected = self.store.root.resolve() / "staging" / "workers" / folder.name
            if (len(folder.name) != 32 or any(c not in "0123456789abcdef" for c in folder.name)
                    or folder.absolute() != expected or folder.resolve() != expected):
                logger.warning("Refusing worker cleanup outside its owned directory: %s", folder)
                return
            if not folder.exists():
                return
            for name in ("ready", "ready.tmp", "assignment.tmp", "assignment", "fatal.tmp", "fatal.json"):
                (folder / name).unlink(missing_ok=True)
            folder.rmdir()
        except OSError as exc:
            transient = isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in {32, 33}
            retry = transient and attempts < 3 and len(self.pending_cleanup) < 64
            if retry:
                self.pending_cleanup[folder] = attempts, time.monotonic() + 5
            logger.warning("Worker handoff cleanup failed: %s; error=%s errno=%s winerror=%s attempt=%s retry=%s",
                           folder, type(exc).__name__, exc.errno, getattr(exc, "winerror", None), attempts, retry)

    def retry_worker_cleanup(self, *, force=False):
        moment = time.monotonic()
        for folder, (_, due) in list(self.pending_cleanup.items()):
            if force or moment >= due:
                self.clear_worker_folder(folder)

    def retire_idle_worker(self, slot):
        process, folder = slot
        if process.poll() is not None:
            from .worker import read_failure
            diagnostic = read_failure(self.store.root, folder) if folder is not None else None
            if diagnostic:
                import logging
                logging.getLogger(__name__).warning("Idle worker failed: %s", diagnostic)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        if process.stdin:
            process.stdin.close()
        self.clear_worker_folder(folder)

    def retire_standby(self):
        if self.standby is None:
            return
        self.retire_idle_worker(self.standby)
        self.standby = None
        self.standby_workspace = None

    def retire_spare(self):
        if self.spare is None:
            return
        self.retire_idle_worker(self.spare)
        self.spare = None

    def prewarm(self):
        moment = time.monotonic()
        if self.running:
            self.last_activity = moment
        if self.standby and self.standby[0].poll() is not None:
            self.retire_standby()
            self.next_prewarm = moment + 5
        if self.spare and self.spare[0].poll() is not None:
            self.retire_spare()
            self.next_prewarm = moment + 5
        if moment-self.last_activity >= 60:
            self.retire_standby()
            self.retire_spare()
            return
        if self.standby is None and self.spare is not None:
            self.standby, self.spare = self.spare, None
            self.standby_workspace = None
        count = len(self.running) + int(self.standby is not None) + int(self.spare is not None)
        has_fresh = self.spare is not None or self.standby is not None and self.standby_workspace is None
        if self.stop_event.is_set() or count >= 2 or has_fresh or moment < self.next_prewarm:
            return
        token = uid()
        folder = self.store.root / "staging" / "workers" / token
        folder.mkdir(parents=True)
        try:
            slot = self.spawn("--standby", token), folder
            if self.standby is None:
                self.standby = slot
                self.standby_workspace = None
            else:
                self.spare = slot
        except OSError:
            self.clear_worker_folder(folder)
            self.next_prewarm = moment + 5

    def dispatch(self, jid, wid):
        self.last_activity = time.monotonic()
        if self.standby and self.standby[0].poll() is not None:
            self.retire_standby()
        if self.standby and self.standby_workspace not in {None, wid}:
            self.retire_standby()
        self.prewarm()
        if self.standby:
            process, folder = self.standby
            try:
                (folder / "ready").unlink(missing_ok=True)
                pending = folder / "assignment.tmp"
                pending.write_text(jid, encoding="ascii")
                pending.replace(folder / "assignment")
            except OSError:
                self.retire_standby()
            else:
                self.worker_folders[jid] = folder
                self.standby = None
                self.standby_workspace = None
                return process
        return self.spawn(jid)

    def tick(self):
        with self.guard:
            self.retry_worker_cleanup()
            for jid, (process, wid, started) in list(self.running.items()):
                observed_job = self.get(jid)
                state = observed_job["status"]
                timed_out = time.monotonic() - started > 120
                if state == "cancelling" or timed_out:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=10)
                folder = self.worker_folders.get(jid)
                completed = False
                if folder is not None:
                    try:
                        with (folder / "ready").open("r", encoding="ascii") as marker:
                            completed = marker.read(33) == jid
                    except (OSError, UnicodeError):
                        pass
                if process.poll() is None and not completed:
                    continue
                path = self.store.root / "staging" / "jobs" / jid / "result.json"
                payload = finished_payload(path, 0 if process.returncode is None and completed else process.returncode)
                if (state != "cancelling" and not timed_out
                        and payload.get("error", {}).get("code") == "WORKER_FAILED"):
                    from .worker import read_failure
                    diagnostic = read_failure(self.store.root, folder or path.parent)
                    if diagnostic:
                        payload["error"]["diagnostic"] = diagnostic
                    import logging
                    logging.getLogger(__name__).warning(
                        "Worker result rejected: exit_code=%s completed_marker=%s result_file=%s diagnostic=%s",
                        process.returncode, completed, path.is_file(), diagnostic)
                with self.store.transaction() as db:
                    latest = db.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()[0]
                    if latest == "cancelling":
                        status, result, error = "cancelled", None, None
                    elif timed_out:
                        status, result, error = "failed", None, {"code": "QUERY_TIMEOUT", "message": "分析超過時間上限。"}
                    elif "error" in payload:
                        status, result, error = "failed", None, payload["error"]
                    else:
                        status, result, error = "succeeded", payload["result"], None
                        kind = db.execute("SELECT kind FROM jobs WHERE id=?", (jid,)).fetchone()[0]
                        if kind == "publish":
                            from .publications import complete_publication
                            try:
                                result = complete_publication(db, jid, wid, result)
                            except (AppError, ValueError, TypeError, KeyError):
                                status, result, error = "failed", None, {
                                    "code":"PUBLICATION_INVALID", "message":"發布檢查未完成，請重新發布。"}
                        if kind == "export":
                            try:
                                format = result.get("format")
                                if format not in ("xlsx", "pdf", "json", "csv"):
                                    raise ValueError("Invalid export format")
                                from .exports import export_suffix
                                source = path.parent / ("export." + export_suffix(format))
                                destination = self.store.root / "workspaces" / wid / "artifacts" / jid
                                destination.mkdir(parents=True, exist_ok=True)
                                final = destination / ("export." + export_suffix(format))
                                if source.exists():
                                    source.replace(final)
                                if not final.is_file():
                                    raise FileNotFoundError("Missing export artifact")
                                result["artifact_id"] = jid
                            except (OSError, ValueError):
                                status, result, error = "failed", None, {
                                    "code": "ARTIFACT_PUBLISH_FAILED", "message": "匯出檔案無法保存，請檢查儲存空間後重新匯出。"}
                    if status == "succeeded":
                        timings = result.get("timings_ms")
                        if not isinstance(timings, dict):
                            timings = result["timings_ms"] = {}
                        # 'updated_at' is the persisted dispatch timestamp while
                        # running. Preloaded imports may precede acceptance and
                        # therefore must not be added to user-perceived latency.
                        timings.update({
                            "coordinator_queue_wall": wall_elapsed_ms(observed_job["created_at"], observed_job["updated_at"]),
                            "coordinator_accepted_to_collection_wall": wall_elapsed_ms(observed_job["created_at"], now()),
                            "coordinator_dispatch_to_collection": round((time.monotonic()-started)*1000, 2),
                        })
                    db.execute("UPDATE jobs SET status=?,result=?,error=?,updated=? WHERE id=? AND status IN ('running','cancelling')",
                               (status, encode(result) if result is not None else None,
                                encode(error) if error else None, now(), jid))
                self.running.pop(jid)
                # A long-running job is activity, not time spent idle. Give its
                # reusable process a full idle interval after completion.
                self.last_activity = time.monotonic()
                folder = self.worker_folders.pop(jid, None)
                can_retain = self.standby is None or self.standby_workspace is None and self.spare is None
                if completed and status == "succeeded" and process.poll() is None and can_retain:
                    if self.standby is not None:
                        self.spare = self.standby
                    self.standby = process, folder
                    self.standby_workspace = wid
                else:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=10)
                    if getattr(process, "stdin", None):
                        process.stdin.close()
                    self.clear_worker_folder(folder)
            occupied = {wid for _, wid, _ in self.running.values()}
            with self.store.transaction() as db:
                queued = db.execute("SELECT id,wid FROM jobs WHERE status='queued' ORDER BY created").fetchall()
                for row in queued:
                    if len(self.running) >= 2:
                        break
                    if row["wid"] in occupied:
                        continue
                    jid = row["id"]
                    folder = self.store.root / "staging" / "jobs" / jid
                    folder.mkdir(parents=True, exist_ok=True)
                    db.execute("UPDATE jobs SET status='running',updated=? WHERE id=?", (now(), jid))
                    try:
                        process = self.dispatch(jid, row["wid"])
                    except OSError:
                        db.execute("UPDATE jobs SET status='failed',error=?,updated=? WHERE id=?", (
                            encode({"code": "WORKER_START_FAILED", "message": "無法啟動分析工作，請檢查執行環境後重試。"}), now(), jid))
                        continue
                    self.running[jid] = process, row["wid"], time.monotonic()
                    occupied.add(row["wid"])
            self.prewarm()

    def loop(self):
        while not self.stop_event.wait(0.1):
            try:
                self.tick()
            except Exception:
                # Keep accepted jobs durable; next tick can resume coordinator work.
                import logging
                logging.getLogger(__name__).exception("Job coordinator tick failed")

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=15)
        with self.guard:
            self.retire_standby()
            self.retire_spare()
            for process, _, _ in self.running.values():
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
                if getattr(process, "stdin", None):
                    process.stdin.close()
            self.running.clear()
            for folder in self.worker_folders.values():
                self.clear_worker_folder(folder)
            self.worker_folders.clear()
            self.retry_worker_cleanup(force=True)
            if self.pending_cleanup:
                import logging
                logging.getLogger(__name__).warning("Worker cleanup still pending at shutdown: %s",
                                                    list(self.pending_cleanup))
                self.pending_cleanup.clear()


def make_snapshot(store: Store, wid: str, rid: str, revision: int, extra: dict, *, db=None) -> dict:
    with (nullcontext(db) if db is not None else store.transaction()) as db:
        report = store.report(wid, rid, db)
        if report["revision"] != revision:
            raise AppError("REVISION_CONFLICT", "請使用最新報表執行分析。", 409)
        rows = db.execute("SELECT * FROM datasets WHERE wid=? ORDER BY created", (wid,)).fetchall()
        datasets = [{"dataset_id": r["id"], "contract": json.loads(r["contract"]), "path": r["path"],
                     "version": r["hash"], "status": r["status"]} for r in rows]
        snapshot = {"report": report["report"], "revision": revision, "datasets": datasets, **extra, "as_of": now()}
        from .publications import EXECUTION_CONTRACT
        snapshot["execution_contract"] = EXECUTION_CONTRACT
        from .bookmarks import exploration_page, bookmark_filter_report
        if snapshot.get("filter_bookmark_id") is not None:
            snapshot["report_persistent_filters"] = snapshot["report"].get("web_extensions",{}).get("persistent_filters",[])
        snapshot["report"] = bookmark_filter_report(snapshot["report"], snapshot.get("filter_bookmark_id"))
        page_id = exploration_page(snapshot["report"], snapshot)
        if page_id is not None:
            snapshot["exploration_page_id"] = page_id
        # Retries return the accepted job without recapturing this timestamp or data.
        from .drilling import validate_snapshot
        validate_snapshot(snapshot)
        snapshot["snapshot_id"] = digest(snapshot)
        return snapshot
