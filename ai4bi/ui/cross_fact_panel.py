"""Cross-fact composition panel — Round 055.

No-code UI for "metric from table A ÷ metric from table B" questions that a
single fact table can't answer — e.g. revenue (retail_sales) per employee
(store_staffing), joined on store. Wires the previously UI-orphaned
CompositionExecutor via analysis/cross_fact.compose_two_facts.
"""

from __future__ import annotations

import streamlit as st

from ai4bi.analysis.cross_fact import compose_two_facts, shared_columns
from ai4bi.blocks.contracts import BlockType, DataBlockContract
from ai4bi.planning.composition_plan import CompositionPlanningError
from ai4bi.ui.upload import _USER_BLOCKS_KEY, _USER_BLOCK_META_KEY

_AGGS = ["SUM", "AVG", "COUNT", "MIN", "MAX"]
_NUMERIC = ("integer", "int", "float", "double", "number", "numeric")


def _fact_blocks() -> dict[str, DataBlockContract]:
    blocks: dict = st.session_state.get(_USER_BLOCKS_KEY, {})
    return {bid: c for bid, c in blocks.items() if c.block_type == BlockType.fact}


def _numeric_cols(contract: DataBlockContract) -> list[str]:
    return [c.name for c in contract.columns if c.data_type in _NUMERIC]


def _label(bid: str) -> str:
    meta = st.session_state.get(_USER_BLOCK_META_KEY, {}).get(bid, {})
    return meta.get("display_name") or bid


def render_cross_fact_panel() -> None:
    """Render the cross-table ratio panel (sidebar)."""
    facts = _fact_blocks()
    if len(facts) < 2:
        return

    with st.expander("🔗 跨資料表計算（人均、轉換率…）", expanded=False):
        st.caption(
            "把兩張資料表的數字相除，例如：營收 ÷ 員工數 = 人均營收。"
            "系統會各自彙總到共同欄位後再相除（安全，不會重複計算）。"
        )
        ids = list(facts.keys())

        block_a = st.selectbox("資料表 A（分子）", ids, format_func=_label, key="xf_block_a")
        cols_a = _numeric_cols(facts[block_a])
        if not cols_a:
            st.info("資料表 A 沒有數值欄位。")
            return
        c1, c2 = st.columns([2, 1])
        with c1:
            col_a = st.selectbox("A 欄位", cols_a, key="xf_col_a")
        with c2:
            agg_a = st.selectbox("A 彙總", _AGGS, key="xf_agg_a")

        ids_b = [b for b in ids if b != block_a] or ids
        block_b = st.selectbox("資料表 B（分母）", ids_b, format_func=_label, key="xf_block_b")
        cols_b = _numeric_cols(facts[block_b])
        if not cols_b:
            st.info("資料表 B 沒有數值欄位。")
            return
        c3, c4 = st.columns([2, 1])
        with c3:
            col_b = st.selectbox("B 欄位", cols_b, key="xf_col_b")
        with c4:
            agg_b = st.selectbox("B 彙總", _AGGS, key="xf_agg_b")

        keys = shared_columns(facts[block_a], facts[block_b])
        if not keys:
            st.warning("這兩張表沒有共同欄位可對應，無法跨表計算。")
            return
        join_key = st.selectbox("對應欄位（join）", keys, key="xf_join")
        op = st.selectbox(
            "計算方式", ["ratio", "diff", "margin_pct"],
            format_func=lambda o: {"ratio": "A ÷ B（比率）", "diff": "A − B（差額）",
                                   "margin_pct": "(A − B) ÷ A ×100（毛利率%）"}[o],
            key="xf_op",
        )
        _default_name = {"ratio": "人均營收", "diff": "差額", "margin_pct": "毛利率%"}[op]
        ratio_name = st.text_input("結果名稱", value=_default_name, key="xf_ratio_name")

        if st.button("📊 計算", key="xf_run", type="primary"):
            try:
                df = compose_two_facts(
                    facts,
                    block_a=block_a, agg_a=agg_a, col_a=col_a, alias_a=f"A_{col_a}",
                    block_b=block_b, agg_b=agg_b, col_b=col_b, alias_b=f"B_{col_b}",
                    join_key=join_key, ratio_alias=ratio_name or "結果", op=op,
                )
                st.session_state["_xf_result"] = df
            except CompositionPlanningError as exc:
                st.error(f"無法計算：{exc}")
            except Exception as exc:  # noqa: BLE001
                st.error(f"計算失敗：{exc}")

        df = st.session_state.get("_xf_result")
        if df is not None and not df.empty:
            st.dataframe(df, width="stretch", hide_index=True)
            ratio_col = ratio_name or "比率"
            if join_key in df.columns and ratio_col in df.columns:
                st.bar_chart(df.set_index(join_key)[ratio_col])
