"""Calculated-measure authoring UI — Round 052.

The derived-metric *engine* (executor `_build_derived_formula_expr`, R045) can
already run safe composite formulas like `(revenue - cost) / revenue`, but there
was no way for a non-technical owner to create one without hand-editing JSON.
This panel adds a no-code form: pick a dataset, name the measure, type a formula,
see it validated live against the same allow-list sandbox the engine uses, save.

Saved measures are appended to the user block's contract (disaggregation_method
= none) so the executor, add-visual panel, alerts, and NL2 all see them.
"""

from __future__ import annotations

import streamlit as st

from ai4bi.analysis.executor import QueryPlanningError, _build_derived_formula_expr
from ai4bi.blocks.contracts import DisaggregationMethod, MetricDefinition
from ai4bi.ui.upload import _USER_BLOCKS_KEY, _USER_BLOCK_META_KEY


def _column_names(contract) -> list[str]:
    return [c.name for c in contract.columns]


def validate_formula(formula: str, contract, parameters: dict | None = None) -> tuple[bool, str]:
    """Validate a formula against the engine sandbox. Returns (ok, message).

    Round 060: ``parameters`` (what-if @names) are accepted so formulas that
    reference them validate instead of being rejected as unknown identifiers.
    """
    try:
        _build_derived_formula_expr(
            formula, contract.block_id, set(_column_names(contract)),
            parameters=parameters or {},
        )
        return True, "公式有效 ✅"
    except QueryPlanningError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"無法解析公式：{exc}"


def _existing_derived(contract) -> list[MetricDefinition]:
    return [m for m in contract.metrics if m.disaggregation_method == DisaggregationMethod.none]


def render_calc_metric_panel() -> None:
    """Render the '新增計算欄位' panel (sidebar)."""
    user_blocks: dict = st.session_state.get(_USER_BLOCKS_KEY, {})
    if not user_blocks:
        return

    with st.expander("➗ 新增計算欄位", expanded=False):
        st.caption(
            "用現有欄位組合出新指標，例如：毛利率 = (revenue - cost) / revenue。"
            "支援 + - * / 、SUM/AVG/COUNT、NULLIF、CASE WHEN。"
        )

        block_ids = list(user_blocks.keys())
        block_id = st.selectbox(
            "資料集", block_ids,
            format_func=lambda b: st.session_state.get(_USER_BLOCK_META_KEY, {})
                .get(b, {}).get("display_name", b),
            key="calc_block_sel",
        )
        contract = user_blocks[block_id]

        st.caption("可用欄位：" + "、".join(f"`{c}`" for c in _column_names(contract)))

        name = st.text_input("指標名稱", placeholder="毛利率", key="calc_name")
        formula = st.text_input(
            "公式",
            placeholder="(revenue - cost) / NULLIF(revenue, 0)",
            key="calc_formula",
        )
        col1, col2 = st.columns(2)
        with col1:
            unit = st.text_input("單位（選填）", placeholder="%", key="calc_unit")
        with col2:
            desc = st.text_input("說明（選填）", key="calc_desc")

        from ai4bi.ui.what_if_panel import get_parameters
        _params = get_parameters()

        # Live validation
        if formula.strip():
            ok, msg = validate_formula(formula, contract, _params)
            (st.success if ok else st.error)(msg)
        else:
            ok = False

        if st.button("➕ 建立計算欄位", key="calc_add_btn", type="primary",
                     disabled=not (name.strip() and formula.strip())):
            # Derived-metric names become a quoted SQL alias, so Unicode is fine —
            # keep the user's name verbatim instead of slugifying it to "col".
            metric_name = name.strip()
            existing_names = {m.name for m in contract.metrics}
            if metric_name in existing_names:
                st.error(f"指標名稱「{metric_name}」已存在。")
            else:
                ok, msg = validate_formula(formula, contract, _params)
                if not ok:
                    st.error(f"公式無效：{msg}")
                else:
                    new_metric = MetricDefinition(
                        name=metric_name,
                        formula=formula.strip(),
                        disaggregation_method=DisaggregationMethod.none,
                        unit=unit.strip() or None,
                        description=desc.strip() or name.strip(),
                    )
                    updated = contract.model_copy(
                        update={"metrics": list(contract.metrics) + [new_metric]}
                    )
                    st.session_state[_USER_BLOCKS_KEY][block_id] = updated
                    meta = st.session_state.setdefault(_USER_BLOCK_META_KEY, {})
                    block_meta = meta.setdefault(block_id, {})
                    block_meta.setdefault("metric_names", [])
                    if metric_name not in block_meta["metric_names"]:
                        block_meta["metric_names"].append(metric_name)
                    st.success(f"✅ 已建立計算欄位「{name}」，可在新增圖表、提醒、摘要中使用。")
                    st.rerun()

        # Existing calculated measures
        derived = _existing_derived(contract)
        if derived:
            st.markdown("---")
            st.caption("此資料集的計算欄位：")
            for m in derived:
                c1, c2 = st.columns([5, 1])
                with c1:
                    st.write(f"• **{m.description or m.name}** = `{m.formula}`")
                with c2:
                    if st.button("刪除", key=f"calc_del_{block_id}_{m.name}"):
                        kept = [x for x in contract.metrics if x.name != m.name]
                        st.session_state[_USER_BLOCKS_KEY][block_id] = contract.model_copy(
                            update={"metrics": kept}
                        )
                        st.rerun()
