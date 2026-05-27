"""Allowlisted report changes generated from controls or prompt text."""

from __future__ import annotations

from dataclasses import dataclass

from ai4bi.report_models import (
    ExecutableReportSpec,
    ReportChange,
    ReportProposal,
)


@dataclass(frozen=True)
class ProposalResult:
    proposal: ReportProposal | None
    message: str


def _control_change(
    report: ExecutableReportSpec,
    control_id: str,
    value,
    label: str,
) -> ReportChange | None:
    previous = report.controls[control_id].value
    if previous == value:
        return None
    return ReportChange(f"controls/{control_id}/value", label, previous, value, True)


def controls_to_proposal(
    report: ExecutableReportSpec,
    *,
    steps: list[str],
    products: list[str],
    breakdown: str,
) -> ReportProposal | None:
    changes = [
        change
        for change in [
            _control_change(report, "process_step", steps, "Process step"),
            _control_change(report, "product_family", products, "Product family"),
            _control_change(report, "breakdown", breakdown, "Comparison breakdown"),
        ]
        if change is not None
    ]
    previous_breakdown = report.controls["breakdown"].value
    if breakdown != previous_breakdown:
        before_column = "vendor" if previous_breakdown == "Vendor" else "tool_id"
        before_label = previous_breakdown
        after_column = "vendor" if breakdown == "Vendor" else "tool_id"
        changes.extend(
            [
                ReportChange(
                    "pages/main/visuals/bar_queue_by_tool_dimension/query/dimensions",
                    "Bar breakdown query",
                    [{"block_id": "tool_dim", "column_name": before_column, "alias": before_label, "truncate_date_to": None}],
                    [{"block_id": "tool_dim", "column_name": after_column, "alias": breakdown, "truncate_date_to": None}],
                    True,
                ),
                ReportChange(
                    "pages/main/visuals/bar_queue_by_tool_dimension/visualization/title",
                    "Bar title",
                    f"Queue Time by {before_label}",
                    f"Queue Time by {breakdown}",
                    False,
                ),
            ]
        )
    if not changes:
        return None
    return ReportProposal("Manual report control update", changes)


def prompt_to_proposal(
    prompt: str,
    report: ExecutableReportSpec,
    selected_component_id: str,
) -> ProposalResult:
    normalized = prompt.strip().upper()
    if not normalized:
        return ProposalResult(None, "Enter a report change to create a proposal.")
    if any(term in normalized for term in ("YIELD", "良率", "JOIN", "SQL")):
        return ProposalResult(
            None,
            "This request needs a governed metric or relationship workflow and cannot execute in this draft.",
        )

    changes: list[ReportChange] = []
    steps = [step for step in ("PHOTO", "ETCH", "CVD") if step in normalized]
    if steps:
        change = _control_change(report, "process_step", steps, "Process step")
        if change:
            changes.append(change)
    products = [family for family in ("Logic-A", "Logic-B") if family.upper() in normalized]
    if products:
        change = _control_change(report, "product_family", products, "Product family")
        if change:
            changes.append(change)
    if "供應商" in prompt or "VENDOR" in normalized:
        breakdown_proposal = controls_to_proposal(
            report,
            steps=report.controls["process_step"].value,
            products=report.controls["product_family"].value,
            breakdown="Vendor",
        )
        if breakdown_proposal:
            changes.extend(breakdown_proposal.changes)
    if "紅" in prompt or "RED" in normalized:
        if selected_component_id != "line_queue_by_day":
            return ProposalResult(None, "Select Queue-Time Trend before changing its line style.")
        current_color = report.pages["main"].visuals["line_queue_by_day"].visualization.extra.get("line_color")
        if current_color != "#D62728":
            changes.append(
                ReportChange(
                    "pages/main/visuals/line_queue_by_day/visualization/extra/line_color",
                    "Trend line color",
                    current_color,
                    "#D62728",
                    False,
                )
            )
    if "RESET" in normalized or "重設" in prompt:
        reset = controls_to_proposal(
            report,
            steps=["ETCH"],
            products=["Logic-A", "Logic-B"],
            breakdown="Tool ID",
        )
        changes = reset.changes if reset else []
        current_color = report.pages["main"].visuals["line_queue_by_day"].visualization.extra.get("line_color")
        if current_color is not None:
            changes.append(
                ReportChange(
                    "pages/main/visuals/line_queue_by_day/visualization/extra/line_color",
                    "Trend line color",
                    current_color,
                    None,
                    False,
                )
            )
    if not changes:
        return ProposalResult(None, "No supported report change was detected.")
    return ProposalResult(
        ReportProposal("Prompt proposal", changes, selected_component_id),
        "Proposal created. Review the diff before applying it.",
    )
