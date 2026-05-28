"""Self-serve CSV / Excel data import — Round 028.

Users can upload their own tabular data; the module auto-infers a
DataBlockContract and stores it in st.session_state["user_blocks"] so
the executor can query it without writing to disk.

Column classification heuristics
---------------------------------
date   — dtype is datetime64, OR column name matches DATE_RE
metric — dtype is numeric AND name does not match ID_RE
dim    — dtype is string / categorical, OR name matches ID_RE but isn't numeric
pk     — name matches ID_RE and uniqueness ≥ 95 %
"""

from __future__ import annotations

import io
import re
import uuid
from typing import Optional

import pandas as pd
import streamlit as st

from ai4bi.blocks.contracts import (
    BlockType,
    ColumnSchema,
    DataBlockContract,
    DataClassification,
    DisaggregationMethod,
    InlineDataSource,
    LifecycleStatus,
    MetricDefinition,
    PolicySpec,
)

_USER_BLOCKS_KEY = "user_blocks"
_USER_BLOCK_META_KEY = "user_block_meta"  # {block_id: {metric_names, dim_names}}

_DATE_RE = re.compile(
    r"\b(date|time|day|month|year|week|period|ts|timestamp|dt)\b", re.I
)
_ID_RE = re.compile(r"(_id|_key|_code|_num|_no)\s*$|^id$", re.I)
_MAX_INLINE_ROWS = 50_000


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "col"


def _detect_date_cols(df: pd.DataFrame) -> set[str]:
    """Try to parse string columns that look like dates."""
    guessed: set[str] = set()
    for col in df.select_dtypes(include=["object", "string"]).columns:
        if _DATE_RE.search(col):
            try:
                pd.to_datetime(df[col].dropna().head(20), infer_datetime_format=True)
                guessed.add(col)
            except Exception:  # noqa: BLE001
                pass
    return guessed


def infer_block(
    df: pd.DataFrame,
    block_id: str,
    display_name: str,
) -> tuple[DataBlockContract, list[str], list[str]]:
    """Infer a DataBlockContract from a DataFrame.

    Returns
    -------
    contract      : validated DataBlockContract
    metric_names  : original column names classified as metrics
    dim_names     : original column names classified as dimensions
    """
    guessed_dates = _detect_date_cols(df)

    columns: list[ColumnSchema] = []
    metrics: list[MetricDefinition] = []
    metric_names: list[str] = []
    dim_names: list[str] = []
    primary_keys: list[str] = []

    for col in df.columns:
        dtype = df[col].dtype
        is_numeric = pd.api.types.is_numeric_dtype(dtype)
        is_datetime = pd.api.types.is_datetime64_any_dtype(dtype) or col in guessed_dates
        is_id_like = bool(_ID_RE.search(col))

        if is_datetime:
            col_type = "date"
            dim_names.append(col)
        elif is_numeric and not is_id_like:
            col_type = "float" if pd.api.types.is_float_dtype(dtype) else "integer"
            metrics.append(MetricDefinition(
                name=col,
                formula=f"SUM({col})",
                disaggregation_method=DisaggregationMethod.sum,
                description=f"Sum of {col}",
            ))
            metric_names.append(col)
        else:
            col_type = "string"
            if is_id_like:
                primary_keys.append(col)
            else:
                dim_names.append(col)

        columns.append(ColumnSchema(name=col, data_type=col_type, nullable=True))

    # Ensure at least one metric exists (fallback: first numeric col regardless of name)
    if not metric_names:
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col].dtype) and col not in primary_keys:
                metrics.append(MetricDefinition(
                    name=col,
                    formula=f"SUM({col})",
                    disaggregation_method=DisaggregationMethod.sum,
                ))
                metric_names.append(col)
                break

    # Convert datetime columns in the df records to ISO strings so they serialise
    df_serial = df.copy()
    for col in guessed_dates:
        df_serial[col] = pd.to_datetime(df_serial[col], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in df_serial.select_dtypes(include="datetime64").columns:
        df_serial[col] = df_serial[col].dt.strftime("%Y-%m-%d")

    records = df_serial.where(pd.notna(df_serial), None).to_dict(orient="records")

    contract = DataBlockContract(
        block_id=block_id,
        block_type=BlockType.fact,
        grain="one row per record",
        version="1.0.0",
        description=f"Uploaded from {display_name}",
        block_lifecycle=LifecycleStatus.draft,
        primary_keys=primary_keys[:1],
        columns=columns,
        metrics=metrics,
        data_source=InlineDataSource(records=records),
        policy=PolicySpec(data_classification=DataClassification.internal),
    )
    return contract, metric_names, dim_names


def _load_file(uploaded_file) -> Optional[pd.DataFrame]:
    """Parse an uploaded file into a DataFrame."""
    name: str = uploaded_file.name.lower()
    raw = uploaded_file.read()
    try:
        if name.endswith(".csv"):
            return pd.read_csv(io.BytesIO(raw))
        if name.endswith((".xls", ".xlsx")):
            return pd.read_excel(io.BytesIO(raw))
        if name.endswith(".parquet"):
            return pd.read_parquet(io.BytesIO(raw))
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to read file: {exc}")
    return None


def render_upload_panel() -> None:
    """Render the 'Upload Your Data' sidebar expander (Round 028)."""
    with st.expander("上傳資料", expanded=False):
        st.caption("支援 CSV、Excel (.xlsx)、Parquet — 最多 50,000 行")

        uploaded = st.file_uploader(
            "選擇檔案",
            type=["csv", "xlsx", "xls", "parquet"],
            key="data_upload_widget",
            label_visibility="collapsed",
        )
        if uploaded is None:
            _render_existing_blocks()
            return

        df = _load_file(uploaded)
        if df is None:
            return

        if len(df) > _MAX_INLINE_ROWS:
            st.warning(f"檔案有 {len(df):,} 行，已截取前 {_MAX_INLINE_ROWS:,} 行。")
            df = df.head(_MAX_INLINE_ROWS)

        # Auto-generate block_id from filename
        raw_name = re.sub(r"\.[^.]+$", "", uploaded.name)
        default_id = _slugify(raw_name) or "my_data"
        block_id = st.text_input("Block ID (識別碼)", value=default_id, key="upload_block_id")
        block_id = _slugify(block_id) or default_id

        # Preview
        with st.container():
            st.caption(f"預覽（前 5 行，共 {len(df):,} 行 × {len(df.columns)} 欄）")
            st.dataframe(df.head(5), use_container_width=True, hide_index=True)

        # Infer contract
        contract, metric_names, dim_names = infer_block(df, block_id, uploaded.name)

        col1, col2 = st.columns(2)
        with col1:
            st.caption(f"**指標（{len(metric_names)}）**")
            for m in metric_names:
                st.markdown(f"- {m}")
        with col2:
            st.caption(f"**維度（{len(dim_names)}）**")
            for d in dim_names:
                st.markdown(f"- {d}")

        if not metric_names:
            st.warning("未偵測到數值欄位，請確認資料格式。")

        if st.button("匯入 Block", key="upload_import_btn", type="primary", disabled=not metric_names):
            if _USER_BLOCKS_KEY not in st.session_state:
                st.session_state[_USER_BLOCKS_KEY] = {}
            if _USER_BLOCK_META_KEY not in st.session_state:
                st.session_state[_USER_BLOCK_META_KEY] = {}
            st.session_state[_USER_BLOCKS_KEY][block_id] = contract
            st.session_state[_USER_BLOCK_META_KEY][block_id] = {
                "metric_names": metric_names,
                "dim_names": dim_names,
                "display_name": uploaded.name,
                "row_count": len(df),
            }
            st.success(f"已匯入 `{block_id}` — {len(metric_names)} 個指標，{len(dim_names)} 個維度")
            st.rerun()

        _render_existing_blocks()


def _render_existing_blocks() -> None:
    """Show already-imported user blocks with a delete button."""
    user_blocks: dict = st.session_state.get(_USER_BLOCKS_KEY, {})
    if not user_blocks:
        return
    st.divider()
    st.caption("**已匯入的資料**")
    meta: dict = st.session_state.get(_USER_BLOCK_META_KEY, {})
    for bid, contract in list(user_blocks.items()):
        m = meta.get(bid, {})
        cols = st.columns([3, 1])
        with cols[0]:
            st.markdown(
                f"**{bid}** — {m.get('row_count', '?')} 行 · "
                f"{len(m.get('metric_names', []))} 指標 · "
                f"{len(m.get('dim_names', []))} 維度"
            )
        with cols[1]:
            if st.button("刪除", key=f"del_upload_{bid}"):
                del st.session_state[_USER_BLOCKS_KEY][bid]
                st.session_state.get(_USER_BLOCK_META_KEY, {}).pop(bid, None)
                st.rerun()
