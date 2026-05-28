"""External Database Connector Panel — Round 043.

Allows users to connect to external data sources without writing code.
Supported connectors:
  - DuckDB file (.duckdb / .db) — local, no credentials needed
  - SQLite file (.sqlite / .db) — local, no credentials needed
  - PostgreSQL — host/port/dbname/user/password
  - CSV/Parquet URL — remote file over HTTPS

When connected, the user selects a table → the system generates a
DataBlockContract with ExternalDataSource pointing to the connection,
then registers it so NL2/executor can query it.

For the MVP, we execute the actual query via DuckDB's native connectors
and cache the result as an InlineDataSource (up to 50K rows), which is the
most compatible path with the current executor architecture.
"""

from __future__ import annotations

import io
from typing import Optional

import streamlit as st

from ai4bi.blocks.contracts import (
    BlockType, ColumnSchema, DataBlockContract, DataClassification,
    DisaggregationMethod, InlineDataSource, LifecycleStatus, MetricDefinition, PolicySpec,
)
from ai4bi.ui.upload import _USER_BLOCKS_KEY, _USER_BLOCK_META_KEY, _PENDING_NEW_BLOCK_KEY, infer_block, _slugify

_CONN_STATE_KEY = "db_connections"
_MAX_ROWS = 50_000


def _execute_duckdb_query(conn_info: dict, query: str) -> "pd.DataFrame":
    """Execute a query using DuckDB and return a DataFrame."""
    import duckdb
    import pandas as pd

    conn_type = conn_info.get("type")
    if conn_type == "duckdb_file":
        conn = duckdb.connect(conn_info["path"], read_only=True)
        return conn.execute(query).df()
    elif conn_type == "sqlite":
        conn = duckdb.connect(":memory:")
        conn.execute(f"INSTALL sqlite; LOAD sqlite;")
        conn.execute(f"ATTACH '{conn_info['path']}' (TYPE sqlite, READ_ONLY);")
        return conn.execute(query).df()
    elif conn_type == "postgresql":
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL postgres; LOAD postgres;")
        pg_dsn = (
            f"host={conn_info['host']} port={conn_info['port']} "
            f"dbname={conn_info['dbname']} user={conn_info['user']} "
            f"password={conn_info['password']}"
        )
        conn.execute(f"ATTACH '{pg_dsn}' AS pg (TYPE postgres, READ_ONLY);")
        return conn.execute(query).df()
    elif conn_type == "url":
        conn = duckdb.connect(":memory:")
        url = conn_info["url"]
        if url.endswith(".parquet"):
            return conn.execute(f"SELECT * FROM read_parquet('{url}') LIMIT {_MAX_ROWS}").df()
        else:
            return conn.execute(f"SELECT * FROM read_csv('{url}') LIMIT {_MAX_ROWS}").df()
    raise ValueError(f"Unknown connector type: {conn_type}")


def _list_tables(conn_info: dict) -> list[str]:
    """List available tables from a connection."""
    import duckdb
    try:
        conn_type = conn_info.get("type")
        if conn_type == "duckdb_file":
            conn = duckdb.connect(conn_info["path"], read_only=True)
            return [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
        elif conn_type == "sqlite":
            conn = duckdb.connect(":memory:")
            conn.execute("INSTALL sqlite; LOAD sqlite;")
            conn.execute(f"ATTACH '{conn_info['path']}' (TYPE sqlite, READ_ONLY);")
            tables = conn.execute("SHOW ALL TABLES").fetchdf()
            return tables["name"].tolist() if not tables.empty else []
        elif conn_type == "postgresql":
            conn = duckdb.connect(":memory:")
            conn.execute("INSTALL postgres; LOAD postgres;")
            pg_dsn = (
                f"host={conn_info['host']} port={conn_info['port']} "
                f"dbname={conn_info['dbname']} user={conn_info['user']} "
                f"password={conn_info['password']}"
            )
            conn.execute(f"ATTACH '{pg_dsn}' AS pg (TYPE postgres, READ_ONLY);")
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            ).fetchdf()
            return tables["table_name"].tolist() if not tables.empty else []
    except Exception as exc:  # noqa: BLE001
        st.error(f"連線錯誤：{exc}")
    return []


def render_connector_panel() -> None:
    """Render the Database Connector expander — Round 043."""
    with st.expander("🔌 連接外部資料庫", expanded=False):
        st.caption(
            "直接連接資料庫，將資料表匯入為可分析的資料集。\n"
            "支援：本機 DuckDB / SQLite 檔案、PostgreSQL、遠端 CSV/Parquet URL。"
        )

        # Connection type selection
        conn_type = st.selectbox(
            "連線類型",
            ["duckdb_file", "sqlite", "postgresql", "url"],
            format_func=lambda t: {
                "duckdb_file": "DuckDB 本機檔案 (.duckdb)",
                "sqlite": "SQLite 本機檔案 (.sqlite)",
                "postgresql": "PostgreSQL 伺服器",
                "url": "遠端 CSV / Parquet URL",
            }[t],
            key="conn_type_sel",
        )

        conn_info: dict = {"type": conn_type}

        if conn_type in ("duckdb_file", "sqlite"):
            path = st.text_input("檔案路徑", placeholder="C:/data/my_db.duckdb", key="conn_path")
            conn_info["path"] = path
        elif conn_type == "postgresql":
            col1, col2 = st.columns([3, 1])
            with col1:
                conn_info["host"] = st.text_input("主機", value="localhost", key="pg_host")
                conn_info["dbname"] = st.text_input("資料庫名稱", key="pg_dbname")
                conn_info["user"] = st.text_input("使用者名稱", key="pg_user")
            with col2:
                conn_info["port"] = st.text_input("埠號", value="5432", key="pg_port")
                conn_info["password"] = st.text_input("密碼", type="password", key="pg_pw")
        elif conn_type == "url":
            conn_info["url"] = st.text_input(
                "URL",
                placeholder="https://example.com/data.parquet",
                key="conn_url",
            )

        if st.button("🔍 列出資料表", key="conn_list_tables"):
            tables = _list_tables(conn_info)
            if tables:
                st.session_state["_conn_tables"] = tables
                st.session_state["_conn_info"] = conn_info
                st.success(f"找到 {len(tables)} 個資料表。")
            else:
                st.warning("未找到任何資料表，請確認連線設定。")

        # Table picker
        tables = st.session_state.get("_conn_tables", [])
        stored_conn = st.session_state.get("_conn_info", {})
        if tables:
            selected_table = st.selectbox(
                "選擇要匯入的資料表",
                tables,
                key="conn_table_sel",
            )
            preview_limit = 1000
            if st.button("⬆️ 匯入此資料表", key="conn_import_btn", type="primary"):
                with st.spinner(f"正在從資料庫讀取 {selected_table}（最多 {_MAX_ROWS:,} 行）..."):
                    try:
                        query = f'SELECT * FROM "{selected_table}" LIMIT {_MAX_ROWS}'
                        df = _execute_duckdb_query(stored_conn, query)
                        if df.empty:
                            st.warning("資料表是空的。")
                            return
                        block_id = _slugify(selected_table) or "db_table"
                        contract, metric_names, dim_names = infer_block(df, block_id, selected_table)
                        if _USER_BLOCKS_KEY not in st.session_state:
                            st.session_state[_USER_BLOCKS_KEY] = {}
                        if _USER_BLOCK_META_KEY not in st.session_state:
                            st.session_state[_USER_BLOCK_META_KEY] = {}
                        st.session_state[_USER_BLOCKS_KEY][block_id] = contract
                        st.session_state[_USER_BLOCK_META_KEY][block_id] = {
                            "metric_names": metric_names,
                            "dim_names": dim_names,
                            "display_name": selected_table,
                            "row_count": len(df),
                            "source": conn_type,
                        }
                        st.session_state[_PENDING_NEW_BLOCK_KEY] = block_id
                        st.success(
                            f"✅ 已匯入「{selected_table}」（{len(df):,} 行，"
                            f"{len(metric_names)} 個指標，{len(dim_names)} 個維度）"
                        )
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"匯入失敗：{exc}")
