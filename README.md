# AI4BI — Headless Analytics Platform

A governed, AI-assisted BI platform where data scientists deliver reusable JSON DataBlocks and business users compose multi-source analysis dashboards without custom GUI code.

## Quick Start

```bash
pip install -e ".[dev]"
streamlit run ai4bi/ui/app.py          # ETCH Queue-Time Explorer demo
python -m pytest tests/ -q             # run full test suite
```

### Windows 一鍵啟動器

雙擊專案根目錄的 `launch.hta`（Windows 內建，免安裝）即可圖形化啟動：可選 port、切換 Claude API（LLM）/mock 模式、一鍵開瀏覽器與停止。等同執行：

```powershell
cd c:\code\claude\AI4BI; $env:LLM_MODE="anthropic"; $env:ANTHROPIC_API_KEY="sk-ant-..."; python -m streamlit run ai4bi/ui/app.py --server.port 8502
```

> LLM 模式由 `LLM_MODE`（`mock`|`anthropic`）、`ANTHROPIC_API_KEY`、`ANTHROPIC_MODEL` 三個環境變數控制；未設或出錯會自動 fallback 回 mock。

## Current Implementation Status

### NativeApp 私有資料目錄（2026-10-05）

原 Streamlit UI 可選用 `AI4BI_DATA_ROOT`，必須是 App 來源目錄之外的絕對路徑。設定後，草稿、registry、published 與 outbox 使用該私有資料根；示範 blocks／semantic model 仍從 App 內容唯讀載入。首次只複製示範 registry，不搬入原有草稿或報表，也不覆寫已存在的私有 registry。未設定時保留既有獨立執行路徑。

NativeApp 接入包由 `C:\code\claude\nativeApp_v2\integrations\ai4bi-streamlit` 維護；`LLM_MODE=mock` 是快測選項，不代表真 LLM 驗收。路徑與草稿／發布聚焦測試 18 項通過（2.87 秒）；殼內與發布驗證以 NativeApp 的 `docs/validation/implementation-status.md` 為準。

The platform is well past the original P0–R022 MVP. As of **Round 166** the
non-e2e suite is **1118 passing** (plus a Playwright E2E suite that needs a live
server). Highlights since the MVP:

- **Power BI parity (R041–137):** global slicers, semantic cross-filter,
  derived/calculated metrics, time-intelligence (WoW/MoM/YoY, calendar YoY),
  what-if parameters, bookmarks, drill-down & cross-page drill-through,
  conditional formatting, KPI targets/pacing, Excel/PDF export, more chart types
  (pivot, histogram, map, small-multiples, scatter), and a chart Format pane
  (axis range/scale, data labels, legend, reference baseline).
- **Conversational analytics (R078–110):** an NL "direct answer" engine, executor
  `HAVING` (measure filters), Top-N / per-group Top-N, RFM/churn, market-basket,
  cohort/funnel, change decomposition, seasonality, anomaly/digest — all routed
  through a `SchemaIndex` so they generalize beyond the demo dataset.
- **Domain validation:** semiconductor-fab scenarios (`crossfact`/`spc` engines)
  and a retail demo, each multi-agent scored to ≥95 (see `docs/fab-*.md`).
- **UI/UX redesign (R147–162):** Power BI-style view-mode IA
  (🔍探索 / 🗂️資料 / 🔗模型 / 📊分析 / 📤分享), drag-and-drop field well, unified
  data-source manager, per-visual edit & Format pane.
- **Design system (R164–166):** 6 switchable, color-blind-safe themes + a live
  picker, WCAG-checked contrast (incl. luminance-based button text), professional
  table headers. See [`docs/theme-ux-validation.md`](docs/theme-ux-validation.md).

Per-round detail is in [`docs/design-council-log.md`](docs/design-council-log.md)
and the validation logs under [`docs/`](docs/).

## Architecture

```
AI4BI/
├── ai4bi/
│   ├── blocks/          # Model: DataBlockContract, BlockLoader, registry, datastore, upgrade_validator
│   ├── planning/        # Control: FanoutGuard, SafeJoinPlanner, composition_plan
│   ├── analysis/        # Control: Executor (DuckDB SQL) + pandas engines —
│   │                    #   time_intelligence, trends, segments, rfm, cohort, funnel,
│   │                    #   basket, capacity, crossfact/cross_fact, spc, geo, postprocess,
│   │                    #   summary, alerts, excel_export, pdf_export
│   ├── ai/              # NL→spec: nl2proposal, intent_models, schema_index, llm_adapter, suggestions
│   ├── report/          # Model/Control: models, builder, proposals, publication, templates,
│   │                    #   metric_catalog, block_library, drillthrough, auth, scheduler
│   ├── routing/         # Control: prompt_router
│   ├── query_spec.py    # BlockRef, VisualQuerySpec, VisualizationSpec, HavingSpec
│   ├── spec_models.py   # PatchProposal, apply_proposal, PageSpec
│   └── ui/              # View: Streamlit
│       ├── app.py       # Main entry point (view-mode IA, canvas, NL ask box)
│       ├── theme.py     # Design system: themes, colorway, app_css, on_color (R164–166)
│       ├── workspace.py / state_manager.py  # Session state (undo/redo/staging)
│       ├── cache.py     # QueryCache (L1 @st.cache_data + L2 session_state)
│       ├── render_visual.py  # Visual dispatcher
│       ├── data_model.py     # Data-source manager, join builder, semantic model
│       ├── *_panel.py        # analysis/slicer/bookmark/what-if/rfm/cohort/… panels
│       └── components/  # kpi_card, line/bar/pie/scatter/histogram/map/small_multiples,
│                        #   data_table, pivot_table, filter_bar, field_well (React/TS)
├── data/semiconductor_demo/   # Demo dataset (blocks/, semantic_model.json, baselines.json)
├── .streamlit/config.toml     # Startup theme chrome (R164–166)
├── docs/                      # spec.md, design-council-log.md, validation logs
└── tests/                     # ~1118 non-e2e + Playwright E2E (tests/e2e, needs live server)
```

## MVC Layering

| Layer | Role | Components |
|-------|------|-----------|
| **Model** | Trusted data building blocks and semantic truth | `DataBlockContract`, `semantic_model.json`, metric definitions, certified relationships |
| **Control** | User intent → valid analysis behavior | `VisualQuerySpec`, `SafeJoinPlanner`, `Executor`, `StateManager` |
| **View** | Interactive BI authoring surface | Streamlit canvas, prompt command area, KPI/trend/chart/table visuals |
| **AI Assistant** | Suggests controlled spec/style edits | `PromptRouter`, `prompt_to_proposal()` — Proposal Author only, never semantic authority |

## Demo: ETCH Queue-Time Explorer

The current working demo answers: _Which tools have longer ETCH queue time?_

- **Blocks**: `process_move_fact` + certified joins to `tool_dim`, `process_step_dim`
- **Visuals**: 2 KPI cards, time trend, tool comparison bar chart, detail table
- **Controls**: Process step slicer, product family slicer, breakdown selector
- **Prompt examples**: `把趨勢線改成紅色`, `只看 ETCH`, `依供應商比較等待時間`
- **Baselines**: ETCH-01 = 2.0 hr queue time, ETCH-02 = 4.0 hr queue time

## What Is NOT Yet Available

Boundaries that remain **out of scope or infrastructure-dependent** (not gaps an
incremental round can close):

| Feature | Status |
|---------|--------|
| Enterprise RLS / SSO via an identity provider | Out of scope — a local `auth.User` + parameterized row-filter (`Executor._rls_predicates`) ships as the implementable stand-in; real IdP integration is future |
| Scheduled email delivery backend (SMTP daemon / cron) | `report/scheduler.py` builds & queues digests behind a `Transport` interface; a real `SMTPTransport` + OS scheduler is deployment-layer |
| Mobile-native / multi-theme app shell | Theme system ships (R164–166); responsive mobile layout is future |
| Full LLM semantic authority | **Permanently** out of scope — the LLM is a Proposal Author only, never semantic authority |
| Fact-to-fact detail join | **Permanently refused** (fan-out safety) |
| `AVG(yield_pct)` aggregation | **Permanently refused** — use `SUM(good_die)/SUM(tested_die)` |

> **Integration note:** `analysis/cross_fact.py` (base CTE composition) and
> `analysis/crossfact.py` (higher-level commonality/correlation/cohort, built on
> top of it) are *different* modules with confusingly similar names — check which
> one you mean before importing.

## Design Decisions Log

All design discussions are in [`docs/design-council-log.md`](docs/design-council-log.md) — a continuously-updated append-only council log across Rounds 000–012. Each round records consensus, code delivered, open questions, and the next-round prompt.

## Development Workflow

Each round follows this sequence:
1. Launch 4 parallel design/implementation agents
2. Collect results, synthesize into `docs/design-council-log.md`
3. Run `python -m pytest tests/ -q` — must pass
4. `git add -A && git commit && git push`
5. Start next round
