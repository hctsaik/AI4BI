"""Round 055: cross-fact composition (revenue per employee) wiring."""

from __future__ import annotations

import pytest

from ai4bi.analysis.cross_fact import compose_two_facts, shared_columns
from ai4bi.planning.composition_plan import CompositionPlanningError
from ai4bi.report.retail_template import build_retail_sales_block, build_store_staffing_block


def _contracts():
    return {
        "retail_sales": build_retail_sales_block(),
        "store_staffing": build_store_staffing_block(),
    }


def test_shared_columns_finds_join_key():
    c = _contracts()
    shared = shared_columns(c["retail_sales"], c["store_staffing"])
    assert "store_name" in shared


def test_revenue_per_employee_composition():
    c = _contracts()
    df = compose_two_facts(
        c,
        block_a="retail_sales", agg_a="SUM", col_a="revenue", alias_a="rev",
        block_b="store_staffing", agg_b="SUM", col_b="headcount", alias_b="emp",
        join_key="store_name", ratio_alias="人均營收",
    )
    # one row per store, both metrics present, ratio computed
    assert set(df["store_name"]) <= {
        "台北信義店", "台北西門店", "台中中港店", "高雄三多店", "台南成功店",
    }
    assert "人均營收" in df.columns
    row = df[df["store_name"] == "台北信義店"].iloc[0]
    assert row["人均營收"] == pytest.approx(row["rev"] / row["emp"], rel=1e-3)
    assert row["emp"] == 14


def test_composition_rejects_three_facts_via_validate():
    # compose_two_facts only ever builds 2 steps; ensure a bad join key is caught
    c = _contracts()
    with pytest.raises(CompositionPlanningError):
        compose_two_facts(
            c,
            block_a="retail_sales", agg_a="SUM", col_a="revenue", alias_a="rev",
            block_b="store_staffing", agg_b="SUM", col_b="headcount", alias_b="emp",
            join_key="nonexistent_column",   # not in group-by ownership → error
        )


def test_demo_registers_staffing_as_second_fact():
    from ai4bi.blocks.contracts import BlockType
    staffing = build_store_staffing_block()
    assert staffing.block_type == BlockType.fact
    assert {m.name for m in staffing.metrics} >= {"headcount", "labor_hours"}
