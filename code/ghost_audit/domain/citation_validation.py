"""Validate request coverage and citation availability without file I/O."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from ghost_audit.domain.evidence_index import EvidenceIndex
from ghost_audit.domain.models import DeletionRequest

from ghost_audit.domain.output_contract import OutputRow, OutputStep


@dataclass(frozen=True)
class CitationCheck:
    """Diagnostics outside steps_json. Resource linkage never proves a state."""

    case_id: str
    step_no: int
    evidence_id: str
    parsing_status: Literal["parsed", "deferred"]
    # 'coverage': an absence check cites a complete listing that omits the resource.
    resource_support: Literal["linked", "coverage", "unknown"]
    state_support: Literal["unverified"] = "unverified"


_LISTINGS: dict[int, dict] = {}


def omitted_from_listing(
    evidence: EvidenceIndex, evidence_id: str, system_id: str, resource_id: str, cutoff: datetime
) -> bool:
    """The cited file holds a point-in-time copy of the resource's collection (a SQL
    snapshot table or a JSON collection snapshot), captured by the cutoff, that does not
    contain the resource."""
    from ghost_audit.domain.submission_semantics import prefix
    from ghost_audit.domain.snapshot_inventory import snapshot_listings

    listings = _LISTINGS.get(id(evidence))
    if listings is None or listings.get("index") is not evidence:
        listings = _LISTINGS[id(evidence)] = {
            "index": evidence,
            "listings": snapshot_listings(evidence.observations),
        }
    return any(
        item.evidence_id == evidence_id
        and item.captured_at is not None
        and item.captured_at <= cutoff
        and item.at is not None
        and item.at <= cutoff
        and resource_id not in item.ids
        for item in listings["listings"].get((system_id, prefix(resource_id)), ())
    )


def check_citation(
    case_id: str, step: OutputStep, cutoff: datetime, evidence: EvidenceIndex
) -> CitationCheck:
    entry = evidence.registry.get(step.evidence_id)
    if entry is None:
        raise ValueError(f"{case_id}: unknown evidence citation: {step.evidence_id}")
    if entry.captured_at is None:
        raise ValueError(f"{case_id}: evidence availability is unknown at audit_at")
    if entry.captured_at > cutoff:
        raise ValueError(f"{case_id}: future evidence citation: {step.evidence_id}")

    candidates = evidence.lookup(evidence_id=step.evidence_id, expand_traces=True)
    candidates = [
        item
        for item in candidates
        if item.kind != "identity" or item.provenance.file_path == "user_audit_log.csv"
    ]
    visible = [
        item for item in candidates if item.available_at is not None and item.available_at <= cutoff
    ]

    def linked(item):
        return any(
            resource.resource_id == step.resource_id
            and resource.system_id in (None, step.system_id)
            for resource in item.resources
        )

    resource_linked = any(linked(item) for item in visible)
    if (
        not resource_linked
        and step.operation == "VERIFY_RECORD_ABSENT"
        and omitted_from_listing(
            evidence, step.evidence_id, step.system_id, step.resource_id, cutoff
        )
    ):
        return CitationCheck(
            case_id, step.step_no, step.evidence_id, entry.parsing_status, "coverage"
        )
    if not resource_linked:
        if any(linked(item) for item in candidates):
            raise ValueError(
                f"{case_id}: future cited resource observation is after audit_at or unavailable"
            )
        if any(item.resources for item in visible):
            raise ValueError(f"{case_id}: evidence refers exclusively to unrelated resources")
        if any(item.resources for item in candidates) or (candidates and not visible):
            raise ValueError(
                f"{case_id}: future evidence observations are after audit_at or unavailable"
            )
    return CitationCheck(
        case_id,
        step.step_no,
        step.evidence_id,
        entry.parsing_status,
        "linked" if resource_linked else "unknown",
    )


def validate_output(
    rows: list[OutputRow], requests: list[DeletionRequest], evidence: EvidenceIndex | None = None
) -> list[CitationCheck]:
    """Validate structure/time/linkage; return explicit unverified state diagnostics."""
    expected = {request.case_id: request for request in requests}
    if len(expected) != len(requests):
        raise ValueError("duplicate request case_id")
    if len(rows) != len(expected) or [row.case_id for row in rows] != sorted(expected):
        raise ValueError("output must contain exactly one sorted row per request")
    checks = []
    for row in rows:
        # Revalidate even if a caller used model_copy/model_construct or mutated a list.
        OutputRow.model_validate(row.model_dump())
        if evidence is None:
            continue
        cutoff = expected[row.case_id].audit_at
        for step in row.steps:
            if not step.evidence_id:
                continue
            checks.append(check_citation(row.case_id, step, cutoff, evidence))
    return checks
