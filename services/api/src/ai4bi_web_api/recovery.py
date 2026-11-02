"""Verified backup references and restore into a new, independently owned data root."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

from .errors import AppError
from .migrations import CURRENT_SCHEMA


def checksum(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def confined_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    result = (root / path).resolve()
    if path.is_absolute() or path.drive or ".." in path.parts or any(":" in part for part in path.parts) or not result.is_relative_to(root.resolve()):
        raise AppError("BACKUP_INVALID_PATH", "備份含有不合法的檔案路徑。")
    if result == root.resolve():
        raise AppError("BACKUP_INVALID_PATH", "備份引用必須是檔案。")
    return result


def artifact_references(db: sqlite3.Connection) -> dict[str, str | None]:
    references = {}
    for row in db.execute("SELECT path,hash,status FROM datasets"):
        if row[2] != "ready":
            raise AppError("BACKUP_SOURCE_NOT_READY", "資料尚在發布或需要修復，請稍後備份。", 409)
        references[row[0]] = row[1]
    if db.execute("PRAGMA user_version").fetchone()[0] >= 2:
        for row in db.execute("SELECT snapshot FROM publications"):
            for dataset in json.loads(row[0])["datasets"]:
                relative, version = dataset["path"], dataset["version"]
                if relative in references and references[relative] != version:
                    raise AppError("BACKUP_CORRUPT", "同一資料檔案有衝突的版本引用。")
                references[relative] = version
    for row in db.execute("SELECT source FROM imports"):
        references[row[0]] = None
    for jid, wid, raw in db.execute("SELECT id,wid,result FROM jobs WHERE kind='export' AND status='succeeded'"):
        result = json.loads(raw)
        if result.get("format") not in ("xlsx", "pdf", "json"):
            raise AppError("BACKUP_INVALID_ARTIFACT", "匯出檔案格式不合法。")
        references[str(Path("workspaces") / wid / "artifacts" / jid / ("export." + result["format"]))] = None
    return references


def verify_backup(source: Path) -> dict:
    source = source.resolve()
    try:
        manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("schema") != 1:
            raise AppError("SCHEMA_INCOMPATIBLE", "備份版本不相容。", 409)
        database = confined_path(source, "metadata.sqlite")
        if checksum(database) != manifest["database_sha256"]:
            raise AppError("BACKUP_CORRUPT", "備份資料庫校驗失敗。")
        listed = {}
        for item in manifest["artifacts"]:
            relative = item["path"]
            if relative in listed or relative in ("metadata.sqlite", "manifest.json"):
                raise AppError("BACKUP_CORRUPT", "備份包含重複或保留路徑。")
            if checksum(confined_path(source, relative)) != item["sha256"]:
                raise AppError("BACKUP_CORRUPT", "備份檔案校驗失敗。")
            listed[relative] = item["sha256"]
        db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        try:
            database_schema = db.execute("PRAGMA user_version").fetchone()[0]
            if not 1 <= database_schema <= CURRENT_SCHEMA:
                raise AppError("SCHEMA_INCOMPATIBLE", "備份資料庫版本不相容。", 409)
            if manifest.get("database_schema", database_schema) != database_schema:
                raise AppError("BACKUP_CORRUPT", "備份宣告與資料庫版本不一致。")
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
                raise AppError("BACKUP_CORRUPT", "備份資料庫完整性檢查失敗。")
            required = artifact_references(db)
            if set(required) != set(listed) or any(value and value != listed[path] for path, value in required.items()):
                raise AppError("BACKUP_INCOMPLETE", "備份的檔案清單與資料庫引用不一致。")
        finally:
            db.close()
        return manifest
    except AppError:
        raise
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        raise AppError("BACKUP_CORRUPT", "備份不完整或無法讀取。") from exc


def restore_backup(source: Path, target: Path) -> Path:
    try:
        return _restore_backup(source, target)
    except OSError as exc:
        raise AppError("RESTORE_WRITE_FAILED", "還原無法寫入；請檢查權限及可用磁碟空間。原資料未被覆寫。", 500) from exc


def _restore_backup(source: Path, target: Path) -> Path:
    from .storage import Store, uid
    source, target = source.resolve(), target.resolve()
    if target.exists() or target.is_relative_to(source) or source.is_relative_to(target):
        raise AppError("INVALID_RESTORE_PATH", "還原必須使用新的獨立資料目錄；不覆寫現有資料。")
    manifest = verify_backup(source)
    stage = target.with_name(target.name + ".restoring-" + uid())
    stage.mkdir(parents=True)
    # Partial staging survives failures for diagnosis; it is never published as target.
    for relative in ["metadata.sqlite", "manifest.json", *(item["path"] for item in manifest["artifacts"])]:
        output = confined_path(stage, relative)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(confined_path(source, relative), output)
    verify_backup(stage)
    restored = Store(stage)
    try:
        # Queued work has no owner after restore; require an explicit new request.
        with restored.transaction() as db:
            db.execute("UPDATE jobs SET status='cancelled' WHERE status='queued'")
    finally:
        restored.close()
    # rename on Windows refuses an existing destination; never merge into user data.
    if target.exists():
        raise AppError("INVALID_RESTORE_PATH", "還原目的地已存在。")
    stage.rename(target)
    return target
