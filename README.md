# AI4BI — Headless Analytics Platform

A governed, AI-assisted BI platform where data scientists deliver reusable JSON DataBlocks and business users compose multi-source analysis dashboards without custom GUI code.

## Quick Start

```bash
pip install -e ".[dev]"
streamlit run ai4bi/ui/app.py          # ETCH Queue-Time Explorer demo
python -m pytest tests/ -q             # run full test suite
```

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
| **Round 014** | 🔄 In Progress | Dynamic Canvas (`visual_order`), BlockRegistry (`FilesystemBlockRegistry` + `_meta.json`), AggStep SQL hardening | — |

**Total tests: 197 passing** (updated each round)

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
| Published/shared reports | Planned (lifecycle gate ready, sharing not yet wired) |
| BlockRegistry with `_meta.json` | In Progress Round 014 (013-D retry) |
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
