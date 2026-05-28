"""Allowlisted report changes generated from controls or prompt text."""

from __future__ import annotations

from dataclasses import dataclass

from ai4bi.report.models import (
    ExecutableReportSpec,
    ReportChange,
    ReportProposal,
    ReportValidationError,
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


def build_title_proposal(
    current_title: str,
    new_title: str,
) -> ReportProposal:
    """Creates a proposal to rename the report title. affects_data=False."""
    change = ReportChange(
        path="title",
        label="Report title",
        before=current_title,
        after=new_title,
        affects_data=False,
    )
    return ReportProposal(
        description=f"Rename report title to '{new_title}'",
        changes=[change],
    )


def pin_block_version_proposal(
    report: ExecutableReportSpec,
    page_id: str,
    visual_id: str,
    block_id: str,
    certified_version: str,
    pin_reason: str = "manually pinned by user",
) -> ReportProposal:
    """
    Creates a proposal that pins the BlockRef for block_id in the given visual
    to certified_version.
    """
    # Validate the page / visual / block_id exist upfront so we raise early.
    page = report.pages.get(page_id)
    if page is None:
        raise ReportValidationError(f"Page '{page_id}' not found in report.")
    visual = page.visuals.get(visual_id)
    if visual is None:
        raise ReportValidationError(f"Visual '{visual_id}' not found on page '{page_id}'.")
    matching = [ref for ref in visual.query.block_refs if ref.block_id == block_id]
    if not matching:
        raise ReportValidationError(
            f"BlockRef '{block_id}' not found in visual '{visual_id}' on page '{page_id}'."
        )
    current_version = matching[0].pinned_version
    path = f"pages/{page_id}/visuals/{visual_id}/query/block_refs/{block_id}/pinned_version"
    change = ReportChange(
        path=path,
        label=f"Pin {block_id} to version {certified_version}",
        before=current_version,
        after=certified_version,
        affects_data=False,
    )
    return ReportProposal(
        description=f"Pin block '{block_id}' to version {certified_version} ({pin_reason})",
        changes=[change],
    )


def unpin_block_version_proposal(
    report: ExecutableReportSpec,
    page_id: str,
    visual_id: str,
    block_id: str,
) -> ReportProposal:
    """Creates a proposal that clears pinned_version and pin_reason for block_id in the given visual."""
    page = report.pages.get(page_id)
    if page is None:
        raise ReportValidationError(f"Page '{page_id}' not found in report.")
    visual = page.visuals.get(visual_id)
    if visual is None:
        raise ReportValidationError(f"Visual '{visual_id}' not found on page '{page_id}'.")
    matching = [ref for ref in visual.query.block_refs if ref.block_id == block_id]
    if not matching:
        raise ReportValidationError(
            f"BlockRef '{block_id}' not found in visual '{visual_id}' on page '{page_id}'."
        )
    current_version = matching[0].pinned_version
    path = f"pages/{page_id}/visuals/{visual_id}/query/block_refs/{block_id}/pinned_version"
    change = ReportChange(
        path=path,
        label=f"Unpin {block_id}",
        before=current_version,
        after=None,
        affects_data=False,
    )
    return ReportProposal(
        description=f"Unpin block '{block_id}' (restore to latest certified)",
        changes=[change],
    )


def build_page_rename_proposal(
    page_id: str,
    current_name: str,
    new_name: str,
) -> ReportProposal:
    """Renames a page's display_name. affects_data=False."""
    change = ReportChange(
        path=f"pages/{page_id}/display_name",
        label=f"Rename page '{page_id}' display name",
        before=current_name,
        after=new_name,
        affects_data=False,
    )
    return ReportProposal(
        description=f"Rename page '{page_id}' to '{new_name}'",
        changes=[change],
    )


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
