"""Cohort / retention panel — Round 062.

Pick a dataset with a customer id + a date column and see a retention matrix:
of the customers who first bought in month M, what % came back in month M+1,
M+2, ... Reads rows from the content-addressed store (R051), no executor needed.
"""

from __future__ import annotations

import streamlit as st

from ai4bi.analysis.cohort import cohort_retention
from ai4bi.blocks.contracts import BlockType, DataBlockContract
from ai4bi.blocks.datastore import materialize_dataframe
from ai4bi.ui.upload import _USER_BLOCKS_KEY, _USER_BLOCK_META_KEY

_ID_HINTS = ("customer", "member", "user", "client", "_id")
_DATE_HINTS = ("date", "_at", "_on", "time")


def _fact_blocks() -> dict[str, DataBlockContract]:
    blocks: dict = st.session_state.get(_USER_BLOCKS_KEY, {})
    return {b: c for b, c in blocks.items() if c.block_type == BlockType.fact}


def _guess(cols: list[str], hints: tuple[str, ...]) -> int:
    for i, c in enumerate(cols):
        lc = c.lower()
        if any(h in lc for h in hints):
            return i
    return 0


def render_cohort_panel() -> None:
    """Render the cohort/retention sidebar panel."""
    facts = _fact_blocks()
    if not facts:
        return

    with st.expander("👥 客戶留存分析（Cohort）", expanded=False):
        st.caption("看不同月份首購的客戶，後續幾個月還會回來消費的比例。")

        bid = st.selectbox(
            "資料集", list(facts.keys()),
            format_func=lambda b: st.session_state.get(_USER_BLOCK_META_KEY, {})
                .get(b, {}).get("display_name", b),
            key="cohort_block",
        )
        contract = facts[bid]
        cols = [c.name for c in contract.columns]
        if len(cols) < 2:
            st.info("欄位不足，無法分析。")
            return

        c1, c2, c3 = st.columns(3)
        with c1:
            cust = st.selectbox("客戶欄位", cols, index=_guess(cols, _ID_HINTS), key="cohort_cust")
        with c2:
            date_col = st.selectbox("日期欄位", cols, index=_guess(cols, _DATE_HINTS), key="cohort_date")
        with c3:
            period = st.selectbox("週期", ["month", "week"],
                                  format_func=lambda p: {"month": "月", "week": "週"}[p],
                                  key="cohort_period")

        if st.button("📊 計算留存", key="cohort_run", type="primary"):
            try:
                df = materialize_dataframe(contract)
                result = cohort_retention(df, cust, date_col, period)
                st.session_state["_cohort_result"] = result.retention
                st.session_state["_cohort_sizes"] = result.cohort_sizes
            except Exception as exc:  # noqa: BLE001
                st.error(f"無法計算：{exc}")

        retention = st.session_state.get("_cohort_result")
        if retention is not None and not retention.empty:
            sizes = st.session_state.get("_cohort_sizes")
            st.caption("留存率 %（列＝首購週期，欄＝之後第幾期）")
            st.dataframe(retention, width="stretch")
            if sizes is not None and not sizes.empty:
                st.caption(
                    "各 cohort 人數：" + "、".join(f"{k}={int(v)}" for k, v in sizes.items())
                )
