"""Output contracts and canonical serialization, independent of prediction logic."""

import csv
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .csvio import read_csv
from .index import EvidenceIndex
from .models import DeletionRequest, Identifier, StrictModel

# Insertion order is the operation order in problem_statement.md.
OPERATIONS = {
    "REPORT_REMAINING_RECORD": ("FINDING", "PRESENT"),
    "REPORT_EXPOSED_PII": ("FINDING", "PRESENT"),
    "REPORT_ACTIVE_DATA_FLOW": ("FINDING", "ACTIVE"),
    "REPORT_RESTORE_RISK": ("FINDING", "ACTIVE"),
    "DISABLE_DATA_FLOW": ("REMEDIATION", "DISABLED"),
    "BLOCK_RESTORE": ("REMEDIATION", "BLOCKED"),
    "DELETE_RECORD": ("REMEDIATION", "ABSENT"),
    "REDACT_RECORD": ("REMEDIATION", "REDACTED"),
    "ANONYMIZE_RECORD": ("REMEDIATION", "ANONYMIZED"),
    "VERIFY_RECORD_ABSENT": ("VERIFICATION", "ABSENT"),
    "VERIFY_RECORD_PRESENT": ("VERIFICATION", "PRESENT"),
    "VERIFY_RECORD_REDACTED": ("VERIFICATION", "REDACTED"),
    "VERIFY_RECORD_ANONYMIZED": ("VERIFICATION", "ANONYMIZED"),
    "VERIFY_DATA_FLOW_DISABLED": ("VERIFICATION", "DISABLED"),
    "VERIFY_RESTORE_BLOCKED": ("VERIFICATION", "BLOCKED"),
}
OPERATION_ORDER = {operation: index for index, operation in enumerate(OPERATIONS)}
Operation = Literal[
    "REPORT_REMAINING_RECORD", "REPORT_EXPOSED_PII", "REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK",
    "DISABLE_DATA_FLOW", "BLOCK_RESTORE", "DELETE_RECORD", "REDACT_RECORD", "ANONYMIZE_RECORD",
    "VERIFY_RECORD_ABSENT", "VERIFY_RECORD_PRESENT", "VERIFY_RECORD_REDACTED", "VERIFY_RECORD_ANONYMIZED",
    "VERIFY_DATA_FLOW_DISABLED", "VERIFY_RESTORE_BLOCKED",
]


class OutputStep(StrictModel):
    step_no: int = Field(ge=1)
    phase: Literal["FINDING", "REMEDIATION", "VERIFICATION"]
    system_id: Identifier
    resource_id: Identifier
    operation: Operation
    state: Literal["PRESENT", "ACTIVE", "DISABLED", "BLOCKED", "ABSENT", "REDACTED", "ANONYMIZED"]
    evidence_id: str

    @model_validator(mode="after")
    def operation_contract(self):
        if OPERATIONS.get(self.operation) != (self.phase, self.state):
            raise ValueError("invalid phase/operation/state combination")
        if self.evidence_id and not self.evidence_id.strip():
            raise ValueError("evidence_id cannot be whitespace")
        return self


def step_key(step: OutputStep):
    return OPERATION_ORDER[step.operation], step.system_id, step.resource_id, step.evidence_id


def canonical_steps(steps: list[OutputStep]) -> list[OutputStep]:
    """Sort explicitly when constructing outputs; validation never repairs bad input."""
    return [OutputStep.model_validate({**step.model_dump(), "step_no": index})
            for index, step in enumerate(sorted(steps, key=step_key), 1)]


class OutputRow(StrictModel):
    case_id: Identifier
    deletion_status: Literal["COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"]
    steps: list[OutputStep]

    @model_validator(mode="after")
    def row_contract(self):
        if self.deletion_status == "NOT_APPLICABLE":
            if self.steps:
                raise ValueError("NOT_APPLICABLE requires []")
            return self
        if not self.steps:
            raise ValueError("authorized deletion requires evidence-backed steps")
        if [s.step_no for s in self.steps] != list(range(1, len(self.steps) + 1)):
            raise ValueError("step numbers must be consecutive from 1")
        if self.steps != sorted(self.steps, key=step_key):
            raise ValueError("steps are not in canonical phase/operation/system/resource order")
        identities = [(s.phase, s.operation, s.system_id, s.resource_id) for s in self.steps]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate steps")
        if self.deletion_status == "COMPLETE":
            if any(s.phase != "VERIFICATION" or not s.evidence_id for s in self.steps):
                raise ValueError("COMPLETE requires only evidence-backed verification")
        else:
            if {s.phase for s in self.steps} != {"FINDING", "REMEDIATION", "VERIFICATION"}:
                raise ValueError("INCOMPLETE requires all three phases")
            for step in self.steps:
                if (step.phase == "FINDING") != bool(step.evidence_id):
                    raise ValueError("only findings may cite evidence in INCOMPLETE")
        return self


OUTPUT_COLUMNS = ["case_id", "deletion_status", "steps_json"]


def read_output(path: Path) -> list[OutputRow]:
    rows = []
    seen = set()
    for number, row in enumerate(read_csv(path, OUTPUT_COLUMNS), 2):
        try:
            steps = json.loads(row['steps_json'])
            parsed = OutputRow(case_id=row['case_id'], deletion_status=row['deletion_status'], steps=steps)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{path.name}: invalid output row {number}") from exc
        if parsed.case_id in seen:
            raise ValueError(f"{path.name}: duplicate case_id")
        seen.add(parsed.case_id)
        rows.append(parsed)
    if [row.case_id for row in rows] != sorted(seen):
        raise ValueError(f"{path.name}: rows must be sorted by case_id")
    return rows


@dataclass(frozen=True)
class CitationCheck:
    """Diagnostics outside steps_json. Resource linkage never proves a state."""

    case_id: str
    step_no: int
    evidence_id: str
    parsing_status: Literal['parsed', 'deferred']
    # 'coverage': an absence check cites a complete listing that omits the resource.
    resource_support: Literal['linked', 'coverage', 'unknown']
    state_support: Literal['unverified'] = 'unverified'


_LISTINGS: dict[int, dict] = {}


def omitted_from_listing(evidence: EvidenceIndex, evidence_id: str, system_id: str,
                         resource_id: str, cutoff: datetime) -> bool:
    """The cited file holds a complete listing of the system's collection, captured by
    the cutoff, and that listing does not contain the resource."""
    from .temporal import coverage_surfaces

    surfaces = _LISTINGS.get(id(evidence))
    if surfaces is None or surfaces.get('index') is not evidence:
        surfaces = _LISTINGS[id(evidence)] = {'index': evidence, 'surfaces': coverage_surfaces(evidence.observations)}
    return any(surface.provenance.evidence_id == evidence_id and at is not None and at <= cutoff
               and resource_id not in ids
               for (system, _), values in surfaces['surfaces'].items() if system == system_id
               for at, surface, ids in values)


def check_citation(case_id: str, step: OutputStep, cutoff: datetime,
                   evidence: EvidenceIndex) -> CitationCheck:
    entry = evidence.registry.get(step.evidence_id)
    if entry is None:
        raise ValueError(f'{case_id}: unknown evidence citation: {step.evidence_id}')
    if entry.captured_at is None:
        raise ValueError(f'{case_id}: evidence availability is unknown at audit_at')
    if entry.captured_at > cutoff:
        raise ValueError(f'{case_id}: future evidence citation: {step.evidence_id}')

    candidates = evidence.lookup(evidence_id=step.evidence_id, expand_traces=True)
    candidates = [item for item in candidates if item.kind != 'identity'
                  or item.provenance.file_path == 'user_audit_log.csv']
    visible = [item for item in candidates if item.available_at is not None
               and item.available_at <= cutoff]

    def linked(item):
        return any(resource.resource_id == step.resource_id
                   and resource.system_id in (None, step.system_id) for resource in item.resources)

    resource_linked = any(linked(item) for item in visible)
    if not resource_linked and step.operation == 'VERIFY_RECORD_ABSENT' and omitted_from_listing(
            evidence, step.evidence_id, step.system_id, step.resource_id, cutoff):
        return CitationCheck(case_id, step.step_no, step.evidence_id, entry.parsing_status, 'coverage')
    if not resource_linked:
        if any(linked(item) for item in candidates):
            raise ValueError(f'{case_id}: future cited resource observation is after audit_at or unavailable')
        if any(item.resources for item in visible):
            raise ValueError(f'{case_id}: evidence refers exclusively to unrelated resources')
        if any(item.resources for item in candidates) or (candidates and not visible):
            raise ValueError(f'{case_id}: future evidence observations are after audit_at or unavailable')
    return CitationCheck(case_id, step.step_no, step.evidence_id, entry.parsing_status,
                         'linked' if resource_linked else 'unknown')


def validate_output(rows: list[OutputRow], requests: list[DeletionRequest],
                    evidence: EvidenceIndex | None = None) -> list[CitationCheck]:
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


def write_output(path: Path, rows: list[OutputRow], requests: list[DeletionRequest],
                 evidence: EvidenceIndex | None = None) -> None:
    ordered = sorted(rows, key=lambda row: row.case_id)
    validate_output(ordered, requests, evidence)
    # Validate everything before replacing any existing output.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="",
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
            writer.writeheader()
            for row in ordered:
                writer.writerow({"case_id": row.case_id, "deletion_status": row.deletion_status,
                                 "steps_json": json.dumps([s.model_dump() for s in row.steps],
                                                          ensure_ascii=False, separators=(",", ":"))})
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
