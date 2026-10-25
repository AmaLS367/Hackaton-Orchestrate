"""Official row and step invariants and deterministic canonical ordering."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from ghost_audit.domain.models import Identifier, StrictModel

Phase = Literal["FINDING", "REMEDIATION", "VERIFICATION"]
State = Literal["PRESENT", "ACTIVE", "DISABLED", "BLOCKED", "ABSENT", "REDACTED", "ANONYMIZED"]
DeletionStatus = Literal["COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"]


OPERATIONS: dict[Operation, tuple[Phase, State]] = {
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
    "REPORT_REMAINING_RECORD",
    "REPORT_EXPOSED_PII",
    "REPORT_ACTIVE_DATA_FLOW",
    "REPORT_RESTORE_RISK",
    "DISABLE_DATA_FLOW",
    "BLOCK_RESTORE",
    "DELETE_RECORD",
    "REDACT_RECORD",
    "ANONYMIZE_RECORD",
    "VERIFY_RECORD_ABSENT",
    "VERIFY_RECORD_PRESENT",
    "VERIFY_RECORD_REDACTED",
    "VERIFY_RECORD_ANONYMIZED",
    "VERIFY_DATA_FLOW_DISABLED",
    "VERIFY_RESTORE_BLOCKED",
]


class OutputStep(StrictModel):
    """Exactly the seven official step fields with a valid operation/state pair."""

    step_no: int = Field(ge=1)
    phase: Phase
    system_id: Identifier
    resource_id: Identifier
    operation: Operation
    state: Literal["PRESENT", "ACTIVE", "DISABLED", "BLOCKED", "ABSENT", "REDACTED", "ANONYMIZED"]
    evidence_id: str

    @model_validator(mode="after")
    def operation_contract(self) -> Self:
        if OPERATIONS.get(self.operation) != (self.phase, self.state):
            raise ValueError("invalid phase/operation/state combination")
        if self.evidence_id and not self.evidence_id.strip():
            raise ValueError("evidence_id cannot be whitespace")
        return self


def step_key(step: OutputStep) -> tuple[int, str, str, str]:
    return OPERATION_ORDER[step.operation], step.system_id, step.resource_id, step.evidence_id


def canonical_steps(steps: list[OutputStep]) -> list[OutputStep]:
    """Sort explicitly when constructing outputs; validation never repairs bad input."""
    return [
        OutputStep.model_validate({**step.model_dump(), "step_no": index})
        for index, step in enumerate(sorted(steps, key=step_key), 1)
    ]


class OutputRow(StrictModel):
    """One official case result with consecutive, canonical and citation-safe steps."""

    case_id: Identifier
    deletion_status: DeletionStatus
    steps: list[OutputStep]

    @model_validator(mode="after")
    def row_contract(self) -> Self:
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


REMEDIATION: dict[str, Operation] = {
    "DELETE": "DELETE_RECORD",
    "REDACT": "REDACT_RECORD",
    "ANONYMIZE": "ANONYMIZE_RECORD",
    "DISABLE": "DISABLE_DATA_FLOW",
    "BLOCK": "BLOCK_RESTORE",
}

VERIFICATION: dict[str, Operation] = {
    "DELETE": "VERIFY_RECORD_ABSENT",
    "RETAIN": "VERIFY_RECORD_PRESENT",
    "REDACT": "VERIFY_RECORD_REDACTED",
    "ANONYMIZE": "VERIFY_RECORD_ANONYMIZED",
    "DISABLE": "VERIFY_DATA_FLOW_DISABLED",
    "BLOCK": "VERIFY_RESTORE_BLOCKED",
}

FINDINGS: dict[str, Operation] = {
    "DELETE": "REPORT_REMAINING_RECORD",
    "REDACT": "REPORT_EXPOSED_PII",
    "ANONYMIZE": "REPORT_EXPOSED_PII",
    "DISABLE": "REPORT_ACTIVE_DATA_FLOW",
    "BLOCK": "REPORT_RESTORE_RISK",
}
