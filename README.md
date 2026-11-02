# AI4BI — Headless Analytics Platform

A governed, AI-assisted BI platform where data scientists deliver reusable JSON DataBlocks and business users compose multi-source analysis dashboards without custom GUI code.

## Quick Start

The supported local app is React Web served by the Python API. From the repository root:

```bash
npm ci
python -m pip install -e . -e services/api
python scripts/build_app.py
python scripts/serve_dev.py
```

Open the printed `http://127.0.0.1:<port>` URL and enter the local pairing code
printed by the server. The build embeds React assets in the Python package; the
runtime does not need a Vite development server or the Streamlit dependency.

On Windows, after this first build, `launch.hta` can start the same API, open the
browser and stop its process. The pairing code remains in the server console.

### Legacy parity tests

The old Streamlit UI is retained as an internal behavior reference while React
parity work continues. It is not a supported app launch path. Install the
development extra only when running those legacy regression tests:

```bash
python -m pip install -e ".[dev]" -e services/api
python -m pytest tests/ -q
npm run test:web
```

## Existing Analysis Semantics

These capabilities describe the existing Python analysis engine and are the
behavioral reference for the React migration. They do not mean the React UI has
feature parity; current migration progress and validation limits are tracked in
[`docs/implementation-plan.md`](docs/implementation-plan.md).

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
├── apps/web/                 # React + TypeScript interface
├── services/api/             # FastAPI local runtime and analysis adapters
├── scripts/                  # build and local startup
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
│   └── ui/              # Legacy Streamlit reference; not the supported app UI
│       ├── app.py       # Legacy entry point retained for parity testing
│       ├── theme.py     # Design system: themes, colorway, app_css, on_color (R164–166)
│       ├── workspace.py / state_manager.py  # Session state (undo/redo/staging)
│       ├── cache.py     # QueryCache (L1 @st.cache_data + L2 session_state)
│       ├── render_visual.py  # Visual dispatcher
│       ├── data_model.py     # Data-source manager, join builder, semantic model
│       ├── *_panel.py        # analysis/slicer/bookmark/what-if/rfm/cohort/… panels
│       └── components/  # kpi_card, line/bar/pie/scatter/histogram/map/small_multiples,
│                        #   data_table, pivot_table, filter_bar, field_well (React/TS)
├── data/semiconductor_demo/   # Demo dataset (blocks/, semantic_model.json, baselines.json)
├── .streamlit/config.toml     # Legacy reference UI configuration
├── docs/                      # spec.md, design-council-log.md, validation logs
├── tests/                     # Core and legacy UI regression tests
├── tests/web/                 # React unit tests
└── tests/e2e/                 # Playwright browser workflows
```

## MVC Layering

| Layer | Role | Components |
|-------|------|-----------|
| **Model** | Trusted data building blocks and semantic truth | `DataBlockContract`, `semantic_model.json`, metric definitions, certified relationships |
| **Control** | User intent → valid analysis behavior | `VisualQuerySpec`, `SafeJoinPlanner`, `Executor`, `StateManager` |
| **View** | Interactive BI authoring surface | React Web canvas, prompt command area, KPI/trend/chart/table visuals |
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

1. Install the Python API and React workspace dependencies.
2. Run `python scripts/build_app.py` to generate API types and embed the React build.
3. Run `python scripts/serve_dev.py` and use the local URL and pairing code it prints.
4. Run the focused API, React, and browser checks for the behavior being changed.
