"""Two-stage imports: complete validation before immutable publication."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd
from .errors import AppError
from .storage import Store, uid, encode


def parse_file(path: Path, name: str, config: dict) -> pd.DataFrame:
    import pandas as pd
    suffix = Path(name).suffix.lower()
    if suffix == ".csv":
        text = path.read_text(encoding=config["encoding"])
        header = next(csv.reader(io.StringIO(text), delimiter=config["delimiter"]), [])
        if not header or len(set(header)) != len(header) or any(not x.strip() for x in header):
            raise AppError("INVALID_COLUMNS", "CSV 欄位名稱不能空白或重複。")
        preserve_text = {column: "string" for column in header
                         if config["column_types"].get(column) == "string"
                         or (column not in config["column_types"] and re.search(r"(^id$|_id$|編號|識別)", column, re.I))}
        frame = pd.read_csv(io.StringIO(text), sep=config["delimiter"], low_memory=False, dtype=preserve_text)
    elif suffix == ".json":
        value = json.loads(path.read_text(encoding=config["encoding"]))
        if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
            raise AppError("INVALID_JSON", "JSON 必須是由資料列物件組成的陣列。")
        frame = pd.DataFrame(value)
    elif suffix in (".xlsx", ".xls"):
        preserve_text = {column: "string" for column, dtype in config["column_types"].items() if dtype == "string"}
        frame = pd.read_excel(path, sheet_name=config["sheet"], dtype=preserve_text)
    else:
        raise AppError("UNSUPPORTED_FILE", "支援 CSV、JSON、XLSX 與 XLS。")
    frame.columns = [str(c) for c in frame.columns]
    if frame.empty or len(frame) > 1_000_000 or len(frame.columns) > 200:
        raise AppError("DATA_LIMIT", "資料必須有內容，且最多 100 萬列、200 欄。")
    if len(set(frame.columns)) != len(frame.columns) or "__row_count" in frame.columns:
        raise AppError("INVALID_COLUMNS", "欄位重複或使用了保留名稱。")
    for column, dtype in config["column_types"].items():
        if column not in frame:
            raise AppError("COLUMN_MISSING", f"找不到欄位：{column}")
        try:
            if dtype == "string":
                frame[column] = frame[column].astype("string")
            elif dtype in ("integer", "number"):
                frame[column] = pd.to_numeric(frame[column], errors="raise")
                if dtype == "integer":
                    frame[column] = frame[column].astype("Int64")
            else:
                frame[column] = pd.to_datetime(frame[column], errors="raise", format="ISO8601")
        except (ValueError, TypeError) as exc:
            raise AppError("INVALID_COLUMN_VALUE", f"欄位「{column}」存在無法轉為 {dtype} 的值；未匯入任何資料。") from exc
    return frame


def infer_contract(frame: pd.DataFrame, block_id: str, name: str):
    import pandas as pd
    from ai4bi.blocks.contracts import (DataBlockContract, BlockType, ColumnSchema,
                                      MetricDefinition, DisaggregationMethod, InlineDataSource)
    columns, metrics = [], []
    for column in frame:
        series = frame[column]
        dtype = "string"
        if pd.api.types.is_datetime64_any_dtype(series):
            dtype = "timestamp"
        elif pd.api.types.is_numeric_dtype(series):
            dtype = "float" if pd.api.types.is_float_dtype(series) else "integer"
            if not re.search(r"(^id$|_id$|編號|識別)", column, re.I):
                ratio = bool(re.search(r"(rate|ratio|pct|percent|率|比例)", column, re.I))
                method = DisaggregationMethod.average if ratio else DisaggregationMethod.sum
                metrics.append(MetricDefinition(name=column, formula=f'{"AVG" if ratio else "SUM"}("{column.replace(chr(34), chr(34)*2)}")',
                                                disaggregation_method=method,
                                                description="平均值；如需加權比率請定義分子／分母" if ratio else "加總"))
        columns.append(ColumnSchema(name=column, data_type=dtype))
    frame["__row_count"] = 1
    columns.append(ColumnSchema(name="__row_count", data_type="integer"))
    metrics.append(MetricDefinition(name="__row_count", formula="SUM(__row_count)",
                                    disaggregation_method=DisaggregationMethod.sum, description="資料筆數"))
    return DataBlockContract(block_id=block_id, block_type=BlockType.fact, grain="one imported source row",
                             description=name, columns=columns, metrics=metrics,
                             data_source=InlineDataSource(records=[])).model_dump(mode="json")


def list_imports(store: Store, wid: str):
    store.get_workspace(wid)
    with store.connect() as db:
        return [{"import_id": row["id"], "name": row["name"], "revision": row["revision"], "status": row["status"]}
                for row in db.execute("SELECT id,name,revision,status FROM imports WHERE wid=? AND status!='committed' ORDER BY rowid DESC", (wid,))]


def get_import(store: Store, wid: str, iid: str):
    with store.connect() as db:
        row = db.execute("SELECT * FROM imports WHERE id=? AND wid=?", (iid, wid)).fetchone()
    if not row:
        raise AppError("NOT_FOUND", "找不到匯入草稿。", 404)
    return {"import_id": iid, "workspace_id": wid, "revision": row["revision"], "name": row["name"],
            "status": row["status"], "config": json.loads(row["config"]), "details": json.loads(row["details"])}


def validate_import(store: Store, wid: str, iid: str, config: dict):
    # Validation and confirmation must observe one draft revision under the same lock.
    from filelock import FileLock
    get_import(store, wid, iid)
    folder = store.root / "staging" / "imports" / iid
    with FileLock(folder / "commit.lock"):
        return _validate_import_locked(store, wid, iid, config)


def _validate_import_locked(store: Store, wid: str, iid: str, config: dict):
    with store.connect() as db:
        row = db.execute("SELECT * FROM imports WHERE id=? AND wid=?", (iid, wid)).fetchone()
    if not row:
        raise AppError("NOT_FOUND", "找不到匯入草稿。", 404)
    if row["status"] == "committed":
        raise AppError("IMPORT_COMMITTED", "此資料已發布，請建立新的匯入。", 409)
    try:
        frame = parse_file(store.root / row["source"], row["name"], config)
        from .core import clean
        details = {**clean(frame.head(100)), "row_count": len(frame),
                   "columns": [{"name": col, "dtype": str(frame[col].dtype),
                                "null_count": int(frame[col].isna().sum())} for col in frame],
                   "full_validation": True}
        status = "validated"
    except Exception as exc:
        details = {"error": getattr(exc, "message", "無法解析檔案，請確認編碼、工作表及格式。"), "full_validation": False}
        status = "invalid"
    with store.transaction() as db:
        db.execute("UPDATE imports SET revision=revision+1,config=?,details=?,status=? WHERE id=? AND status!='committed'",
                   (encode(config), encode(details), status, iid))
    return get_import(store, wid, iid)


def create_import(store: Store, wid: str, name: str, data: bytes, config: dict):
    store.get_workspace(wid)
    if not data or len(data) > 50_000_000:
        raise AppError("UPLOAD_LIMIT", "檔案需有內容，且大小不可超過 50 MB。", 413)
    iid = uid()
    folder = store.root / "staging" / "imports" / iid
    folder.mkdir(parents=True)
    path = folder / ("source" + Path(name).suffix.lower())
    path.write_bytes(data)
    with store.transaction() as db:
        db.execute("INSERT INTO imports VALUES(?,?,1,?,?,?,'pending','{}')",
                   (iid, wid, Path(name).name, str(path.relative_to(store.root)), encode(config)))
    return validate_import(store, wid, iid, config)


def commit_import(store: Store, wid: str, iid: str, revision: int, key: str):
    # Serialized by a per-import file lock across confirmation requests.
    from filelock import FileLock
    get_import(store, wid, iid)  # Validate ownership before constructing any writable path.
    folder = store.root / "staging" / "imports" / iid
    if not folder.is_dir():
        raise AppError("NOT_FOUND", "找不到匯入草稿。", 404)
    with FileLock(folder / "commit.lock"):
        with store.connect() as db:
            previous = db.execute("SELECT hash,response FROM dedup WHERE scope=? AND key=?", (f"import:{wid}:{iid}", key)).fetchone()
        from .storage import digest
        payload = {"revision": revision}
        if previous:
            if previous["hash"] != digest(payload):
                raise AppError("IDEMPOTENCY_CONFLICT", "請求內容不一致。", 409)
            return json.loads(previous["response"])
        draft = get_import(store, wid, iid)
        if draft["revision"] != revision or draft["status"] != "validated":
            raise AppError("IMPORT_NOT_VALIDATED", "請先完成目前版本的完整驗證。", 409)
        with store.connect() as db:
            row = db.execute("SELECT source FROM imports WHERE id=? AND wid=?", (iid, wid)).fetchone()
        frame = parse_file(store.root / row["source"], draft["name"], draft["config"])
        contract = infer_contract(frame, "upload_" + iid[:12], draft["name"])
        # Stable ID lets a post-publication retry reconcile an interrupted confirmation.
        existing = next((d for d in store.datasets(wid) if d["dataset_id"] == iid), None)
        if existing is None:
            store.publish_dataset(wid, contract, frame, iid)
        elif existing["status"] != "ready":
            raise AppError("SOURCE_UNAVAILABLE", "資料發布需要恢復。", 409)
        with store.transaction() as db:
            def action():
                db.execute("UPDATE imports SET status='committed' WHERE id=?", (iid,))
                return {"dataset_id": iid, "block_id": contract["block_id"], "workspace_id": wid}
            return store.idempotent(db, f"import:{wid}:{iid}", key, payload, action)
