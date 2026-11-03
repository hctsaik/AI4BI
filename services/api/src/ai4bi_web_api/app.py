"""HTTP boundary, session guard, static UI and application lifecycle."""
from __future__ import annotations

from contextlib import asynccontextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, UploadFile, File, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from . import __version__
from .validation_cache import QueryValidationCache
from .errors import AppError
from .imports import create_import, get_import, validate_import, commit_import, list_imports
from .jobs import Jobs
from .schemas import (PairRequest, WorkspaceCreate, Command, QueryRequest, AssistantRequest,
                      ImportConfig, ImportCommit, JobView, ExportRequest, PublishRequest, SpcRequest, CommonalityRequest, CrossFactRequest, ChangeRequest, RfmRequest, SummaryRequest, AlertEvaluationRequest)
from .storage import Store, uid, encode
from .static_assets import verify_manifest, validate_launch_identity


def create_app(data_root: Path, pairing_code: str | None = None, static_root: Path | None = None,
               *, instance_id: str | None = None, expected_build_id: str | None = None,
               session_cookie_mode: str = "strict") -> FastAPI:
    if session_cookie_mode not in {"strict", "partitioned"}:
        raise ValueError("Invalid session cookie mode")
    code = pairing_code or secrets.token_urlsafe(24)
    sessions: dict[str, float] = {}
    instance = instance_id if instance_id is not None else uid()
    static = static_root or Path(__file__).parent / "static"
    launch_build_id = expected_build_id
    validate_launch_identity(static, instance, expected_build_id)

    @asynccontextmanager
    async def lifespan(app):
        store = Store(data_root)
        app.state.store, app.state.jobs = store, Jobs(store)
        app.state.validation_cache = QueryValidationCache()
        try:
            yield
        finally:
            app.state.jobs.close()
            store.close()

    app = FastAPI(title="AI4BI Web", version=__version__, lifespan=lifespan)
    app.state.pairing_code = code
    app.state.paired = False

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message,
                                      "request_id": request.state.request_id,
                                      "retryable": exc.status in (429, 503)}}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc):
        return JSONResponse({"error": {"code": "INVALID_REQUEST", "message": "請求欄位格式不正確。",
                                      "request_id": request.state.request_id}}, status_code=422)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        request.state.request_id = uid()
        host = request.url.hostname
        if host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
            return JSONResponse({"error": {"code": "INVALID_HOST", "message": "僅支援本機連線。"}}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"error": {"code": "INVALID_ORIGIN", "message": "拒絕跨來源請求。"}}, status_code=403)
        if request.url.path.startswith("/api/") and request.url.path != "/api/v1/session":
            auth = request.headers.get("authorization", "")
            token = auth[7:] if auth.startswith("Bearer ") else request.cookies.get("ai4bi_session", "")
            if sessions.get(token, 0) < time.time():
                return JSONResponse({"error": {"code": "SESSION_REQUIRED", "message": "請輸入本次啟動的配對碼。"}}, status_code=401)
            if request.method not in ("GET", "HEAD") and request.headers.get("x-ai4bi-request") != "1":
                return JSONResponse({"error": {"code": "CSRF_REJECTED", "message": "無效的操作來源。"}}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path.startswith("/api/") or request.url.path in ("/ready", "/health", "/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health():
        return {"app_id": "ai4bi-web", "version": __version__, "instance_id": instance, "status": "alive"}

    @app.get("/ready")
    def ready(expected_instance_id: str | None = Query(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$"),
              expected_build_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{64}$")):
        if not (static / "index.html").is_file():
            raise AppError("UI_NOT_BUILT", "React 靜態檔尚未建置。", 503)
        identity = {**health(), **verify_manifest(static), "status": "ready"}
        if launch_build_id is not None and identity["build_id"] != launch_build_id:
            raise AppError("BUILD_ID_MISMATCH", "目前建置已偏離啟動時指定的版本。", 409)
        if ((expected_instance_id is not None and expected_instance_id != instance)
                or (expected_build_id is not None and expected_build_id != identity["build_id"])):
            raise AppError("READY_IDENTITY_MISMATCH", "就緒服務與預期的執行個體或建置不符。", 409)
        return identity

    @app.post("/api/v1/session")
    def pair(body: PairRequest):
        if app.state.paired or not secrets.compare_digest(body.code, code):
            raise AppError("PAIRING_REJECTED", "配對碼錯誤或已使用；已有分頁可沿用 session，否則請重新啟動。", 401)
        app.state.paired = True
        token = secrets.token_urlsafe(32)
        sessions[token] = time.time() + 12*3600
        response = JSONResponse({"token": token, "expires_in": 12*3600})
        partitioned = session_cookie_mode == "partitioned"
        response.set_cookie("ai4bi_session", token, httponly=True, secure=partitioned,
                            samesite="none" if partitioned else "strict", max_age=12*3600)
        if partitioned:
            # Python 3.11's cookie serializer has no Partitioned attribute. Append
            # only this constant to the server-generated Set-Cookie header.
            response.headers["set-cookie"] += "; Partitioned"
        return response

    @app.get("/api/v1/capabilities")
    def capabilities():
        from ai4bi.query_spec import VisualType
        return {"app_version": __version__, "api_version": 1, "templates": ["fab", "retail", "cv", "blank"],
                "visual_types": [kind.value for kind in VisualType], "llm_mode": os.environ.get("LLM_MODE", "mock"),
                "features": ["workspaces", "query", "history", "imports", "assistant"]}

    @app.get("/api/v1/workspaces")
    def workspaces():
        return app.state.store.list_workspaces()

    @app.post("/api/v1/workspaces")
    def new_workspace(body: WorkspaceCreate):
        import pandas as pd
        from .core import template
        report, contracts = template(body.template)
        result = app.state.store.create_workspace(body.title, report, body.idempotency_key, body.template)
        for block_id, contract in contracts.items():
            dataset_id = hashlib.sha256(f"{result['workspace_id']}:{block_id}".encode()).hexdigest()[:32]
            existing = app.state.store.datasets(result["workspace_id"])
            if not any(d["dataset_id"] == dataset_id for d in existing):
                app.state.store.publish_dataset(result["workspace_id"], contract.model_dump(mode="json"),
                                                pd.DataFrame(contract.data_source.records), dataset_id)
        return result

    @app.get("/api/v1/workspaces/{wid}")
    def workspace(wid: str):
        return app.state.store.get_workspace(wid)

    @app.get("/api/v1/workspaces/{wid}/datasets")
    def datasets(wid: str):
        return [{k: v for k, v in d.items() if k != "path"} for d in app.state.store.datasets(wid)]

    @app.get("/api/v1/workspaces/{wid}/datasets/{did}/preview")
    def preview(wid: str, did: str, offset: int = 0, limit: int = 100):
        if offset < 0 or not 1 <= limit <= 1000:
            raise AppError("INVALID_PAGE", "分頁範圍不合法。")
        item = next((d for d in app.state.store.datasets(wid) if d["dataset_id"] == did), None)
        if not item or item["status"] != "ready":
            raise AppError("NOT_FOUND", "找不到可預覽資料。", 404)
        import pyarrow.parquet as pq
        from .core import clean
        parquet = pq.ParquetFile(app.state.store.root / item["path"])
        rows, skipped = [], 0
        for batch in parquet.iter_batches(batch_size=min(1000, offset + limit)):
            if skipped + batch.num_rows <= offset:
                skipped += batch.num_rows
                continue
            start = max(0, offset-skipped)
            rows.extend(batch.slice(start, min(limit-len(rows), batch.num_rows-start)).to_pylist())
            skipped += batch.num_rows
            if len(rows) >= limit:
                break
        return {"columns": parquet.schema_arrow.names, "rows": clean(rows),
                "row_count": parquet.metadata.num_rows, "offset": offset, "version": item["version"]}

    @app.get("/api/v1/workspaces/{wid}/reports/{rid}")
    def get_report(wid: str, rid: str):
        return app.state.store.report(wid, rid)

    @app.get("/api/v1/workspaces/{wid}/reports/{rid}/bookmarks/{bid}")
    def resolve_report_bookmark(wid: str, rid: str, bid: str, base_revision: int):
        from .core import resolve_stored_bookmark
        from .jobs import make_snapshot
        snapshot = make_snapshot(app.state.store,wid,rid,base_revision,{})
        view = resolve_stored_bookmark(snapshot["report"], bid, app.state.store.root, snapshot["datasets"],
            validation_cache=app.state.validation_cache, validation_scope=f"{wid}:{rid}")
        return {"revision":snapshot["revision"],"view":view}

    @app.get("/api/v1/workspaces/{wid}/reports/{rid}/publications")
    def published_reports(wid: str, rid: str):
        from .publications import list_publications
        return list_publications(app.state.store, wid, rid)

    @app.post("/api/v1/workspaces/{wid}/reports/{rid}/publications", status_code=202)
    def publish_report(wid: str, rid: str, body: PublishRequest):
        return app.state.jobs.submit_report(wid, rid, "publish", body.base_revision,
                                           {"visual_ids":[], "filters":[]}, body.idempotency_key)

    @app.get("/api/v1/workspaces/{wid}/reports/{rid}/publications/{pid}")
    def published_report(wid: str, rid: str, pid: str):
        from .publications import get_publication
        return get_publication(app.state.store, wid, rid, pid)

    @app.get("/api/v1/workspaces/{wid}/reports/{rid}/publications/{pid}/bookmarks/{bid}")
    def resolve_published_bookmark(wid: str, rid: str, pid: str, bid: str, base_revision: int):
        from .core import resolve_stored_bookmark
        from .publications import publication_snapshot
        with app.state.store.transaction() as db:
            snapshot = publication_snapshot(db,wid,rid,pid,base_revision,{})
        view = resolve_stored_bookmark(snapshot["report"], bid, app.state.store.root, snapshot["datasets"],
            validation_cache=app.state.validation_cache, validation_scope=f"{wid}:{rid}:publication:{pid}")
        return {"revision":snapshot["revision"],"view":view}

    @app.post("/api/v1/workspaces/{wid}/reports/{rid}/publications/{pid}/queries", status_code=202)
    def published_query(wid: str, rid: str, pid: str, body: QueryRequest):
        return app.state.jobs.submit_publication(wid, rid, pid, "query", body.base_revision,
                                                body.execution_options(), body.idempotency_key)

    @app.post("/api/v1/workspaces/{wid}/reports/{rid}/publications/{pid}/exports", status_code=202)
    def published_export(wid: str, rid: str, pid: str, body: ExportRequest):
        return app.state.jobs.submit_publication(wid, rid, pid, "export", body.base_revision,
                                                {**body.execution_options(),"format":body.format}, body.idempotency_key)

    @app.post("/api/v1/workspaces/{wid}/reports/{rid}/commands")
    def command(wid: str, rid: str, body: Command):
        from .core import command_contract_metadata, validate_stored_report
        def transform(current):
            loaded_contracts = None
            source_datasets = app.state.store.datasets(wid)
            bookmark_edit = None

            def contracts_for_command():
                nonlocal loaded_contracts
                if loaded_contracts is None:
                    loaded_contracts = command_contract_metadata(source_datasets)
                return loaded_contracts

            if body.command_type == "apply_proposal":
                job = app.state.jobs.get(body.payload.get("job_id", ""))
                if job["workspace_id"] != wid or job["kind"] != "assistant" or job["status"] != "succeeded":
                    raise AppError("INVALID_PROPOSAL", "提案不屬於此工作區或尚未完成。")
                result = job["result"]
                if result["base_revision"] != body.base_revision or not result["candidate_report"]:
                    raise AppError("REVISION_CONFLICT", "提案已過期或沒有可套用內容。", 409)
                candidate = result["candidate_report"]
                if candidate["audit"]["report_id"] != rid:
                    raise AppError("INVALID_PROPOSAL", "提案不屬於此報表。")
            elif body.command_type in {"add_filter","update_filter","delete_filter"}:
                from .filters import filter_command
                contracts = contracts_for_command()
                candidate = filter_command(current,body.command_type,body.payload,contracts)
            elif body.command_type in {"save_bookmark", "update_bookmark", "rename_bookmark", "delete_bookmark"}:
                from .bookmarks import bookmark_command
                if body.command_type in {"rename_bookmark", "delete_bookmark"}:
                    # These commands only alter bookmark metadata, even if a source is offline.
                    return bookmark_command(current, body.command_type, body.payload, {})
                from copy import deepcopy
                candidate = deepcopy(current)
                bookmark_edit = body.command_type, body.payload
            elif body.command_type in {"save_spc_analysis", "update_spc_analysis", "rename_spc_analysis", "delete_spc_analysis"}:
                from .spc import settings_command
                if body.command_type in {"rename_spc_analysis", "delete_spc_analysis"}:
                    return settings_command(current, body.command_type, body.payload, {})
                candidate = settings_command(current, body.command_type, body.payload, contracts_for_command())
            elif body.command_type in {"save_commonality_analysis", "update_commonality_analysis", "rename_commonality_analysis", "delete_commonality_analysis"}:
                from .commonality import settings_command
                if body.command_type in {"rename_commonality_analysis", "delete_commonality_analysis"}:
                    return settings_command(current, body.command_type, body.payload, {})
                candidate = settings_command(current, body.command_type, body.payload, contracts_for_command())
            elif body.command_type in {"save_crossfact_analysis", "update_crossfact_analysis", "rename_crossfact_analysis", "delete_crossfact_analysis"}:
                from .crossfact import settings_command
                if body.command_type in {"rename_crossfact_analysis", "delete_crossfact_analysis"}:
                    return settings_command(current, body.command_type, body.payload, {})
                candidate = settings_command(current, body.command_type, body.payload, contracts_for_command())
            elif body.command_type in {"save_change_analysis", "update_change_analysis", "rename_change_analysis", "delete_change_analysis"}:
                from .change_analysis import settings_command
                if body.command_type in {"rename_change_analysis", "delete_change_analysis"}:
                    return settings_command(current, body.command_type, body.payload, {})
                candidate = settings_command(current, body.command_type, body.payload, contracts_for_command())
            elif body.command_type in {"save_rfm_analysis", "update_rfm_analysis", "rename_rfm_analysis", "delete_rfm_analysis"}:
                from .rfm import settings_command
                if body.command_type in {"rename_rfm_analysis", "delete_rfm_analysis"}:
                    return settings_command(current, body.command_type, body.payload, {})
                candidate = settings_command(current, body.command_type, body.payload, contracts_for_command())
            elif body.command_type in {"save_scenario", "update_scenario", "rename_scenario", "apply_scenario", "delete_scenario"}:
                from .report_extensions import scenario_command
                candidate = scenario_command(current, body.command_type, body.payload)
            elif body.command_type == "duplicate_page":
                from .report_extensions import duplicate_page
                if set(body.payload) != {"page_id"}:
                    raise AppError("INVALID_PAGE", "頁面複製只接受來源頁面識別碼。")
                candidate = duplicate_page(current, body.payload["page_id"])
            else:
                candidate = body.payload.get("report")
            if not isinstance(candidate, dict):
                raise AppError("INVALID_REPORT", "缺少報表內容。")
            if candidate.get("read_only") != current.get("read_only"):
                raise AppError("INVALID_REPORT", "不可透過編輯命令改變唯讀狀態。")
            try:
                from .report_extensions import prune_removed_content
                candidate = prune_removed_content(candidate,current)
                return validate_stored_report(candidate, app.state.store.root, source_datasets, validation_cache=app.state.validation_cache,
                                       validation_scope=f"{wid}:{rid}", bookmark_edit=bookmark_edit)
            except AppError:
                raise
            except Exception as exc:
                raise AppError("INVALID_REPORT", "報表含有不合法欄位、指標或關聯。") from exc
        return app.state.store.command(wid, rid, body.model_dump(), transform)

    @app.post("/api/v1/workspaces/{wid}/reports/{rid}/queries", status_code=202)
    def query(wid: str, rid: str, body: QueryRequest):
        return app.state.jobs.submit_report(wid, rid, "query", body.base_revision,
                                           body.execution_options(), body.idempotency_key)

    @app.post("/api/v1/workspaces/{wid}/reports/{rid}/assistant", status_code=202)
    def assistant(wid: str, rid: str, body: AssistantRequest):
        if set(body.drill_state) - {body.selected_component_id}:
            raise AppError("INVALID_ASSISTANT_CONTEXT", "AI 鑽取路徑必須屬於選取圖表。")
        return app.state.jobs.submit_report(wid, rid, "assistant", body.base_revision,
                                           {"prompt": body.prompt, "selected_component_id": body.selected_component_id,
                                            "conversation": body.conversation,
                                            **({"drill_state":body.drill_state} if body.drill_state else {}),
                                            **({"filter_bookmark_id":body.filter_bookmark_id} if body.filter_bookmark_id is not None else {})}, body.idempotency_key)

    @app.post("/api/v1/workspaces/{wid}/reports/{rid}/analyses/spc", status_code=202)
    def spc(wid: str, rid: str, body: SpcRequest):
        from .spc import ANALYSIS_CONTRACT
        options = body.model_dump(exclude={"idempotency_key", "base_revision"})
        options["analysis_contract"] = ANALYSIS_CONTRACT
        return app.state.jobs.submit_report(wid, rid, "spc", body.base_revision, options, body.idempotency_key)

    @app.post("/api/v1/workspaces/{wid}/reports/{rid}/analyses/commonality", status_code=202)
    def commonality(wid: str, rid: str, body: CommonalityRequest):
        from .commonality import ANALYSIS_CONTRACT
        options = body.model_dump(exclude={"idempotency_key", "base_revision"})
        options["analysis_contract"] = ANALYSIS_CONTRACT
        return app.state.jobs.submit_report(wid, rid, "commonality", body.base_revision, options, body.idempotency_key)

    @app.post("/api/v1/workspaces/{wid}/reports/{rid}/analyses/crossfact", status_code=202)
    def crossfact(wid: str, rid: str, body: CrossFactRequest):
        from .crossfact import ANALYSIS_CONTRACT
        options = body.model_dump(exclude={"idempotency_key", "base_revision"})
        options["analysis_contract"] = ANALYSIS_CONTRACT
        return app.state.jobs.submit_report(wid, rid, "crossfact", body.base_revision, options, body.idempotency_key)

    @app.post("/api/v1/workspaces/{wid}/reports/{rid}/analyses/change", status_code=202)
    def change_analysis(wid: str, rid: str, body: ChangeRequest):
        from .change_analysis import ANALYSIS_CONTRACT
        options = body.model_dump(exclude={"idempotency_key", "base_revision"})
        options["analysis_contract"] = ANALYSIS_CONTRACT
        return app.state.jobs.submit_report(wid, rid, "change", body.base_revision, options, body.idempotency_key)

    @app.post("/api/v1/workspaces/{wid}/reports/{rid}/analyses/rfm", status_code=202)
    def rfm_analysis(wid: str, rid: str, body: RfmRequest):
        from .rfm import ANALYSIS_CONTRACT
        options = body.model_dump(exclude={"idempotency_key", "base_revision"})
        options["analysis_contract"] = ANALYSIS_CONTRACT
        return app.state.jobs.submit_report(wid, rid, "rfm", body.base_revision, options, body.idempotency_key)

    @app.post("/api/v1/workspaces/{wid}/reports/{rid}/summaries", status_code=202)
    def business_summary(wid: str, rid: str, body: SummaryRequest):
        options = body.model_dump(exclude={"idempotency_key", "base_revision"})
        return app.state.jobs.submit_report(wid, rid, "summary", body.base_revision, options, body.idempotency_key)

    @app.post("/api/v1/workspaces/{wid}/reports/{rid}/alerts", status_code=202)
    def evaluate_report_alerts(wid: str, rid: str, body: AlertEvaluationRequest):
        return app.state.jobs.submit_report(wid, rid, "alerts", body.base_revision,
                                            body.execution_options(), body.idempotency_key)

    @app.get("/api/v1/jobs/{jid}", response_model=JobView)
    def job(jid: str):
        return app.state.jobs.get(jid)

    @app.post("/api/v1/workspaces/{wid}/reports/{rid}/exports", status_code=202)
    def export(wid: str, rid: str, body: ExportRequest):
        return app.state.jobs.submit_report(wid, rid, "export", body.base_revision,
                                           {**body.execution_options(), "format": body.format}, body.idempotency_key)

    @app.get("/api/v1/artifacts/{aid}")
    def artifact(aid: str):
        job = app.state.jobs.get(aid)
        if job["kind"] != "export" or job["status"] != "succeeded":
            raise AppError("NOT_FOUND", "匯出尚未完成或不存在。", 404)
        result = job["result"]
        from .exports import export_suffix
        path = app.state.store.root / "workspaces" / job["workspace_id"] / "artifacts" / aid / ("export." + export_suffix(result["format"]))
        if not path.is_file():
            raise AppError("ARTIFACT_MISSING", "匯出檔已遺失，請重新產生。", 410)
        return FileResponse(path, filename=result["filename"],media_type="application/zip" if result["format"]=="csv" else None)

    @app.post("/api/v1/jobs/{jid}/cancel", response_model=JobView)
    def cancel(jid: str):
        return app.state.jobs.cancel(jid)

    @app.get("/api/v1/workspaces/{wid}/imports")
    def import_drafts(wid: str):
        return list_imports(app.state.store, wid)

    @app.post("/api/v1/workspaces/{wid}/imports")
    async def upload(wid: str, file: UploadFile = File()):
        data = await file.read(50_000_001)
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(create_import, app.state.store, wid, file.filename or "data.csv", data, ImportConfig().model_dump())

    @app.get("/api/v1/workspaces/{wid}/imports/{iid}")
    def import_draft(wid: str, iid: str):
        return get_import(app.state.store, wid, iid)

    @app.post("/api/v1/workspaces/{wid}/imports/{iid}/validate")
    def validate(wid: str, iid: str, body: ImportConfig):
        return validate_import(app.state.store, wid, iid, body.model_dump())

    @app.post("/api/v1/workspaces/{wid}/imports/{iid}/commit")
    def commit(wid: str, iid: str, body: ImportCommit):
        return commit_import(app.state.store, wid, iid, body.draft_revision, body.idempotency_key)

    @app.get("/{path:path}", include_in_schema=False)
    def ui(path: str):
        if path.startswith(("api/", "health/", "ready/")):
            raise AppError("NOT_FOUND", "找不到此 API。", 404)
        target = (static / path).resolve()
        if not target.is_relative_to(static.resolve()):
            raise AppError("NOT_FOUND", "找不到頁面。", 404)
        if target.is_file():
            return FileResponse(target)
        if path.startswith("assets/") or "." in Path(path).name:
            raise AppError("ASSET_NOT_FOUND", "靜態檔不存在，請重新整理或修復安裝。", 404)
        if (static / "index.html").is_file():
            return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})
        raise AppError("UI_NOT_BUILT", "React 介面尚未建置。", 503)

    return app
