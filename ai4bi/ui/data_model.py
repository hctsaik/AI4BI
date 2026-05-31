"""Data Model UI — Round 037/038.

Round 037: Join Builder — lets users connect two uploaded CSV tables by
           selecting a common key column, creating a governed relationship
           stored in session_state["user_semantic_model"].

Round 038: Data Model View — visual table/column browser showing all loaded
           blocks and their declared relationships.

These two features unlock Power BI's core "Relationships" panel, enabling:
- Cross-table visuals (revenue from sales_data, NPS from nps_data)
- Governed joins validated by SafeJoinPlanner
- Visual exploration of the data model before building reports
"""

from __future__ import annotations

import re
from typing import Optional

import streamlit as st

from ai4bi.blocks.contracts import BlockType, DataBlockContract
from ai4bi.ui.upload import _USER_BLOCKS_KEY, _USER_BLOCK_META_KEY

_USER_SEMANTIC_MODEL_KEY = "user_semantic_model"

_SOURCE_BADGE = {
    "duckdb": "🦆 DuckDB", "sqlite": "💾 SQLite", "postgres": "🐘 Postgres",
    "postgresql": "🐘 Postgres", "url": "🌐 URL",
}


def _user_loaded_blocks() -> dict[str, DataBlockContract]:
    """Round 156: genuinely user-loaded sources (upload / DB import carry a meta
    entry). Excludes demo blocks seeded into user_blocks, so join/data-model show
    your data — not retail leftovers when you're on another report."""
    meta = st.session_state.get(_USER_BLOCK_META_KEY, {})
    all_blocks = st.session_state.get(_USER_BLOCKS_KEY, {})
    return {bid: c for bid, c in all_blocks.items() if bid in meta}


def _friendly_time(ts: "str | None") -> "str | None":
    """Format a stored 'YYYY-MM-DD HH:MM' upload time as 今天/昨天/日期."""
    if not ts:
        return None
    try:
        import datetime as _dt
        dt = _dt.datetime.strptime(ts, "%Y-%m-%d %H:%M")
        today = _dt.date.today()
        if dt.date() == today:
            return f"今天 {dt:%H:%M}"
        if dt.date() == today - _dt.timedelta(days=1):
            return f"昨天 {dt:%H:%M}"
        return ts
    except Exception:  # noqa: BLE001
        return ts


def render_data_source_manager(report_sources: "dict | None" = None) -> None:
    """Round 147 / 166: unified data-source manager — one list of EVERY source
    powering the current report, so the user can always see how many there are.

    Shows two groups:
      * 內建／示範資料 — blocks the current report uses that the user didn't upload
        (e.g. the retail / semiconductor demo). Read-only (they ARE the report).
      * 你載入的資料 — files/DB imports the user added (meta-tracked, removable).

    ``report_sources`` is ``{block_id: contract}`` for the blocks the current
    report references (passed from app._report_block_contracts). When omitted we
    fall back to just the user-loaded sources (old behaviour).
    """
    meta: dict = st.session_state.get(_USER_BLOCK_META_KEY, {})
    uploads = _user_loaded_blocks()  # genuinely user-loaded (meta-tracked)
    report_sources = dict(report_sources or {})
    # built-in / demo = report blocks the user didn't upload themselves
    builtin = {bid: c for bid, c in report_sources.items() if bid not in meta}

    total = len(builtin) + len(uploads)
    if total == 0:
        st.info(
            "目前沒有資料來源。用下方「上傳檔案」或「連接資料庫」加入第一份資料；"
            "加入 2 份以上後，可到 **🔗 模型** 模式把它們關聯起來。",
            icon="📂",
        )
        return

    n_rel = len(get_user_semantic_model().get("relationships", []))
    # Round 167: total rows is metadata-only (CachedDataSource.row_count) — we
    # never load or scan any frame just to summarize.
    from ai4bi.blocks.datastore import source_row_count
    from ai4bi.ui.data_inspector import render_source_inspector
    total_rows, any_known = 0, False
    for c in list(builtin.values()) + list(uploads.values()):
        rc = source_row_count(c)
        if rc is not None:
            total_rows += rc
            any_known = True
    rows_txt = f" · 約 {total_rows:,} 列" if any_known else ""
    st.caption(f"**這份報表使用 {total} 個資料來源 · {n_rel} 個關聯{rows_txt}**")
    st.caption("展開任一來源即可看欄位結構（schema）；資料預覽採**取樣、需手動展開**,大型資料不會整表載入或掃描。")

    # ── built-in / demo sources (read-only) ─────────────────────────────
    if builtin:
        st.markdown("**📊 內建／示範資料**")
        for bid, contract in builtin.items():
            label = getattr(contract, "description", None) or bid
            render_source_inspector(contract, display_name=label,
                                    origin="📊 內建／示範資料", key_prefix=f"dsm_b_{bid}")

    # ── user-loaded sources (removable) ─────────────────────────────────
    if uploads:
        st.markdown("**📥 你載入的資料**")
        for bid, contract in uploads.items():
            m = meta.get(bid, {})
            origin = _SOURCE_BADGE.get(str(m.get("source", "")).lower(), "📄 上傳檔案")
            _uploaded = _friendly_time(m.get("uploaded_at"))
            render_source_inspector(contract, display_name=m.get("display_name", bid),
                                    origin=origin, key_prefix=f"dsm_u_{bid}",
                                    subtitle=f"🕒 載入於 {_uploaded}" if _uploaded else None)
            if st.button("🗑 移除此來源", key=f"dsm_remove_{bid}"):
                st.session_state.get(_USER_BLOCKS_KEY, {}).pop(bid, None)
                st.session_state.get(_USER_BLOCK_META_KEY, {}).pop(bid, None)
                st.rerun()

    if total >= 2:
        st.caption("💡 想把多份資料合併分析？到 **🔗 模型** 模式建立關聯（join）。")
    st.divider()


# ---------------------------------------------------------------------------
# User semantic model helpers
# ---------------------------------------------------------------------------

def get_user_semantic_model() -> dict:
    """Return the user-managed semantic model from session_state.

    Merges user-defined relationships with an empty base structure.
    Used by NL2, catalog, and executor to understand cross-table joins.
    """
    sm = st.session_state.get(_USER_SEMANTIC_MODEL_KEY)
    if sm is None:
        sm = {
            "model_id": "user_data_model",
            "version": "1.0.0",
            "label": "使用者資料模型",
            "blocks": [],
            "relationships": [],
            "metrics": [],
            "prohibited_paths": [],
        }
        st.session_state[_USER_SEMANTIC_MODEL_KEY] = sm
    return sm


def _add_relationship(
    from_block: str,
    from_col: str,
    to_block: str,
    to_col: str,
    rel_id: Optional[str] = None,
) -> None:
    """Add a user-defined relationship to the session semantic model."""
    sm = get_user_semantic_model()
    rel_id = rel_id or f"user_{from_block}_to_{to_block}_{from_col}"
    # Remove any existing relationship with same id
    sm["relationships"] = [r for r in sm["relationships"] if r.get("relationship_id") != rel_id]
    sm["relationships"].append({
        "relationship_id": rel_id,
        "from_block": from_block,
        "to_block": to_block,
        "keys": [{"from": from_col, "to": to_col}],
        "cardinality": "many_to_one",
        "join_type": "left",
        "status": "certified",  # user-defined = trusted for their own data
    })
    # Update blocks list
    for bid in (from_block, to_block):
        if bid not in sm["blocks"]:
            sm["blocks"].append(bid)


def _remove_relationship(rel_id: str) -> None:
    sm = get_user_semantic_model()
    sm["relationships"] = [r for r in sm["relationships"] if r.get("relationship_id") != rel_id]


def _auto_detect_join_cols(
    block_a: DataBlockContract,
    block_b: DataBlockContract,
) -> list[tuple[str, str, float]]:
    """Find common column pairs between two blocks and score them.

    Returns list of (col_a, col_b, confidence_score) sorted by score desc.
    """
    a_cols = {c.name.lower(): c.name for c in block_a.columns}
    b_cols = {c.name.lower(): c.name for c in block_b.columns}

    matches: list[tuple[str, str, float]] = []

    # Exact name matches
    for lower_a, orig_a in a_cols.items():
        if lower_a in b_cols:
            orig_b = b_cols[lower_a]
            score = 1.0
            matches.append((orig_a, orig_b, score))

    # Fuzzy: strip common suffixes and match
    _STRIP = re.compile(r"(_id|_key|_code|_no|_num|_name)$", re.I)
    for lower_a, orig_a in a_cols.items():
        stem_a = _STRIP.sub("", lower_a)
        for lower_b, orig_b in b_cols.items():
            stem_b = _STRIP.sub("", lower_b)
            if stem_a == stem_b and (orig_a, orig_b, 1.0) not in matches:
                matches.append((orig_a, orig_b, 0.7))

    # Deduplicate and sort
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str, float]] = []
    for a, b, score in sorted(matches, key=lambda x: -x[2]):
        if (a, b) not in seen:
            seen.add((a, b))
            unique.append((a, b, score))
    return unique[:10]


# ---------------------------------------------------------------------------
# Round 037: Join Builder UI
# ---------------------------------------------------------------------------

def render_join_builder(expanded: bool = False) -> None:
    """Render the '資料關聯設定' expander — Round 037.

    Round 148: ``expanded`` lets the caller open it by default when it is the
    primary panel of the 模型 view (so the headline feature isn't one click away).
    Round 156: operates on genuinely user-loaded data only (not the demo seed).
    """
    user_blocks: dict[str, DataBlockContract] = _user_loaded_blocks()

    with st.expander("🔗 資料關聯設定（把兩份資料用共同欄位連結）", expanded=expanded):
        st.caption(
            "將兩份資料用共同欄位連結起來，就能在同一張圖表中顯示不同來源的數字。"
        )

        if len(user_blocks) < 2:
            st.info(
                "上傳至少 **2 份資料** 後，才能設定資料關聯。\n\n"
                "範例：銷售明細 + 門市基本資料，用 `store_id` 連結後，\n"
                "即可在同一張圖表裡顯示各門市的「銷售額」和「門市坪數」。",
                icon="💡",
            )
            return

        block_ids = list(user_blocks.keys())

        st.caption("**建立新的關聯**")
        col_l, col_r = st.columns(2)
        with col_l:
            from_bid = st.selectbox("主表（事實資料）", block_ids, key="join_from_block")
        with col_r:
            to_options = [b for b in block_ids if b != from_bid]
            if not to_options:
                st.warning("需要至少兩份不同的資料才能建立關聯。")
                return
            to_bid = st.selectbox("副表（維度資料）", to_options, key="join_to_block")

        from_contract = user_blocks.get(from_bid)
        to_contract = user_blocks.get(to_bid)
        if from_contract is None or to_contract is None:
            return

        # Auto-detect common columns
        candidates = _auto_detect_join_cols(from_contract, to_contract)

        if candidates:
            top_a, top_b, confidence = candidates[0]
            conf_pct = int(confidence * 100)
            if confidence >= 0.9:
                st.success(
                    f"✅ AI 偵測到最佳連接欄位：`{from_bid}.{top_a}` ↔ `{to_bid}.{top_b}`"
                    f"（信心度 {conf_pct}%）"
                )
            else:
                st.info(
                    f"💡 建議連接欄位：`{from_bid}.{top_a}` ↔ `{to_bid}.{top_b}`"
                    f"（信心度 {conf_pct}%，請確認是否正確）"
                )

        # Let user choose columns
        from_col_options = [c.name for c in from_contract.columns]
        to_col_options = [c.name for c in to_contract.columns]

        default_from = candidates[0][0] if candidates else from_col_options[0]
        default_to = candidates[0][1] if candidates else to_col_options[0]

        col1, col2 = st.columns(2)
        with col1:
            from_col = st.selectbox(
                f"{from_bid} 的連接欄位",
                from_col_options,
                index=from_col_options.index(default_from) if default_from in from_col_options else 0,
                key="join_from_col",
            )
        with col2:
            to_col = st.selectbox(
                f"{to_bid} 的連接欄位",
                to_col_options,
                index=to_col_options.index(default_to) if default_to in to_col_options else 0,
                key="join_to_col",
            )

        if st.button("✅ 建立關聯", key="join_create_btn", type="primary"):
            _add_relationship(from_bid, from_col, to_bid, to_col)
            st.success(
                f"已建立關聯：`{from_bid}.{from_col}` → `{to_bid}.{to_col}`\n\n"
                "現在可以在同一張圖表裡同時使用這兩份資料的欄位。"
            )
            st.rerun()

        # Show existing relationships
        sm = get_user_semantic_model()
        existing_rels = [
            r for r in sm.get("relationships", [])
            if r.get("from_block") in user_blocks or r.get("to_block") in user_blocks
        ]
        if existing_rels:
            st.markdown("---")
            st.caption("**已建立的關聯**")
            for rel in existing_rels:
                keys = rel.get("keys", [{}])
                from_k = keys[0].get("from", "?") if keys else "?"
                to_k = keys[0].get("to", "?") if keys else "?"
                rel_col, del_col = st.columns([5, 1])
                with rel_col:
                    st.markdown(
                        f"`{rel['from_block']}.{from_k}` **→** `{rel['to_block']}.{to_k}`"
                    )
                with del_col:
                    if st.button("刪除", key=f"del_rel_{rel['relationship_id']}"):
                        _remove_relationship(rel["relationship_id"])
                        st.rerun()


# ---------------------------------------------------------------------------
# Round 038: Data Model View
# ---------------------------------------------------------------------------

_BLOCK_TYPE_ICON = {
    "fact": "📊", "snapshot_fact": "📸", "target_fact": "🎯",
    "dimension": "🏷️", "date_dimension": "📅",
    "metric_set": "🔢", "derived_block": "🔄",
}
_DATA_TYPE_ICON = {
    "date": "📅", "timestamp": "📅", "float": "🔢", "integer": "🔢",
    "string": "🏷️", "boolean": "✓",
}


def render_data_model_view() -> None:
    """Render the '資料模型' expander — Round 038.

    Round 156: shows genuinely user-loaded data only (not the demo seed)."""
    user_blocks: dict[str, DataBlockContract] = _user_loaded_blocks()
    sm = get_user_semantic_model()

    with st.expander("🗂️ 資料模型", expanded=False):
        if not user_blocks:
            st.info("上傳資料後，這裡會顯示你的資料結構和關聯圖。", icon="🗂️")
            return

        st.caption(f"**{len(user_blocks)} 個資料集，{len(sm.get('relationships', []))} 個關聯**")

        for bid, contract in user_blocks.items():
            icon = _BLOCK_TYPE_ICON.get(contract.block_type.value, "📦")
            n_metrics = len(contract.metrics)
            n_dims = len([c for c in contract.columns if c.data_type in ("string", "str")])
            n_dates = len([c for c in contract.columns if c.data_type in ("date", "timestamp")])

            with st.expander(f"{icon} **{bid}** — {len(contract.columns)} 欄位", expanded=False):
                sum_m = [m for m in contract.metrics if m.disaggregation_method.value == "sum"]
                avg_m = [m for m in contract.metrics if m.disaggregation_method.value == "average"]
                # Use caption instead of st.metric() to avoid polluting AppTest metric collection
                st.caption(
                    f"📊 加總指標 **{len(sum_m)}** 個　"
                    f"⚠️ 比率指標 **{len(avg_m)}** 個　"
                    f"🏷️ 分類 **{n_dims}** 欄　"
                    f"📅 日期 **{n_dates}** 欄"
                )

                # Column list
                st.caption("**欄位清單**")
                for col in contract.columns:
                    dtype_icon = _DATA_TYPE_ICON.get(col.data_type, "▪️")
                    is_metric = any(m.name == col.name for m in contract.metrics)
                    metric_tag = " _(指標)_" if is_metric else ""
                    st.caption(f"{dtype_icon} `{col.name}` — {col.data_type}{metric_tag}")

        # Relationships diagram (textual)
        rels = sm.get("relationships", [])
        if rels:
            st.markdown("---")
            st.caption("**資料關聯圖**")
            for rel in rels:
                keys = rel.get("keys", [{}])
                from_k = keys[0].get("from", "?") if keys else "?"
                to_k = keys[0].get("to", "?") if keys else "?"
                status_icon = "✅" if rel.get("status") == "certified" else "⚠️"
                st.markdown(
                    f"{status_icon} `{rel['from_block']}`.`{from_k}` **─ many:1 ─→** "
                    f"`{rel['to_block']}`.`{to_k}`"
                )
