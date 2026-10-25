"""Independent synthetic output cases builders; never sample answers."""

from ghost_audit.domain.models import DeletionRequest
from ghost_audit.domain.output_contract import OPERATIONS, OutputStep


def step(operation="VERIFY_RECORD_ABSENT", **overrides):
    phase, state = OPERATIONS.get(operation, ("VERIFICATION", "ABSENT"))
    return OutputStep.model_validate(
        {
            "step_no": 1,
            "phase": phase,
            "system_id": "account_service",
            "resource_id": "record_x",
            "operation": operation,
            "state": state,
            "evidence_id": "fixture_file",
            **overrides,
        }
    )


def request(**overrides):
    return DeletionRequest.model_validate(
        {
            "case_id": "fixture_case",
            "email": "fictional@example.invalid",
            "requested_at": "2026-01-01T00:00:00Z",
            "reported_status": "COMPLETE",
            "reported_at": "2026-01-01T01:00:00Z",
            "audit_at": "2026-01-03T00:00:00Z",
            "request_text": "Delete my personal data.",
            **overrides,
        }
    )
