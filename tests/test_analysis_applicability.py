"""Round 156: advanced-analysis panels are data-driven — retail-only analyses
(cohort/basket/RFM) must NOT apply to semiconductor data; decline-detection does.
"""

from __future__ import annotations

from ai4bi.ui.rfm_panel import _rfm_applicable
from ai4bi.ui.cohort_panel import _cohort_applicable
from ai4bi.ui.basket_panel import _basket_applicable
from ai4bi.ui.trend_streak_panel import _streak_applicable
from ai4bi.report.retail_template import build_retail_sales_block
from ai4bi.report.fab_template import fab_contracts


def _fab_move():
    return fab_contracts()["fab_process_move"]


def test_retail_block_supports_customer_analyses():
    retail = build_retail_sales_block()
    assert _rfm_applicable(retail) is True
    assert _cohort_applicable(retail) is True
    assert _basket_applicable(retail) is True
    assert _streak_applicable(retail) is True


def test_fab_block_excludes_customer_analyses():
    fab = _fab_move()
    # no customer / money / order columns -> these retail analyses must not apply
    assert _rfm_applicable(fab) is False
    assert _cohort_applicable(fab) is False
    assert _basket_applicable(fab) is False


def test_fab_block_supports_decline_detection():
    # decline-detection works on tool x date x metric (queue time), so it applies
    assert _streak_applicable(_fab_move()) is True
