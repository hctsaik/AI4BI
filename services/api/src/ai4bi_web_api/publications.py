"""Validated immutable report releases, independent of the working checkpoint."""
from importlib.metadata import version
from contextlib import closing
import json
import sqlite3

from . import __version__
from .errors import AppError
from .storage import digest, encode, now


CORE_MISMATCH = "此發布版本的分析核心與目前環境不同。請使用相容的安裝環境，或回到草稿重新驗證並發布新版本。"
EXECUTION_CONTRACT = "web-query-v7"
RUNTIME_MISMATCH = "此發布版本的 Web 執行契約缺失或與目前環境不同。請使用相容的安裝環境，或回到草稿重新驗證並發布新版本。"


def require_snapshot_contract(snapshot):
    if snapshot.get("execution_contract") != EXECUTION_CONTRACT:
        published = "publication_id" in snapshot
        raise AppError("PUBLICATION_RUNTIME_INCOMPATIBLE" if published else "SNAPSHOT_RUNTIME_INCOMPATIBLE",
                       RUNTIME_MISMATCH if published else "此工作的執行契約缺失或已變更，請重新提交工作。", 409)


def require_publication_runtime(checks, snapshot):
    require_core_version(checks.get("core_version"))
    if (checks.get("execution_contract") != EXECUTION_CONTRACT
            or snapshot.get("execution_contract") != EXECUTION_CONTRACT):
        raise AppError("PUBLICATION_RUNTIME_INCOMPATIBLE", RUNTIME_MISMATCH, 409)


def runtime_status(checks, snapshot):
    try:
        require_publication_runtime(checks, snapshot)
        return {"runtime_compatible": True, "runtime_message": None}
    except AppError as exc:
        return {"runtime_compatible": False, "runtime_message": exc.message}


def require_core_version(expected):
    if not isinstance(expected, str) or not expected or expected != version("ai4bi"):
        raise AppError("PUBLICATION_CORE_INCOMPATIBLE", CORE_MISMATCH, 409)


def check_execution_runtime(root, snapshot):
    """Recheck at execution, including jobs queued by builds without this guard."""
    require_snapshot_contract(snapshot)
    if "publication_id" not in snapshot:
        return
    with closing(sqlite3.connect((root / "metadata.sqlite").resolve().as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("SELECT checks FROM publications WHERE id=? AND rid=?",
                         (snapshot["publication_id"], snapshot["report"]["audit"]["report_id"])).fetchone()
    if not row:
        raise AppError("NOT_FOUND", "找不到此報表的發布版本。", 404)
    require_publication_runtime(json.loads(row[0]), snapshot)


def check_publication(root, snapshot):
    from .crossfact import delivery_checks as crossfact_checks
    from .commonality import delivery_checks as commonality_checks
    from .core import load_contracts, run_query, validate_report
    require_snapshot_contract(snapshot)
    body = snapshot["report"]
    visuals = [vid for page in body["pages"].values() for vid in page["visuals"]]
    if not visuals:
        raise AppError("PUBLICATION_EMPTY", "請先建立至少一個圖表，再發布報表。")
    if any(set(page["visual_order"]) != set(page["visuals"]) for page in body["pages"].values()):
        raise AppError("PUBLICATION_INVALID", "報表圖表清單不完整，請修正後再發布。")
    validate_report(body, load_contracts(root, snapshot["datasets"]))
    result = run_query(root, {**snapshot, "include_spc": True, "include_commonality": True, "include_crossfact": True, "include_change": True, "include_rfm": True})
    from .rfm import delivery_checks as rfm_checks
    from .change_analysis import delivery_checks as change_checks
    if set(result["visuals"]) != set(visuals) or any(v["status"] != "ready" for v in result["visuals"].values()):
        raise AppError("PUBLICATION_INVALID", "部分圖表無法完成查詢，請修正後再發布。")
    return {"checks": {"status":"passed", "snapshot_id":snapshot["snapshot_id"],
                       "visual_count":len(visuals), "checked_at":now(),
                       "spc_analyses": {key: {field: value[field] for field in ("analysis_contract", "status", "entity_count", "input_rows")}
                                        for key, value in result["spc_analyses"].items()},
                       "commonality_analyses": commonality_checks(snapshot["report"], result),
                       "crossfact_analyses": crossfact_checks(snapshot["report"], result),
                       "change_analyses": change_checks(snapshot["report"], result),
                       "rfm_analyses": rfm_checks(snapshot["report"], result),
                       "app_version":__version__, "core_version":version("ai4bi"),
                       "execution_contract": EXECUTION_CONTRACT,
                       "data_versions":result["data_versions"],
                       "truncated_visuals":[vid for vid, value in result["visuals"].items() if value.get("truncated")]}}


def complete_publication(db, jid, wid, result):
    snapshot = json.loads(db.execute("SELECT input FROM jobs WHERE id=? AND wid=?", (jid, wid)).fetchone()[0])
    from .crossfact import validate_delivery_checks as validate_crossfact_checks
    require_snapshot_contract(snapshot)
    from .change_analysis import validate_delivery_checks as validate_change_checks
    checks = result.get("checks", {})
    visual_ids = {vid for page in snapshot["report"]["pages"].values() for vid in page["visuals"]}
    from .report_extensions import extensions
    from .spc import ANALYSIS_CONTRACT
    analyses = checks.get("spc_analyses") if isinstance(checks, dict) else None
    expected_analyses = {item.analysis_id for item in extensions(snapshot["report"]).spc_analyses}
    if (not isinstance(analyses, dict) or set(analyses) != expected_analyses or any(
            not isinstance(item, dict) or item.get("analysis_contract") != ANALYSIS_CONTRACT
            or item.get("status") not in {"ready", "empty", "insufficient_groups", "zero_variance"}
            or any(type(item.get(field)) is not int or item[field] < 0 for field in ("entity_count", "input_rows"))
            for item in analyses.values())):
        raise AppError("PUBLICATION_INVALID", "SPC 發布檢查結果與固定設定不一致。")
    if (not isinstance(checks, dict) or not visual_ids
            or checks.get("execution_contract") != snapshot["execution_contract"]
            or checks.get("core_version") != version("ai4bi")
            or not all(isinstance(checks.get(name), str) and checks[name] for name in ("checked_at", "app_version", "core_version"))
            or not isinstance(checks.get("truncated_visuals"), list)
            or not all(isinstance(vid, str) and vid in visual_ids for vid in checks["truncated_visuals"])
            or not snapshot["report"].get("read_only") or checks.get("status") != "passed"
            or checks.get("snapshot_id") != snapshot["snapshot_id"]
            or checks.get("data_versions") != {d["dataset_id"]:d["version"] for d in snapshot["datasets"]}
            or checks.get("visual_count") != sum(len(p["visuals"]) for p in snapshot["report"]["pages"].values())):
        raise AppError("PUBLICATION_INVALID", "發布檢查結果與固定快照不一致。")
    from .commonality import validate_delivery_checks
    validate_delivery_checks(snapshot["report"], checks.get("commonality_analyses"))
    validate_crossfact_checks(snapshot["report"], checks.get("crossfact_analyses"))
    validate_change_checks(snapshot["report"], checks.get("change_analyses"))
    from .rfm import validate_delivery_checks as validate_rfm_checks
    validate_rfm_checks(snapshot["report"], checks.get("rfm_analyses"))
    rid = snapshot["report"]["audit"]["report_id"]
    number = db.execute("SELECT COALESCE(MAX(published_revision),0)+1 FROM publications WHERE rid=?", (rid,)).fetchone()[0]
    db.execute("INSERT INTO publications VALUES(?,?,?,?,?,?,?,?)",
               (jid, rid, wid, number, snapshot["revision"], encode(snapshot), encode(checks), now()))
    return {"publication_id":jid, "published_revision":number, "source_revision":snapshot["revision"]}


def publication_row(db, wid, rid, pid):
    row = db.execute("SELECT * FROM publications WHERE id=? AND wid=? AND rid=?", (pid, wid, rid)).fetchone()
    if not row:
        raise AppError("NOT_FOUND", "找不到此報表的發布版本。", 404)
    return row


def summary(row):
    return {"publication_id":row["id"], "published_revision":row["published_revision"],
            "source_revision":row["source_revision"], "created_at":row["created"]}


def list_publications(store, wid, rid):
    store.report(wid, rid)
    with store.connect() as db:
        return [{**summary(row), **runtime_status(json.loads(row["checks"]), json.loads(row["snapshot"]))} for row in db.execute(
            "SELECT id,published_revision,source_revision,created,checks,snapshot FROM publications WHERE wid=? AND rid=? ORDER BY published_revision DESC", (wid, rid))]


def get_publication(store, wid, rid, pid):
    with store.connect() as db:
        row = publication_row(db, wid, rid, pid)
        snapshot = json.loads(row["snapshot"])
        checks = json.loads(row["checks"])
        return {**summary(row), "report_id":rid, "workspace_id":wid,
                "report":snapshot["report"], "snapshot_id":snapshot["snapshot_id"], "as_of":snapshot["as_of"],
                "data_versions":{d["dataset_id"]:d["version"] for d in snapshot["datasets"]},
                "checks":checks, **runtime_status(checks, snapshot)}


def publication_snapshot(db, wid, rid, pid, revision, extra):
    row = publication_row(db, wid, rid, pid)
    if row["source_revision"] != revision:
        raise AppError("REVISION_CONFLICT", "請使用此發布版本的來源修訂號。", 409)
    snapshot = json.loads(row["snapshot"])
    require_publication_runtime(json.loads(row["checks"]), snapshot)
    snapshot.update(extra)
    from .bookmarks import exploration_page, bookmark_filter_report
    snapshot["report"] = bookmark_filter_report(snapshot["report"], snapshot.get("filter_bookmark_id"))
    page_id = exploration_page(snapshot["report"], snapshot)
    if page_id is not None:
        snapshot["exploration_page_id"] = page_id
    snapshot["publication_id"] = pid
    snapshot.pop("snapshot_id")
    from .drilling import validate_snapshot
    validate_snapshot(snapshot)
    snapshot["snapshot_id"] = digest(snapshot)
    return snapshot
