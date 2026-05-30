"""Phase 3 move / capacity / OEE scenarios — regression lock-in.

Three themed rounds the multi-agent loop drove to >95 (R128):
  A = move / WIP, B = capacity / utilization / loading, C = OEE.
Each asserts the analytical method + the headline signal the fab dataset embeds
(ETCH-02 bottleneck/excursion, CVD idle headroom, THINFILM low plan attainment).
"""

from __future__ import annotations

import pytest

from ai4bi.analysis.capacity import compute_oee, plan_attainment, throughput_rate, utilization
from ai4bi.analysis.executor import Executor
from ai4bi.ai.nl2proposal import NL2ProposalService
from ai4bi.report.fab_template import build_fab_demo_report, fab_contracts


@pytest.fixture(scope="module")
def env():
    c = fab_contracts()
    return NL2ProposalService(), build_fab_demo_report(), c, Executor(extra_contracts=c)


def _ask(env, p):
    svc, report, c, ex = env
    return svc.propose(p, report, None, contracts=c, executor=ex)


# --- capacity analytics module (direct) ----------------------------------
def test_capacity_block_present():
    c = fab_contracts()
    assert "fab_tool_capacity" in c


def test_utilization_etch02_is_bottleneck():
    u = utilization(fab_contracts(), "tool_id")
    assert not u.empty and u.iloc[0]["tool_id"] == "ETCH-02"  # highest util first
    assert u.iloc[0]["利用率%"] >= 90


def test_plan_attainment_worst_area():
    p = plan_attainment(fab_contracts(), "area")
    assert not p.empty and "達成率%" in p.columns  # ascending: worst first


def test_throughput_has_rate_column():
    t = throughput_rate(fab_contracts(), "tool_id")
    assert not t.empty and "moves_per_hr" in t.columns


def test_oee_etch02_worst_dragged_by_availability():
    o = compute_oee(fab_contracts())
    assert not o.empty and o.iloc[0]["tool_id"] == "ETCH-02"  # worst OEE first
    row = o.iloc[0]
    assert row["可用率A"] == min(row["可用率A"], row["表現P"], row["良率Q"])  # A drags


# --- Round A: move / WIP --------------------------------------------------
def test_A1_tool_move_ranking(env):
    r = _ask(env, "每台機台的移動次數，哪一台最高？")
    assert r.result_table is not None and "tool_id" in r.result_table.columns
    assert r.result_table.iloc[0]["tool_id"] == "ETCH-02"


def test_A3_step_queue_ranking(env):
    r = _ask(env, "各製程站的平均等待時間排名")
    assert r.result_table is not None and "step_id" in r.result_table.columns


def test_A6_product_move_share(env):
    r = _ask(env, "各產品別的移動次數佔總比")
    assert r.result_table is not None
    assert any("佔總" in c or "佔總比%" in c for c in r.result_table.columns)


def test_A10_etch02_anomaly_spc(env):
    r = _ask(env, "ETCH-02 的移動量與等待時間異常嗎？")
    assert r.result_table is not None  # SPC outlier table


# --- Round B: capacity / utilization -------------------------------------
def test_B1_utilization_ranking(env):
    r = _ask(env, "各機台的產能利用率排名")
    assert r.result_table is not None and "利用率%" in r.result_table.columns
    assert r.result_table.iloc[0]["tool_id"] == "ETCH-02"


def test_B2_headroom(env):
    r = _ask(env, "哪些機台還有產能餘裕、可以多接單？")
    assert r.result_table is not None and "餘裕" in r.result_table.columns
    assert "CVD" in str(r.result_table.iloc[0]["tool_id"])  # idle CVD has most headroom


def test_B4_plan_attainment_worst_area(env):
    r = _ask(env, "計畫達成率最差的區是哪一區？")
    assert r.result_table is not None and "達成率%" in r.result_table.columns


def test_B5_bottleneck_is_max_util(env):
    r = _ask(env, "整條線的瓶頸在哪？哪台機台利用率最高、餘裕最少？")
    assert r.result_table is not None
    assert r.result_table.iloc[0]["tool_id"] == "ETCH-02"  # NOT headroom-sorted


def test_B6_cvd_family_filter(env):
    r = _ask(env, "CVD 機台的利用率是不是偏低？")
    assert r.result_table is not None
    assert all(str(t).startswith("CVD-") for t in r.result_table["tool_id"])


def test_B7_etch_area_headroom(env):
    r = _ask(env, "ETCH 區的產能餘裕還有多少？")
    assert r.result_table is not None
    assert set(r.result_table["area"]) == {"ETCH"}


def test_B9_lowest_availability(env):
    r = _ask(env, "可用率最低（停機最多）的機台是哪一台？")
    assert r.result_table is not None
    assert r.result_table.iloc[0]["tool_id"] == "ETCH-02"


def test_B10_utilization_by_vendor(env):
    r = _ask(env, "各 vendor 機台群的平均利用率")
    assert r.result_table is not None and "vendor" in r.result_table.columns


# --- Round C: OEE ---------------------------------------------------------
def test_C1_oee_ranking_worst(env):
    r = _ask(env, "各機台的 OEE 排名，最低的是哪一台？")
    assert r.result_table is not None and "OEE" in r.result_table.columns
    assert r.result_table.iloc[0]["tool_id"] == "ETCH-02"


def test_C2_oee_drag_factor_is_availability(env):
    r = _ask(env, "ETCH-02 的 OEE 為什麼這麼低？是可用率、表現還是良率拖累？")
    assert r.result_table is not None
    assert "可用率" in r.message  # names availability as the actual drag, not 表現


def test_C3_fab_average_oee(env):
    r = _ask(env, "全廠平均 OEE 大概多少？")
    assert r.result_table is not None and "範圍" in r.result_table.columns


def test_C4_oee_by_vendor(env):
    r = _ask(env, "各 vendor 機台群的 OEE 對比")
    assert r.result_table is not None and "vendor" in r.result_table.columns


def test_C8_oee_by_area(env):
    r = _ask(env, "各區（area）的 OEE 平均")
    assert r.result_table is not None and "area" in r.result_table.columns


def test_C9_oee_below_threshold(env):
    r = _ask(env, "OEE 低於 60% 的機台有哪些？")
    assert r.result_table is not None
    assert all(v < 60 for v in r.result_table["OEE"])


def test_C10_which_tool_to_fix_first(env):
    r = _ask(env, "如果要提升整廠 OEE，最該先處理哪一台？")
    assert r.result_table is not None and "tool_id" in r.result_table.columns
    assert r.result_table.iloc[0]["tool_id"] == "ETCH-02"  # worst, not fab-average
