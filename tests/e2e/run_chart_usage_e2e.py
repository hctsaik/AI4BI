"""E2E for the 10 common chart-usage scenarios (multi-agent generated).

Drives a real browser and reads Plotly's live `.data`/`.layout` off the chart
DOM nodes — so axis range, log scale, traces, legend, data labels etc. are
verified as actually rendered, not just as control state. Standalone (free port).

Run:  python tests/e2e/run_chart_usage_e2e.py
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

_APP = Path(__file__).parents[2] / "ai4bi" / "ui" / "app.py"

results: list[tuple[str, bool, str]] = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(port):
    import os
    env = dict(os.environ)
    env["LLM_MODE"] = "mock"  # deterministic NL routing (don't inherit a dev key)
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(_APP), "--server.port", str(port),
         "--server.headless", "true", "--server.runOnSave", "false",
         "--browser.gatherUsageStats", "false"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    url = f"http://localhost:{port}"
    end = time.time() + 40
    while time.time() < end:
        try:
            if requests.get(url, timeout=2).status_code == 200:
                return proc, url
        except Exception:
            pass
        time.sleep(1)
    proc.terminate(); raise RuntimeError("server did not start")


def _load(pg, url):
    pg.goto(url, wait_until="networkidle", timeout=60_000)
    pg.wait_for_selector("[data-testid='stApp']", timeout=30_000)
    pg.wait_for_timeout(4_000)


def _load_semi(pg):
    # the semi demo has a real bar chart ("Queue Time by Tool ID") for chart tests
    pg.get_by_text("進階示範").first.click()
    pg.wait_for_timeout(700)
    pg.get_by_role("button", name="載入半導體示範報表").click()
    pg.wait_for_timeout(4_000)


def _open_select(pg, label_substr: str):
    sb = pg.locator("div[data-testid='stSelectbox']").filter(has_text=label_substr).first
    target = sb.locator("div[data-baseweb='select']").first
    for _ in range(4):
        target.scroll_into_view_if_needed()
        pg.wait_for_timeout(150)
        target.click()
        pg.wait_for_timeout(500)
        if pg.locator("li[role='option']").count() > 0:  # popover opened
            return
    target.click(force=True)
    pg.wait_for_timeout(500)


def _set_select_last(pg, label_substr: str):
    """Pick the last option of a labelled selectbox (a value different from default)."""
    _open_select(pg, label_substr)
    opt = pg.locator("li[role='option']").last
    try:
        opt.scroll_into_view_if_needed(timeout=3_000)
    except Exception:
        pass
    try:
        opt.click(force=True, timeout=4_000)
    except Exception:
        pg.keyboard.press("ArrowUp"); pg.keyboard.press("Enter")
    pg.wait_for_timeout(3_000)


def _plotly(pg):
    """All Plotly charts' live state."""
    return pg.evaluate(
        """() => Array.from(document.querySelectorAll('.js-plotly-plot')).map(d => ({
            types: (d.data||[]).map(t=>t.type),
            type0: (d.data && d.data[0]) ? d.data[0].type : null,
            yrange: (d.layout && d.layout.yaxis) ? d.layout.yaxis.range : null,
            ytype: (d.layout && d.layout.yaxis) ? d.layout.yaxis.type : null,
            showlegend: d.layout ? !!d.layout.showlegend : false,
            legorient: (d.layout && d.layout.legend) ? d.layout.legend.orientation : null,
            legy: (d.layout && d.layout.legend) ? d.layout.legend.y : null,
            hastext: (d.data||[]).some(t => t.texttemplate || (t.text && t.text.length)),
            y0: (d.calcdata && d.calcdata[0])
                  ? d.calcdata[0].map(pt => pt.y !== undefined ? pt.y : pt.s).slice(0,12) : []
        }))""")


def _expand_fallback(pg):
    """Open the '或用下拉選單編輯' expander where the value/dimension/type dropdowns live."""
    exp = pg.get_by_text("或用下拉選單編輯", exact=False).first
    if exp.count():
        try:
            exp.click()
            pg.wait_for_timeout(700)
        except Exception:
            pass


def _select_visual(pg, label_substr: str):
    lbl = pg.get_by_text("選擇圖表").first
    box = lbl.locator(
        "xpath=ancestor::div[contains(@data-testid,'stSelectbox')]//div[@data-baseweb='select']")
    (box.first if box.count() else pg.locator('div[data-baseweb="select"]').first).click()
    pg.wait_for_timeout(700)
    opt = pg.locator('li[role="option"]').filter(has_text=label_substr).first
    (opt if opt.count() else pg.locator('li[role="option"]').nth(1)).click()
    pg.wait_for_timeout(3_500)


def _pick_option(pg, option_substr: str):
    # keyboard-first (baseweb selects filter as you type) — reliable in narrow panes
    pg.keyboard.type(option_substr)
    pg.wait_for_timeout(500)
    opt = pg.locator("li[role='option']").filter(has_text=option_substr).first
    if opt.count():
        try:
            opt.click(force=True, timeout=4_000)
            pg.wait_for_timeout(3_000)
            return
        except Exception:
            pass
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(3_000)


def _set_select(pg, label_substr: str, option_substr: str):
    _open_select(pg, label_substr)
    _pick_option(pg, option_substr)


def _fill(pg, label_substr: str, value: str):
    ti = pg.locator("div[data-testid='stTextInput']").filter(has_text=label_substr).first
    ti.locator("input").fill(value)
    pg.wait_for_timeout(300)


def _click_btn(pg, text: str):
    pg.get_by_role("button", name=text, exact=False).first.click()
    pg.wait_for_timeout(3_000)


BAR = "Tool ID"  # matches the semi demo's bar chart "Queue Time by Tool ID"


def _bar(pg, retries: int = 6):
    """The bar chart's live Plotly state (first trace type == 'bar'); polls while
    the chart re-renders after an edit."""
    for _ in range(retries):
        s = next((s for s in _plotly(pg) if s["type0"] == "bar" and s["y0"]), None)
        if s:
            return s
        pg.wait_for_timeout(1_000)
    return next((s for s in _plotly(pg) if s["type0"] == "bar"), None)


def _selector_option_count(pg) -> int:
    lbl = pg.get_by_text("選擇圖表").first
    box = lbl.locator("xpath=ancestor::div[contains(@data-testid,'stSelectbox')]//div[@data-baseweb='select']")
    (box.first if box.count() else pg.locator('div[data-baseweb="select"]').first).click()
    pg.wait_for_timeout(500)
    n = pg.locator('li[role="option"]').count()
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(300)
    return n


def main() -> int:
    port = _free_port()
    proc, url = _start(port)
    try:
        with sync_playwright() as p:
            br = p.chromium.launch()

            def fresh():
                """A fresh page on the semi demo — keeps scenarios independent."""
                pg = br.new_page()
                _load(pg, url)
                _load_semi(pg)
                return pg

            # S1 — change chart type bar→line
            pg = fresh()
            _select_visual(pg, BAR); _expand_fallback(pg)
            before = sum(t == "scatter" for s in _plotly(pg) for t in s["types"])
            _set_select(pg, "圖表類型", "折線圖")
            after = sum(t == "scatter" for s in _plotly(pg) for t in s["types"])
            check("S1 change chart type → line", after > before, f"scatter {before}→{after}")
            pg.close()

            # S2 — change measure (queue time → move_count) changes the bar's data
            pg = fresh()
            _select_visual(pg, BAR); _expand_fallback(pg)
            b = _bar(pg)
            _set_select(pg, "值", "process_time_min")
            a = _bar(pg)
            check("S2 change measure changes data",
                  b is not None and a is not None and a["y0"] != b["y0"],
                  f"{b['y0'] if b else None}→{a['y0'] if a else None}")
            pg.close()

            # S3 — change group-by dimension
            pg = fresh()
            _select_visual(pg, BAR); _expand_fallback(pg)
            _set_select_last(pg, "分組")
            check("S3 change group-by dimension (no error)",
                  len(pg.locator("[data-testid='stException']").all()) == 0)
            pg.close()

            # S4 — sort high→low → bar values non-increasing
            pg = fresh()
            _select_visual(pg, BAR)
            _set_select(pg, "排序", "由高到低")
            s = _bar(pg)
            mono = bool(s and len(s["y0"]) >= 2 and all(s["y0"][i] >= s["y0"][i+1] for i in range(len(s["y0"])-1)))
            check("S4 sort high→low → non-increasing bars", mono, str(s["y0"][:6]) if s else "no bar")
            pg.close()

            # S5 — Y-axis min/max
            pg = fresh()
            _select_visual(pg, BAR)
            _fill(pg, "Y 最小", "0"); _fill(pg, "Y 最大", "999")
            _click_btn(pg, "套用 Y 軸")
            s = _bar(pg)
            ok5 = bool(s and s["yrange"] and abs(s["yrange"][0]) < 1e-6 and abs(s["yrange"][1]-999) < 1)
            check("S5 Y-axis range applied", ok5, str(s["yrange"]) if s else "no bar")
            pg.close()

            # S6 — log scale
            pg = fresh()
            _select_visual(pg, BAR)
            _set_select(pg, "刻度", "對數")
            _click_btn(pg, "套用 Y 軸")
            s = _bar(pg)
            check("S6 Y-axis log scale", bool(s and s["ytype"] == "log"))
            pg.close()

            # S7 — data labels
            pg = fresh()
            _select_visual(pg, BAR)
            before_dl = bool((_bar(pg) or {}).get("hastext"))
            pg.get_by_text("顯示資料標籤").first.click()
            pg.wait_for_timeout(3_000)
            after_dl = bool((_bar(pg) or {}).get("hastext"))
            check("S7 data labels toggled on", after_dl and not before_dl, f"{before_dl}→{after_dl}")
            pg.close()

            # S8 — legend to bottom
            pg = fresh()
            _select_visual(pg, BAR)
            _set_select(pg, "圖例位置", "底部")
            s = _bar(pg)
            check("S8 legend moved to bottom",
                  bool(s and s["showlegend"] and s["legy"] is not None and s["legy"] < 0),
                  str((s["showlegend"], s["legy"])) if s else "no bar")
            pg.close()

            # S9 — delete a chart
            pg = fresh()
            before_del = pg.get_by_role("button", name="🗑", exact=True).count()
            pg.get_by_role("button", name="🗑", exact=True).first.click()
            pg.wait_for_timeout(3_000)
            after_del = pg.get_by_role("button", name="🗑", exact=True).count()
            check("S9 delete removes one chart", after_del == before_del - 1, f"{before_del}→{after_del}")
            pg.close()

            # S10 — add a chart by typing (NL)
            pg = fresh()
            n_before = _selector_option_count(pg)
            pg.locator("textarea").first.fill("加一張長條圖")
            pg.get_by_role("button", name="送出請求", exact=False).first.click()
            pg.wait_for_timeout(3_500)
            for name in ("Apply Proposal", "套用提案", "套用", "Apply"):
                btn = pg.get_by_role("button", name=name, exact=False)
                if btn.count():
                    btn.first.click(); pg.wait_for_timeout(4_000); break
            n_after = _selector_option_count(pg)
            check("S10 add chart by NL (+1 visual)", n_after >= n_before + 1, f"{n_before}→{n_after}")
            pg.close()

            br.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n=== chart-usage E2E: {passed}/{len(results)} scenarios passed ===")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
