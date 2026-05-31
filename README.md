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

| Sprint | Status | Highlights | Tests |
|--------|--------|-----------|-------|
| **P0** | ✅ Done | `DataBlockContract` (10 block types), `BlockLoader`, `FanoutGuard` | 26 |
| **P1** | ✅ Done | `StateManager` (undo/redo/staging), `ReportSpec`/`PageSpec`, `PatchProposal` | +48 |
| **P2** | ✅ Done | `VisualQuerySpec` (block_refs), `QueryCache` (L1+L2), kpi_card / line_chart / filter_bar | +41 |
| **P3** | ✅ Done | `bar_chart`, `data_table`, semiconductor demo dataset (6 dim + 2 fact) | +13 |
| **Round 010** | ✅ Done | Semiconductor data product (process_move_fact + wafer_yield_fact + 6 dims) | +29 |
| **Round 011** | ✅ Done | Governed Join Planner, ETCH Queue-Time Canvas (KPI + trend + bar + table) | +30 |
| **Round 012** | ✅ Done | `ExecutableReportSpec`, proposal workflow, undo/redo, local draft save/load | +39 |
| **Round 013** | ✅ Done | `CatalogBrowser`, `build_visual_from_selection`, `PublicationGate` (5 checks), `ReadonlyMode`, `CompositionPlanner`/`CompositionExecutor` (CTE cross-fact SQL), `RatioMetricExpr` | +54 |
| **Round 014** | ✅ Done | `visual_order` dynamic canvas, `build_add_visual_proposal`, filter inheritance, `AuditMetadata`, `pin_block_version_proposal`, `grain_check()`, parameterized SQL in `CompositionExecutor` | +37 |
| **Round 015** | ✅ Done | `PublishedReportStore` (share URL), `unpin_block_version_proposal`, Pin versions sidebar, `move_visual_up/down`, reorder proposal, `ANALYST_NAME` identity | +27 |
| **Round 016** | ✅ Done | `global_filters`/`merged_filters()`, `build_global_filter_proposal`, title editing proposal, `created_at` first-save fix, `display_name`/`add_page()`, multi-page `st.tabs()` canvas | +34 |
| **Round 017** | ✅ Done | `cross_filter_emit`, page-scoped `cross_filters`, page delete proposal, published snapshot browser/load, published readonly URL fix | +15 |
| **Round 018** | ✅ Done | `MetricCatalogService` (3-zone: certified_ready/needs_blocks/sandbox), Metric Catalog sidebar panel, sandbox amber banner, per-visual 🔬 badge, Playwright E2E test suite | +25 (14 unit + 11 E2E) |
| **Round 019** | ✅ Done | NL2 intent: `chart_type_change` (bar↔line), `dimension_change` (月份/週/日), `add_metric` (owner_block certified check, max 3); new `visualization/visual_type` + `query/metrics` paths; `_store_visual_assistant_context` hot-reload fix | +38 (28 unit + 10 E2E) |
| **Round 020** | ✅ Done | `validate_upgrade()` breaking change detection (004-A: forbidden/breaking/non-breaking/none); NL2 `date_filter_change` intent (最近3個月/last quarter/ytd, `global_filters/date_range`, deterministic) | +60 (54 unit + 6 E2E) |
| **Round 021** | ✅ Done | Data Block View sidebar panel (`BlockCard`, `LIFECYCLE_BADGE` × 5, `BLOCK_TYPE_ICON` × 10, `build_block_library()` with search + certified-first sort); R2 bridge feature (001-F) | +32 (23 unit + 9 E2E) |
| **Round 022** | ✅ Done | NL2 expanded coverage: `rename_visual`, `remove_metric` (≥1 metric guard), `categorical_dimension_change` (certified whitelist), `value_filter_change` (step_id PHOTO/ETCH/CVD), broader `add_metric` keywords; `query/filters` path; intent routing priority fix | +52 (39 unit + 13 E2E) |

**Total tests: 473 unit + 49 E2E passing** (updated each round)

## Architecture

```
AI4BI/
├── ai4bi/
│   ├── blocks/          # Model: DataBlockContract, BlockLoader
│   ├── planning/        # Control: FanoutGuard, SafeJoinPlanner
│   ├── analysis/        # Control: Executor (DuckDB SQL)
│   ├── report/          # Model/Control: ExecutableReportSpec, Proposals, Templates
│   ├── routing/         # Control: PromptRouter
│   ├── query_spec.py    # BlockRef, VisualQuerySpec, VisualizationSpec
│   ├── spec_models.py   # PatchProposal, apply_proposal, PageSpec
│   └── ui/              # View: Streamlit
│       ├── app.py       # Main entry point
│       ├── workspace.py # Session state (undo/redo/staging)
│       ├── cache.py     # QueryCache (L1 @st.cache_data + L2 session_state)
│       ├── render_visual.py  # Visual dispatcher
│       └── components/  # kpi_card, line_chart, bar_chart, data_table, filter_bar
├── data/semiconductor_demo/   # Demo dataset
│   ├── blocks/          # 8 DataBlock JSON files (6 dim + 2 fact)
│   ├── semantic_model.json    # Certified relationships
│   └── baselines.json   # Expected query results
├── docs/
│   ├── design-council-log.md  # Append-only multi-agent design decisions (Rounds 000–012)
│   ├── spec.md          # Formal product/contract specification
│   └── wireframe-review.md    # GUI design decisions
└── tests/               # 128 tests
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

| Feature | Status |
|---------|--------|
| Cross-fact composition (queue time vs yield) | Implemented Round 013 (`CompositionPlanner`) |
| Published/shared reports | Basic publish/share URL and snapshot browser implemented; team lifecycle policy still future |
| BlockRegistry with `_meta.json` | Implemented Round 014/015 (`FilesystemBlockRegistry`) |
| Arbitrary visual builder from catalog | Implemented Round 013 (`build_visual_from_selection`) |
| Full LLM semantic authority | Out of scope (Proposal Author only) |
| Fact-to-fact detail join | Permanently refused |
| `AVG(yield_pct)` aggregation | Permanently refused (use `SUM(good_die)/SUM(tested_die)`) |

## Design Decisions Log

All design discussions are in [`docs/design-council-log.md`](docs/design-council-log.md) — a continuously-updated append-only council log across Rounds 000–012. Each round records consensus, code delivered, open questions, and the next-round prompt.

## Development Workflow

Each round follows this sequence:
1. Launch 4 parallel design/implementation agents
2. Collect results, synthesize into `docs/design-council-log.md`
3. Run `python -m pytest tests/ -q` — must pass
4. `git add -A && git commit && git push`
5. Start next round
