"""Snapshot-backed adapter for the existing business-summary analysis."""
from __future__ import annotations

from pathlib import Path

from .errors import AppError


def run_summary(root: Path, snapshot: dict) -> dict:
    from .publications import check_execution_runtime
    from .core import load_contracts
    from .report_extensions import report_executor, ordered_report
    from ai4bi.analysis.alerts import AlertRule
    from ai4bi.analysis.summary import generate_summary
    from ai4bi.blocks.contracts import BlockType

    check_execution_runtime(root, snapshot)
    contracts = load_contracts(root, snapshot["datasets"])
    report = ordered_report(snapshot["report"])
    page_id = snapshot.get("page_id")
    page = report.get("pages", {}).get(page_id)
    if page is None:
        raise AppError("INVALID_PAGE", "找不到要產生摘要的報表頁面。")

    executor, enriched = report_executor(report, contracts, page_id=page_id)
    preferred_block_id = None
    for visual_id in page.get("visual_order", []):
        visual = page.get("visuals", {}).get(visual_id)
        refs = visual.get("query", {}).get("block_refs", []) if visual else []
        if refs:
            preferred_block_id = refs[0].get("block_id")
            break

    alert_rules = []
    for index, item in enumerate(snapshot.get("alert_rules", [])):
        contract = enriched.get(item["block_id"])
        metric = next((value for value in contract.metrics if value.name == item["metric_name"]), None) if contract else None
        if (contract is None or contract.block_type not in (BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact)
                or metric is None):
            raise AppError("INVALID_ALERT_RULE", "摘要提醒引用了目前報表中不存在的事實指標。")
        alert_rules.append(AlertRule(
            rule_id=f"summary-{index}", block_id=item["block_id"], metric_name=metric.name,
            metric_label=metric.description or metric.name, operator=item["operator"],
            threshold=item["threshold"], unit=metric.unit or None,
            filter_column=item.get("filter_column"), filter_value=item.get("filter_value"),
        ))

    summary = generate_summary(executor, enriched, period=snapshot["period"], alert_rules=alert_rules,
                               preferred_block_id=preferred_block_id)
    return {
        "summary_contract": "business-summary-v1",
        "title": summary.title,
        "generated_at": summary.generated_at,
        "period": summary.period,
        "markdown": summary.to_markdown(),
        "sections": [{"heading": section.heading, "lines": section.lines} for section in summary.sections],
        "snapshot_id": snapshot["snapshot_id"],
        "revision": snapshot["revision"],
        "page_id": page_id,
        "data_versions": {item["dataset_id"]: item["version"] for item in snapshot["datasets"]},
    }
