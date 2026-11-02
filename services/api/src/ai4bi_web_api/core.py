"""Versioned facade around AI4BI. No Streamlit or desktop imports."""
from __future__ import annotations

import copy
from collections import OrderedDict
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from decimal import Decimal
import hashlib
import io
import json
import math
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd
from ai4bi.blocks.contracts import DataBlockContract
from ai4bi.query_spec import FilterSpec, FilterOperator
from ai4bi.report.models import ExecutableReportSpec, ReportChange, ReportProposal, apply_report_proposal
from .errors import AppError
from .validation_cache import QueryValidationCache
from .report_extensions import report_executor, preserve_extensions, ordered_report, extensions

# Enabled only by the disposable worker entry, never by the long-lived API.
# Core's public dataframe store is process-global and has no eviction API.
_worker_dataframe_sources = False
_worker_source_keys: OrderedDict[str, str] = OrderedDict()


def worker_source_key(raw: bytes, frame: pd.DataFrame) -> str | None:
    """Reuse only an index, after rechecking exact source bytes and frame equality."""
    from ai4bi.blocks.datastore import put_dataframe, get_dataframe
    source_hash = hashlib.sha256(raw).hexdigest()
    key = _worker_source_keys.get(source_hash)
    if key is not None:
        try:
            if get_dataframe(key).equals(frame):
                _worker_source_keys.move_to_end(source_hash)
                return key
        except KeyError:
            pass
        _worker_source_keys.pop(source_hash, None)
    key = put_dataframe(frame)
    # The pinned core's hash omits dtype identity. A collision or a mutated
    # cached frame must still fall back to the established inline cleaner.
    if not get_dataframe(key).equals(frame):
        return None
    _worker_source_keys[source_hash] = key
    while len(_worker_source_keys) > 32:
        _worker_source_keys.popitem(last=False)
    return key


def validation_digest(value):
    raw = json.dumps(clean(value, safe_ints=False), sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True, allow_nan=False).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def validation_contract_fingerprints(contracts):
    """Hash inline records in order without copying/serializing the whole table."""
    fingerprints = {}
    for key, contract in contracts.items():
        metadata = contract.model_dump(exclude={"data_source"})
        metadata["data_source"] = contract.data_source.model_dump(exclude={"records"})
        stream = hashlib.sha256(b"ai4bi-validation-contract-v1\0")
        stream.update(bytes.fromhex(validation_digest(metadata)))
        # Fixed-size digests preserve row boundaries, order, count and all values.
        # Only one row's cleaned JSON is temporary; no row digests are retained.
        for row in contract.data_source.records:
            stream.update(bytes.fromhex(validation_digest(row)))
        fingerprints[key] = stream.hexdigest()
    return fingerprints


def enable_worker_dataframe_sources():
    global _worker_dataframe_sources
    _worker_dataframe_sources = True


def dataframe_source_compatible(frame: pd.DataFrame) -> bool:
    """Only skip row cleaning when Arrow preserves its established semantics."""
    for column in frame.columns:
        series = frame[column]
        if pd.api.types.is_numeric_dtype(series.dtype):
            if series.isin([math.inf, -math.inf]).any():
                return False
        elif isinstance(series.dtype, pd.DatetimeTZDtype):
            # Legacy inline queries preserve the original ISO offset labels.
            return False
        elif pd.api.types.is_datetime64_any_dtype(series.dtype):
            continue
        elif pd.api.types.is_object_dtype(series.dtype) or pd.api.types.is_string_dtype(series.dtype):
            # Decimal and structured/mixed objects require the existing cleaner.
            if pd.api.types.infer_dtype(series, skipna=True) not in {"string", "unicode", "boolean", "empty"}:
                return False
        else:
            return False
    return True


def clean(value: Any, *, safe_ints: bool = True):
    # Exact types keep Enum and numpy scalar conversion on the established path.
    # Most table cells are already JSON primitives; avoid expensive reflection.
    kind = type(value)
    if value is None or kind is str or kind is bool:
        return value
    if kind is int:
        return str(value) if safe_ints and abs(value) > 2**53-1 else value
    if kind is float:
        return value if math.isfinite(value) else None
    if isinstance(value, pd.DataFrame):
        return {"columns": list(value.columns), "rows": clean(value.to_dict(orient="records"), safe_ints=safe_ints), "row_count": len(value)}
    if is_dataclass(value):
        return clean(asdict(value), safe_ints=safe_ints)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): clean(v, safe_ints=safe_ints) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v, safe_ints=safe_ints) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if value is pd.NA or value is pd.NaT:
        return None
    if hasattr(value, "tolist"):
        return clean(value.tolist(), safe_ints=safe_ints)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if safe_ints and isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53-1:
        return str(value)
    return value


def template(name: str):
    if name == "fab":
        from ai4bi.report.fab_template import build_fab_demo_report, fab_contracts
        report, contracts = build_fab_demo_report(), fab_contracts()
    elif name == "cv":
        from ai4bi.report.cv_dataset_template import build_cv_demo_report, cv_contracts
        report, contracts = build_cv_demo_report(), cv_contracts()
    else:
        from ai4bi.report.retail_template import build_retail_demo_report, build_retail_sales_block
        report = build_retail_demo_report()
        block = build_retail_sales_block()
        contracts = {block.block_id: block}
    result = report.to_dict()
    if name == "blank":
        for page in result["pages"].values():
            page["visuals"], page["visual_order"] = {}, []
        contracts = {}
        result["title"] = "我的分析報表"
    for page in result["pages"].values():
        for visual in page["visuals"].values():
            visual["col_span"] = 4 if visual["visualization"]["visual_type"] == "kpi_card" else 6
    return result, contracts


def load_contracts(root: Path, datasets: list[dict]) -> dict[str, DataBlockContract]:
    return _parse_contracts((item, _read_source(root, item)) for item in datasets)


def _read_source(root, item):
    if item["status"] != "ready":
        raise AppError("SOURCE_UNAVAILABLE", "資料尚未就緒或需要修復。", 409)
    path = (root / item["path"]).resolve()
    if not path.is_relative_to(root.resolve()):
        raise AppError("INVALID_PATH", "資料路徑不合法。")
    if not path.is_file():
        raise AppError("SOURCE_CORRUPT", "資料版本已變更或檔案損壞。", 409)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != item["version"]:
        raise AppError("SOURCE_CORRUPT", "資料版本已變更或檔案損壞。", 409)
    return raw


def _parse_contracts(verified_sources):
    contracts = {}
    for item, raw in verified_sources:
        contract = copy.deepcopy(item["contract"])
        # Parse the exact bytes whose digest was checked, not a second file read.
        frame = pd.read_parquet(io.BytesIO(raw))
        if _worker_dataframe_sources and dataframe_source_compatible(frame):
            key = worker_source_key(raw, frame)
            cached_matches = key is not None
        else:
            cached_matches = False
        if cached_matches:
            contract["data_source"] = {"source_type": "cached", "content_hash": key, "row_count": len(frame)}
        else:
            contract["data_source"] = {"source_type": "inline", "records": clean(frame.to_dict(orient="records"), safe_ints=False)}
        parsed = DataBlockContract.model_validate(contract)
        if parsed.block_id in contracts:
            raise AppError("DUPLICATE_BLOCK", "資料區塊版本有歧義。", 409)
        contracts[parsed.block_id] = parsed
    return contracts


def validate_report(body: dict, contracts: dict, *, validation_cache=None, validation_scope=""):
    return _validate_report(body, contracts, validation_cache=validation_cache,
                            validation_scope=validation_scope, fingerprint_contracts=validation_contract_fingerprints)


def command_contract_metadata(datasets):
    """Field-only views for command construction; never execute queries on these."""
    contracts = {}
    for item in datasets:
        metadata = copy.deepcopy(item["contract"])
        metadata["data_source"] = {"source_type": "inline", "records": []}
        contract = DataBlockContract.model_validate(metadata)
        if contract.block_id in contracts:
            raise AppError("DUPLICATE_BLOCK", "資料區塊版本有歧義。", 409)
        contracts[contract.block_id] = contract
    return contracts


def _bookmark_validation_options(sources, loader, cache, scope):
    return {"execution_loader": loader,
            "validation_cache": None if _worker_dataframe_sources else cache,
            "validation_context": validation_digest({"scope": scope, "sources": [
                {"version": item["version"], "contract": {
                    key: value for key, value in item["contract"].items() if key != "data_source"}}
                for item in sources]})}


def resolve_stored_bookmark(body, bookmark_id, root, datasets, *, validation_cache=None, validation_scope=""):
    """Verify snapshot bytes on every read; reuse only bounded execution proofs."""
    from .bookmarks import resolve_bookmark
    sources = copy.deepcopy(datasets)
    verified = [(item, _read_source(root, item)) for item in sources]
    contracts = command_contract_metadata(sources)
    return resolve_bookmark(body, bookmark_id, contracts, **_bookmark_validation_options(
        sources, lambda: _parse_contracts(verified), validation_cache, validation_scope))


def validate_stored_report(body: dict, root: Path, datasets: list[dict], *, validation_cache=None,
                           validation_scope="", bookmark_edit=None):
    """Verify bytes each request; decode only when actual execution is needed.

    Bytes and decoded contracts remain local. Only success digests survive the
    request, and process-local proofs cannot survive decoder/core upgrades.
    """
    sources = copy.deepcopy(datasets)
    verified = [(item, _read_source(root, item)) for item in sources]
    contracts = command_contract_metadata(sources)
    loaded = None
    execution = None

    def loaded_contracts():
        nonlocal loaded
        if loaded is None:
            loaded = _parse_contracts(verified)
        return loaded

    def execution_factory():
        nonlocal execution
        if execution is None:
            execution, _ = report_executor(body, loaded_contracts(), validate_calculations=True)
        return execution

    versions = {item["contract"]["block_id"]: item["version"] for item in sources}
    if bookmark_edit is not None:
        from .bookmarks import bookmark_command
        kind, payload = bookmark_edit
        if kind not in {"save_bookmark", "update_bookmark"}:
            raise AppError("INVALID_BOOKMARK", "不支援的書籤操作。")
        body = bookmark_command(body, kind, payload, contracts, **_bookmark_validation_options(
            sources, loaded_contracts, validation_cache, validation_scope))

    # Calculated metrics retain their unconditional real-data validation.
    if extensions(body).calculated_metrics:
        execution_factory()
    if not any(page.get("visuals") for page in body.get("pages", {}).values()):
        loaded_contracts()

    def fingerprints(enriched):
        return {key: validation_digest({"format": "verified-parquet-v2", "version": versions[key],
                    "contract": contract.model_dump(exclude={"data_source"}),
                    "source": contract.data_source.model_dump(exclude={"records"})})
                for key, contract in enriched.items()}

    return _validate_report(body, contracts,
                            validation_cache=None if _worker_dataframe_sources else validation_cache,
                            validation_scope=validation_scope, fingerprint_contracts=fingerprints,
                            execution_factory=execution_factory)


def _validate_report(body, contracts, *, validation_cache, validation_scope, fingerprint_contracts,
                     execution_factory=None):
    from .filters import validate_aggregate_filters
    validate_aggregate_filters(body)
    report = ExecutableReportSpec.from_dict(ordered_report(body))
    all_ids = []
    if len(report.pages) > 30:
        raise AppError("REPORT_LIMIT", "報表頁數超過上限。")
    for pid, page in report.pages.items():
        if pid != page.page_id or len(page.visual_order) != len(set(page.visual_order)):
            raise AppError("INVALID_REPORT", "頁面或圖表識別不一致。")
        for vid, visual in page.visuals.items():
            all_ids.append(vid)
            from .date_dimensions import validate_date_dimensions
            validate_date_dimensions(visual.query, contracts)
            if vid != visual.component_id or not 1 <= visual.col_span <= 12:
                raise AppError("INVALID_REPORT", "圖表識別或寬度不合法。")
            if not 120 <= visual.visualization.height_px <= 1600:
                raise AppError("INVALID_REPORT", "圖表高度必須在 120–1600 之間。")
            if not visual.query.metrics and visual.visualization.extra.get("chart_mode") != "histogram":
                raise AppError("INVALID_REPORT", "圖表至少需要一個指標。")
            if visual.visualization.extra.get("chart_mode") == "histogram":
                from .histogram import validate_histogram
                validate_histogram(visual.query, visual.visualization)
            if visual.visualization.visual_type.value == "kpi_card":
                from .kpi import validate_kpi
                validate_kpi(visual.visualization)
                from .comparison import validate_comparison
                validate_comparison(visual.query, visual.visualization, contracts)
                from .sparkline import validate_sparkline
                validate_sparkline(visual.query, visual.visualization, contracts)
            if any(ref.block_id not in contracts for ref in visual.query.block_refs):
                raise AppError("SOURCE_UNAVAILABLE", "報表使用了此工作區不存在的資料。")
    if len(all_ids) > 100 or len(set(all_ids)) != len(all_ids):
        raise AppError("INVALID_REPORT", "圖表數量超限或識別重複。")
    # Authoritative core validation: never accept arbitrary SQL or unregistered metrics.
    executor, enriched = report_executor(body, contracts, validate_calculations=execution_factory is None)
    proof_context = None
    if validation_cache is not None and all(item.data_source.source_type == "inline" for item in enriched.values()):
        # Includes actual verified records, schema, metrics, relationships and policies.
        # Cached/external core sources have a different lifetime and are not eligible.
        proof_context = validation_digest({"scope": validation_scope,
            "contracts": fingerprint_contracts(enriched),
            "parameters": extensions(body).parameters, "active_filters": report.merged_filters()})
    for page in report.pages.values():
        for visual in page.visuals.values():
            from .drilling import apply_drill
            query, _ = apply_drill(visual.query,visual.visualization,contracts)
            if visual.visualization.visual_type.value == "kpi_card" and visual.visualization.extra.get("compare_period"):
                from .comparison import validate_comparison, window_executor
                config = validate_comparison(query, visual.visualization, contracts)
                window_executor(executor, query, config, page.page_id, visual.component_id)
            def check():
                runner = execution_factory() if execution_factory is not None else executor
                runner.run(query, active_filters=report.merged_filters(),page_id=page.page_id,visual_id=visual.component_id)
            if proof_context is None:
                check()
            else:
                fingerprint = validation_digest({"context": proof_context, "query": query,
                    "conditions": [item.model_dump() for item in executor.applicable(query,page.page_id,visual.component_id)]})
                validation_cache.run(fingerprint, check)
    return preserve_extensions(report.to_dict(), body)


def run_query(root: Path, snapshot: dict) -> dict:
    from .publications import check_execution_runtime
    check_execution_runtime(root, snapshot)
    started = time.perf_counter()
    contracts = load_contracts(root, snapshot["datasets"])
    loaded = time.perf_counter()
    from .drilling import apply_drill, validate_snapshot
    validate_snapshot(snapshot)
    report = ExecutableReportSpec.from_dict(ordered_report(snapshot["report"]))
    executor, _ = report_executor(snapshot["report"], contracts)
    wanted = set(snapshot.get("visual_ids", []))
    from .bookmarks import exploration_page
    scoped_page = exploration_page(snapshot["report"], snapshot)
    results = {}
    query_times = {}
    for page in report.pages.values():
        for vid in page.visual_order:
            visual = page.visuals[vid]
            if wanted and vid not in wanted:
                continue
            query, drill = apply_drill(visual.query,visual.visualization,contracts,snapshot.get("drill_state",{}).get(vid))
            visual_started = time.perf_counter()
            try:
                for spec in snapshot.get("filters", []) if page.page_id == scoped_page else []:
                    if spec.get("source_visual_id") == vid:
                        continue
                    if spec["block_id"] in query.all_block_ids:
                        query.filters.append(FilterSpec(block_id=spec["block_id"], column_name=spec["column_name"],
                                                       operator=FilterOperator(spec["operator"]), value=spec.get("value")))
                comparison = None
                if visual.visualization.visual_type.value == "kpi_card" and visual.visualization.extra.get("compare_period") not in (None, ""):
                    from .comparison import compare_query
                    frame, metadata, comparison = compare_query(executor, query, visual.visualization, contracts,
                        active_filters=report.merged_filters(), page_id=page.page_id, visual_id=vid)
                else:
                    frame, metadata = executor.run_with_metadata(query, active_filters=report.merged_filters(),page_id=page.page_id,visual_id=vid)
                histogram = None
                if visual.visualization.extra.get("chart_mode") == "histogram":
                    from .histogram import histogram_result
                    frame, histogram = histogram_result(query, visual.visualization, frame)
                pivot = None
                if histogram is None and visual.visualization.visual_type.value == "pivot":
                    from .pivot import pivot_result
                    pivot = pivot_result(executor, query, visual.visualization, frame,
                                         active_filters=report.merged_filters(), page_id=page.page_id, visual_id=vid)
                from ai4bi.analysis.postprocess import apply_postprocess
                frame = apply_postprocess(frame, query, visual.visualization)
                limit = 5000
                results[vid] = {**clean(frame.head(limit)), "row_count": len(frame),
                                "truncated": len(frame) > limit, "metadata": clean(metadata),
                                "status": "ready"}
                results[vid]["query"] = clean(query)
                results[vid]["drill"] = drill
                if visual.visualization.visual_type.value == "kpi_card":
                    from .kpi import kpi_result
                    results[vid]["kpi"] = kpi_result(query, visual.visualization, results[vid]["rows"], truncated=results[vid]["truncated"])
                    if comparison is not None:
                        results[vid]["kpi"]["comparison"] = comparison
                    if visual.visualization.show_sparkline:
                        from .sparkline import sparkline_result
                        results[vid]["kpi"]["sparkline"] = sparkline_result(executor, query, visual.visualization, contracts,
                            active_filters=report.merged_filters(), page_id=page.page_id, visual_id=vid, comparison=comparison)
                if histogram is None and visual.visualization.visual_type.value in ("bar_chart", "line_chart"):
                    from .chart_format import chart_format
                    results[vid]["chart_format"] = chart_format(query, visual.visualization, results[vid]["rows"], truncated=results[vid]["truncated"])
                    if visual.visualization.visual_type.value == "bar_chart":
                        from .bar_chart import bar_result
                        bar = bar_result(query, visual.visualization, results[vid]["rows"])
                        results[vid]["bar"] = bar
                        position = visual.visualization.extra.get("legend_position")
                        results[vid]["chart_format"]["show_legend"] = position != "hide" and (bool(position) or (visual.visualization.show_legend and len(bar["series"]) > 1))
                if histogram is not None:
                    results[vid]["histogram"] = histogram
                if histogram is None and visual.visualization.visual_type.value == "map":
                    from .geo import geographic_result
                    results[vid]["geo"] = geographic_result(query, results[vid]["rows"])
                if histogram is None and visual.visualization.visual_type.value == "scatter":
                    from .scatter import scatter_result
                    results[vid]["scatter"] = scatter_result(query, visual.visualization, results[vid]["rows"], truncated=results[vid]["truncated"])
                if histogram is None and visual.visualization.visual_type.value == "pie_chart":
                    from .pie import pie_result
                    results[vid]["pie"] = pie_result(query, visual.visualization, results[vid]["rows"], truncated=results[vid]["truncated"])
                if pivot is not None:
                    results[vid]["pivot"] = pivot
                    results[vid]["truncated"] = results[vid]["truncated"] or pivot["truncated"]
            except Exception as exc:
                results[vid] = {"status": "error", "error": {"code": "QUERY_INVALID", "message": str(exc)[:500]}}
            finally:
                query_times[vid] = round((time.perf_counter() - visual_started) * 1000, 2)
    from .spc import run_saved_analyses
    spc_analyses = run_saved_analyses(snapshot, contracts) if snapshot.get("include_spc") else {}
    from .commonality import run_saved_analyses as run_commonality_analyses
    commonality_analyses = run_commonality_analyses(snapshot, contracts) if snapshot.get("include_commonality") else {}
    from .crossfact import run_saved_analyses as run_crossfact_analyses
    crossfact_analyses = run_crossfact_analyses(snapshot, contracts) if snapshot.get("include_crossfact") else {}
    from .change_analysis import run_saved_analyses as run_change_analyses
    change_analyses = run_change_analyses(snapshot, contracts) if snapshot.get("include_change") else {}
    from .rfm import run_saved_analyses as run_rfm_analyses
    rfm_analyses = run_rfm_analyses(snapshot, contracts) if snapshot.get("include_rfm") else {}
    return {"snapshot_id": snapshot["snapshot_id"], "revision": snapshot["revision"],
            "spc_analyses": spc_analyses, "commonality_analyses": commonality_analyses, "crossfact_analyses": crossfact_analyses, "change_analyses": change_analyses, "rfm_analyses": rfm_analyses,
            "execution_contract": snapshot["execution_contract"],
            "exploration_page_id":scoped_page,
            "filter_bookmark_id":snapshot.get("filter_bookmark_id"),
            "drill_state":snapshot.get("drill_state",{}),
            "timings_ms": {"load_datasets": round((loaded-started)*1000, 2), "visuals": query_times,
                           "query_total": round((time.perf_counter()-started)*1000, 2)},
            "data_versions": {d["dataset_id"]: d["version"] for d in snapshot["datasets"]},
            "visuals": results}


def explicit_rename(prompt: str, report: ExecutableReportSpec, selected: str | None):
    """Resolve an explicit edit before broad core analysis keywords such as overview."""
    from ai4bi.ai.intent_models import AIIntent, NL2ProposalResult
    match = re.fullmatch(
        r"\s*(?:rename\s+(?:this\s+)?chart\s+to\s+|(?:將|把)?(?:這個|此)?圖表(?:標題)?(?:改名為|改名成|改為|改成)\s*)(.+?)\s*",
        prompt, re.IGNORECASE,
    )
    if not match:
        return None
    title = re.sub(r"<[^>]+>", "", match[1]).strip().strip('"\'「」')[:80]
    found = next(((pid, p.visuals[selected]) for pid, p in report.pages.items() if selected in p.visuals), None)
    if not found or not title:
        return NL2ProposalResult(intent=AIIntent(intent_kind="unsupported", target_scope="report"),
                                 message="請先選取圖表，並提供新的圖表標題。")
    pid, visual = found
    proposal = ReportProposal(description=f"將圖表改名為「{title}」", target_component_id=selected,
        changes=[ReportChange(path=f"pages/{pid}/visuals/{selected}/visualization/title", label="圖表標題",
                              before=visual.visualization.title, after=title, affects_data=False)])
    return NL2ProposalResult(intent=AIIntent(intent_kind="style_change", target_scope=f"visual:{selected}"),
        message=f"已建立改名提案：{title}", proposal=proposal,
        trust_notes=["只修改標題；查詢與資料不變。"], risk_level="low")


def run_assistant(root: Path, snapshot: dict) -> dict:
    from .publications import check_execution_runtime
    check_execution_runtime(root, snapshot)
    import os
    from ai4bi.ai.nl2proposal import NL2ProposalService
    from .drilling import assistant_drill_executor, assistant_source_contracts, validate_snapshot
    if set(snapshot.get("drill_state",{})) - {snapshot.get("selected_component_id")}:
        raise AppError("INVALID_ASSISTANT_CONTEXT", "AI 鑽取路徑必須屬於選取圖表。")
    validate_snapshot(snapshot)
    contracts = load_contracts(root, snapshot["datasets"])
    report = ExecutableReportSpec.from_dict(ordered_report(snapshot["report"]))
    conversation = copy.deepcopy(snapshot.get("conversation", {}))
    source_contracts = contracts
    selected_page = next((pid for pid,p in snapshot["report"]["pages"].items() if snapshot.get("selected_component_id") in p["visuals"]),None)
    executor, contracts = report_executor(snapshot["report"], contracts,page_id=selected_page,
                                         visual_id=snapshot.get("selected_component_id") if selected_page else None)
    population_executor = executor
    executor, drill_context = assistant_drill_executor(executor,snapshot["report"],contracts,
        snapshot.get("selected_component_id"),snapshot.get("drill_state",{}))
    analysis_contracts = assistant_source_contracts(population_executor,contracts,drill_context)
    response = explicit_rename(snapshot["prompt"], report, snapshot.get("selected_component_id"))
    if response is None:
        response = NL2ProposalService().propose(snapshot["prompt"], report,
                                          snapshot.get("selected_component_id"),
                                          contracts=analysis_contracts, executor=executor,
                                          conversation_state=conversation)
    candidate = None
    if response.proposal:
        candidate = preserve_extensions(apply_report_proposal(report, response.proposal).to_dict(), snapshot["report"])
        if "report_persistent_filters" in snapshot:
            candidate["web_extensions"]["persistent_filters"] = copy.deepcopy(snapshot["report_persistent_filters"])
        validate_report(candidate, source_contracts)
    result = clean(response)
    result["candidate_report"] = candidate
    result["base_revision"] = snapshot["revision"]
    result["conversation"] = clean(conversation)
    result["configured_mode"] = os.environ.get("LLM_MODE", "mock")
    result["snapshot_id"] = snapshot["snapshot_id"]
    result["drill_context"] = drill_context
    return result
