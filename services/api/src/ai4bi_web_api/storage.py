"""Single-owner SQLite state and immutable, journaled dataset artifacts."""
from __future__ import annotations

from contextlib import contextmanager, closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Callable, Any
import uuid

from filelock import FileLock, Timeout
from .errors import AppError
from .migrations import CURRENT_SCHEMA, migrate


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return uuid.uuid4().hex


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


class ClosingConnection(sqlite3.Connection):
    """Commit/rollback and release Windows file handles at the context boundary."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(self.root / "coordinator.lock")
        try:
            self.lock.acquire(timeout=0)
        except Timeout as exc:
            raise AppError("DATA_ROOT_BUSY", "此資料目錄已有執行中的 AI4BI。", 409) from exc
        self.db_path = self.root / "metadata.sqlite"
        try:
            with self.connect() as db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version > CURRENT_SCHEMA:
                    raise AppError("SCHEMA_INCOMPATIBLE", "資料版本較新，請使用相容的程式版本。", 409)
                if version == 1:
                    # Keep a complete pre-upgrade recovery point beside the data root.
                    # A failed backup leaves the source schema untouched.
                    self.backup(self.root.with_name(self.root.name + ".before-schema-2-" + uid()))
                db.executescript("""
                    PRAGMA journal_mode=WAL;
                    CREATE TABLE IF NOT EXISTS workspaces(
                      id TEXT PRIMARY KEY, title TEXT NOT NULL, created TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS reports(
                      id TEXT PRIMARY KEY, wid TEXT NOT NULL REFERENCES workspaces(id),
                      revision INTEGER NOT NULL, saved INTEGER NOT NULL,
                      history TEXT NOT NULL, pointer INTEGER NOT NULL);
                    CREATE TABLE IF NOT EXISTS revisions(
                      rid TEXT NOT NULL REFERENCES reports(id), revision INTEGER NOT NULL,
                      body TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(rid,revision));
                    CREATE TABLE IF NOT EXISTS dedup(
                      scope TEXT NOT NULL, key TEXT NOT NULL, hash TEXT NOT NULL,
                      response TEXT NOT NULL, PRIMARY KEY(scope,key));
                    CREATE TABLE IF NOT EXISTS datasets(
                      id TEXT PRIMARY KEY, wid TEXT NOT NULL REFERENCES workspaces(id),
                      contract TEXT NOT NULL, path TEXT NOT NULL, hash TEXT NOT NULL,
                      status TEXT NOT NULL, created TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS imports(
                      id TEXT PRIMARY KEY, wid TEXT NOT NULL REFERENCES workspaces(id),
                      revision INTEGER NOT NULL, name TEXT NOT NULL, source TEXT NOT NULL,
                      config TEXT NOT NULL, status TEXT NOT NULL, details TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS jobs(
                      id TEXT PRIMARY KEY, wid TEXT NOT NULL REFERENCES workspaces(id),
                      kind TEXT NOT NULL, status TEXT NOT NULL, input TEXT NOT NULL,
                      result TEXT, error TEXT, created TEXT NOT NULL, updated TEXT NOT NULL);
                """)
                migrate(db)
            self.recover()
        except Exception:
            self.lock.release()
            raise

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=10, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def close(self):
        self.lock.release()

    def get_workspace(self, wid: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM workspaces WHERE id=?", (wid,)).fetchone()
            if not row:
                raise AppError("NOT_FOUND", "找不到工作區。", 404)
            reports = [r[0] for r in db.execute("SELECT id FROM reports WHERE wid=?", (wid,))]
        return {"workspace_id": wid, "title": row["title"], "created_at": row["created"], "report_ids": reports}

    def list_workspaces(self) -> list[dict]:
        with self.connect() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM workspaces ORDER BY created DESC")]
        return [self.get_workspace(wid) for wid in ids]

    def idempotent(self, db, scope: str, key: str, payload: Any, action: Callable[[], Any]):
        fingerprint = digest(payload)
        found = db.execute("SELECT hash,response FROM dedup WHERE scope=? AND key=?", (scope, key)).fetchone()
        if found:
            if found["hash"] != fingerprint:
                raise AppError("IDEMPOTENCY_CONFLICT", "相同請求識別碼不可使用不同內容。", 409)
            return json.loads(found["response"])
        result = action()
        db.execute("INSERT INTO dedup VALUES(?,?,?,?)", (scope, key, fingerprint, encode(result)))
        return result

    def create_workspace(self, title: str, report: dict, key: str, template: str):
        with self.transaction() as db:
            def action():
                wid, rid = uid(), uid()
                db.execute("INSERT INTO workspaces VALUES(?,?,?)", (wid, title, now()))
                report["audit"]["report_id"] = rid
                report["audit"]["revision"] = 1
                db.execute("INSERT INTO reports VALUES(?,?,1,1,?,0)", (rid, wid, encode([1])))
                db.execute("INSERT INTO revisions VALUES(?,1,?,?)", (rid, encode(report), now()))
                return {"workspace_id": wid, "report_id": rid}
            return self.idempotent(db, "create-workspace", key, {"title": title, "template": template}, action)

    def report(self, wid: str, rid: str, db=None) -> dict:
        own = db is None
        db = db or self.connect()
        try:
            row = db.execute("SELECT * FROM reports WHERE id=? AND wid=?", (rid, wid)).fetchone()
            if not row:
                raise AppError("NOT_FOUND", "找不到報表。", 404)
            body = json.loads(db.execute("SELECT body FROM revisions WHERE rid=? AND revision=?", (rid, row["revision"])).fetchone()[0])
            saved_body = json.loads(db.execute("SELECT body FROM revisions WHERE rid=? AND revision=?", (rid, row["saved"])).fetchone()[0])
            def content(value):
                clone = json.loads(encode(value))
                clone.get("audit", {}).pop("revision", None)
                return clone
            history = json.loads(row["history"])
            return {"report_id": rid, "workspace_id": wid, "revision": row["revision"],
                    "saved_revision": row["saved"], "dirty": content(body) != content(saved_body),
                    "can_undo": row["pointer"] > 0, "can_redo": row["pointer"] < len(history)-1,
                    "report": body}
        finally:
            if own:
                db.close()

    def command(self, wid: str, rid: str, command: dict, transform: Callable[[dict], dict]):
        with self.transaction() as db:
            def action():
                current = self.report(wid, rid, db)
                if current["revision"] != command["base_revision"]:
                    raise AppError("REVISION_CONFLICT", "報表已變更，請重新載入再套用。", 409)
                row = db.execute("SELECT * FROM reports WHERE id=?", (rid,)).fetchone()
                kind = command["command_type"]
                if current["report"].get("read_only"):
                    raise AppError("READ_ONLY", "此報表為唯讀。", 403)
                if kind == "save":
                    db.execute("UPDATE reports SET saved=revision WHERE id=?", (rid,))
                else:
                    history, pointer = json.loads(row["history"]), row["pointer"]
                    if kind in ("undo", "redo"):
                        pointer += -1 if kind == "undo" else 1
                        if pointer < 0 or pointer >= len(history):
                            raise AppError("HISTORY_BOUNDARY", "沒有可還原的操作。", 409)
                        body = json.loads(db.execute("SELECT body FROM revisions WHERE rid=? AND revision=?", (rid, history[pointer])).fetchone()[0])
                    elif kind == "restore_saved":
                        body = json.loads(db.execute("SELECT body FROM revisions WHERE rid=? AND revision=?", (rid, row["saved"])).fetchone()[0])
                    else:
                        body = transform(current["report"])
                    revision = current["revision"] + 1
                    body["audit"]["revision"] = revision
                    body["audit"]["report_id"] = rid
                    db.execute("INSERT INTO revisions VALUES(?,?,?,?)", (rid, revision, encode(body), now()))
                    if kind not in ("undo", "redo"):
                        history = history[:pointer+1] + [revision]
                        history = history[-101:]
                        pointer = len(history)-1
                    db.execute("UPDATE reports SET revision=?,history=?,pointer=? WHERE id=?", (revision, encode(history), pointer, rid))
                return self.report(wid, rid, db)
            return self.idempotent(db, f"command:{wid}:{rid}", command["idempotency_key"], command, action)

    def publish_dataset(self, wid: str, contract: dict, frame, dataset_id: str | None = None) -> str:
        self.get_workspace(wid)
        did = dataset_id or uid()
        folder = self.root / "workspaces" / wid / "datasets" / did
        folder.mkdir(parents=True, exist_ok=True)
        stage, final = folder / "data.tmp.parquet", folder / "data.parquet"
        frame.to_parquet(stage, index=False)
        checksum = hashlib.sha256(stage.read_bytes()).hexdigest()
        path = str(final.relative_to(self.root))
        metadata = {key: value for key, value in contract.items() if key != "data_source"}
        metadata["data_source"] = {"source_type": "inline", "records": []}
        with self.transaction() as db:
            db.execute("INSERT INTO datasets VALUES(?,?,?,?,?,?,?)",
                       (did, wid, encode(metadata), path, checksum, "publishing", now()))
        stage.replace(final)
        with self.transaction() as db:
            db.execute("UPDATE datasets SET status='ready' WHERE id=?", (did,))
        return did

    def datasets(self, wid: str) -> list[dict]:
        self.get_workspace(wid)
        with self.connect() as db:
            return [{"dataset_id": row["id"], "contract": json.loads(row["contract"]),
                     "version": row["hash"], "path": row["path"], "status": row["status"]}
                    for row in db.execute("SELECT * FROM datasets WHERE wid=? ORDER BY created", (wid,))]

    def recover(self):
        with self.transaction() as db:
            db.execute("UPDATE jobs SET status='failed',error=?,updated=? WHERE status IN ('running','cancelling')",
                       (encode({"code": "JOB_INTERRUPTED", "message": "服務中斷，請重新執行。"}), now()))
            for row in db.execute("SELECT id,path,hash FROM datasets WHERE status='publishing'").fetchall():
                path = self.root / row["path"]
                stage = path.with_name("data.tmp.parquet")
                candidate = path if path.exists() else stage
                valid = candidate.is_file() and hashlib.sha256(candidate.read_bytes()).hexdigest() == row["hash"]
                if valid and candidate != path:
                    candidate.replace(path)
                db.execute("UPDATE datasets SET status=? WHERE id=?", ("ready" if valid else "damaged", row["id"]))

    def backup(self, target: Path):
        """Create a new directory backup; pin writes during manifest capture."""
        target = target.resolve()
        if target.exists() or target.is_relative_to(self.root) or self.root.is_relative_to(target):
            raise AppError("INVALID_BACKUP_PATH", "備份必須使用新的獨立目錄。")
        target.mkdir(parents=True)
        # Transaction excludes dataset metadata publication while references are copied.
        with self.transaction() as db:
            manifest = []
            with closing(self.connect()) as reader, closing(sqlite3.connect(target / "metadata.sqlite")) as destination:
                reader.backup(destination)
            from .recovery import artifact_references, confined_path, checksum
            for relative, expected_hash in artifact_references(db).items():
                source = confined_path(self.root, relative)
                output = confined_path(target, relative)
                output.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copyfile(source, output)
                except OSError as exc:
                    raise AppError("BACKUP_COPY_FAILED", "備份檔案無法複製；請檢查來源與可用磁碟空間。", 500) from exc
                actual_hash = checksum(output)
                if expected_hash and actual_hash != expected_hash:
                    raise AppError("BACKUP_CORRUPT", "備份資料校驗失敗。", 500)
                manifest.append({"path": relative, "sha256": actual_hash})
            from importlib.metadata import version
            from . import __version__
            metadata = {"schema": 1, "database_schema": db.execute("PRAGMA user_version").fetchone()[0],
                        "app_version": __version__, "core_version": version("ai4bi"),
                        "database_sha256": checksum(target / "metadata.sqlite"),
                        "artifacts": manifest, "created": now()}
            # Written last: an interrupted directory without this marker is not a backup.
            (target / "manifest.json").write_text(encode(metadata), encoding="utf-8")
