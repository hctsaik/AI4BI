"""Round 054: result post-processing (running total / moving avg / Pareto)."""

from __future__ import annotations

import pandas as pd
import pytest

from ai4bi.analysis.postprocess import (
    add_moving_average, add_pareto, add_running_total, apply_postprocess,
)
from ai4bi.query_spec import BlockRef, MetricRef, VisualizationSpec, VisualType, VisualQuerySpec


def _spec():
    return VisualQuerySpec("v", [BlockRef("b")], metrics=[MetricRef("b", "rev", "營收")])


def _viz(**extra):
    return VisualizationSpec(VisualType.table, extra=extra)


def test_running_total_cumulates():
    df = pd.DataFrame({"營收": [10.0, 20.0, 30.0]})
    out = add_running_total(df, "營收")
    assert list(out["營收（累計）"]) == [10.0, 30.0, 60.0]


def test_moving_average():
    df = pd.DataFrame({"營收": [10.0, 20.0, 30.0, 40.0]})
    out = add_moving_average(df, "營收", window=2)
    col = "營收（2期移動平均）"
    assert out[col].iloc[0] == pytest.approx(10.0)   # min_periods=1
    assert out[col].iloc[1] == pytest.approx(15.0)
    assert out[col].iloc[3] == pytest.approx(35.0)


def test_pareto_cumulative_and_abc():
    df = pd.DataFrame({"item": ["a", "b", "c", "d"], "營收": [80.0, 12.0, 5.0, 3.0]})
    out = add_pareto(df, "營收")
    # total 100 → cumulative 80, 92, 97, 100 → A(≤80) B(≤95) C(>95) C
    assert list(out["累計占比(%)"]) == [80.0, 92.0, 97.0, 100.0]
    assert list(out["ABC"]) == ["A", "B", "C", "C"]


def test_apply_postprocess_pareto_via_extra():
    df = pd.DataFrame({"商品": ["a", "b"], "營收": [70.0, 30.0]})
    out = apply_postprocess(df, _spec(), _viz(postprocess="pareto", postprocess_column="營收"))
    assert "ABC" in out.columns and "累計占比(%)" in out.columns


def test_apply_postprocess_noop_without_mode():
    df = pd.DataFrame({"營收": [1.0]})
    out = apply_postprocess(df, _spec(), _viz())
    assert out.equals(df)


def test_apply_postprocess_empty_df_safe():
    df = pd.DataFrame({"營收": []})
    out = apply_postprocess(df, _spec(), _viz(postprocess="pareto"))
    assert out.empty


def test_retail_demo_has_abc_table():
    from ai4bi.report.retail_template import build_retail_demo_report
    report = build_retail_demo_report()
    abc = report.pages["main"].visuals["table_product_abc"]
    assert abc.visualization.extra.get("postprocess") == "pareto"
