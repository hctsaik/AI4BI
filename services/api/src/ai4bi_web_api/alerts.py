"""Evaluate user threshold alerts against an immutable report snapshot."""
from __future__ import annotations

from pathlib import Path

from .errors import AppError


def run_alerts(root: Path, snapshot: dict) -> dict:
    from .publications import check_execution_runtime
    from .core import load_contracts
    from .report_extensions import report_executor, ordered_report
    from ai4bi.analysis.alerts import AlertRule, evaluate_alerts
    from ai4bi.blocks.contracts import BlockType

    check_execution_runtime(root, snapshot)
    contracts = load_contracts(root, snapshot["datasets"])
    report = ordered_report(snapshot["report"])
    executor, enriched = report_executor(report, contracts)
    rules = []
    seen = set()
    for item in snapshot.get("alert_rules", []):
        rule_id = item["rule_id"]
        if rule_id in seen:
            raise AppError("INVALID_ALERT_RULE", "提醒識別碼不可重複。")
        seen.add(rule_id)
        contract = enriched.get(item["block_id"])
        metric = next((value for value in contract.metrics if value.name == item["metric_name"]), None) if contract else None
        if (contract is None or contract.block_type not in (BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact)
                or metric is None):
            raise AppError("INVALID_ALERT_RULE", "提醒引用了目前報表中不存在的事實指標。")
        if item.get("filter_column") and item["filter_column"] not in {column.name for column in contract.columns}:
            raise AppError("INVALID_ALERT_RULE", "提醒範圍引用了目前資料來源中不存在的欄位。")
        rules.append(AlertRule(
            rule_id=rule_id,
            block_id=item["block_id"],
            metric_name=metric.name,
            metric_label=metric.description or metric.name,
            operator=item["operator"],
            threshold=item["threshold"],
            unit=metric.unit or None,
            filter_column=item.get("filter_column"),
            filter_value=item.get("filter_value"),
        ))

    evaluated = evaluate_alerts(executor, rules)
    return {
        "alerts": [{
            "rule_id": result.rule.rule_id,
            "block_id": result.rule.block_id,
            "metric_name": result.rule.metric_name,
            "value": result.value,
            "fired": result.fired,
            "message": result.message,
        } for result in evaluated],
        "snapshot_id": snapshot["snapshot_id"],
        "revision": snapshot["revision"],
        "data_versions": {item["dataset_id"]: item["version"] for item in snapshot["datasets"]},
    }
