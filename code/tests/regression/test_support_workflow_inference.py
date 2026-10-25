"""A request's own pre-audit DELETE_RECORD weakly classifies an otherwise silent support record.

Synthetic fixtures only. The operation may choose SUPPORT_ATTACHMENT only when no time-valid
evidence classifies the record; it never establishes record state or completion.
"""

from collections.abc import Iterable

import pytest
from ghost_audit.application.submission_service import SubmissionPredictor
from ghost_audit.domain.models import Activity, DeletionRule, Observation
from ghost_audit.domain.submission_models import ResourceAssessment
from pydantic import JsonValue

from tests.fixtures.evidence_cases import LISTING, build, request, snapshot

EMAIL = "a@example.test"
# Final-result operations land 30-125 minutes after the request's reported_at (12:00).
IN_BATCH = "2026-03-02T12:45:00Z"
RECORD: dict[str, JsonValue] = {
    "resource_id": "support_1",
    "requester_email": EMAIL,
    "message_excerpt": "Customer contacted support about account access.",
}


def treatment(n: int, event: str, at: str = IN_BATCH, result: str = "FAILED") -> Activity:
    return Activity.model_validate(
        {
            "activity_id": f"activity_{n}",
            "event_time": at,
            "event_type": event,
            "source_system": "deletion_worker",
            "target_system": "support_platform",
            "resource_id": "support_1",
            "reported_result": result,
            "details": "Deletion worker received the final result for support_1 "
            "from support_platform.",
        }
    )


def record(
    row: dict[str, JsonValue] = RECORD,
    collection: str = "support_records",
    captured: str = LISTING,
) -> list[Observation]:
    return snapshot("inventory", captured, [("support_platform", collection, captured, [row])])


def assess(
    rules: list[DeletionRule],
    observations: Iterable[Observation],
    activities: Iterable[Activity],
    audit: str = "2026-03-10T12:00:00Z",
) -> tuple[ResourceAssessment, list[str], SubmissionPredictor]:
    p = SubmissionPredictor(
        build(rules, [request("case_1", EMAIL, audit=audit)], observations, activities)
    )
    case = p.evidence.dataset.requests[0]
    resources, notes = p.resources_for(case, "user_a")
    [assessment] = [
        a
        for a in p._assess_resources(case, "user_a", resources, notes)
        if a.resource.resource_id == "support_1"
    ]
    return assessment, notes, p


def test_attributed_delete_operation_classifies_a_silent_support_record(
    rules: list[DeletionRule],
) -> None:
    # Even a SUCCESS result proves nothing: the present readback remains the finding.
    a, notes, p = assess(rules, record(), [treatment(1, "DELETE_RECORD", result="SUCCESS")])
    assert (a.category, a.action, a.verdict) == ("SUPPORT_ATTACHMENT", "DELETE", "VIOLATION")
    assert a.fact is not None and a.fact.evidence_id == "inventory"
    assert "inferred_support_category:support_1:activity_1" in notes
    case = p.predict_case(p.evidence.dataset.requests[0])
    assert case.row.deletion_status == "INCOMPLETE"
    assert "support_1" in case.low_confidence


def test_contradictory_workflow_operations_keep_the_conversation_policy(
    rules: list[DeletionRule],
) -> None:
    ops = [treatment(1, "DELETE_RECORD"), treatment(2, "REDACT_RECORD", "2026-03-02T12:50:00Z")]
    a, notes, _ = assess(rules, record(), ops)
    assert (a.category, a.action) == ("SUPPORT_MESSAGE", "REDACT")
    assert not any(n.startswith("inferred_support_category") for n in notes)


@pytest.mark.parametrize(
    ("row", "collection"),
    [
        (RECORD, "support_conversations"),
        (
            {**RECORD, "message_excerpt": "Customer followed up about an order update."},
            "support_records",
        ),
        ({**RECORD, "message_text": "Thanks, the agent resent it."}, "support_records"),
        ({**RECORD, "record_type": "SUPPORT_MESSAGE"}, "support_records"),
    ],
    ids=["conversation_collection", "shared_order_context", "conversation_text", "named_type"],
)
def test_conversation_or_explicit_evidence_is_never_overridden(
    rules: list[DeletionRule], row: dict[str, JsonValue], collection: str
) -> None:
    a, notes, _ = assess(rules, record(row, collection), [treatment(1, "DELETE_RECORD")])
    assert (a.category, a.action) == ("SUPPORT_MESSAGE", "REDACT")
    assert not any(n.startswith("inferred_support_category") for n in notes)


@pytest.mark.parametrize(
    ("operation_at", "inferred"),
    [("2026-03-02T12:35:00Z", True), ("2026-03-02T12:45:00Z", False)],
)
def test_an_operation_after_audit_at_cannot_support_the_inference(
    rules: list[DeletionRule], operation_at: str, inferred: bool
) -> None:
    a, _, _ = assess(
        rules,
        record(captured="2026-03-02T06:00:00Z"),
        [treatment(1, "DELETE_RECORD", operation_at)],
        audit="2026-03-02T12:40:00Z",
    )
    assert (a.category == "SUPPORT_ATTACHMENT") is inferred


def test_an_operation_outside_the_request_batch_is_not_attributed(
    rules: list[DeletionRule],
) -> None:
    a, _, _ = assess(rules, record(), [treatment(1, "DELETE_RECORD", "2026-03-05T09:00:00Z")])
    assert (a.category, a.action) == ("SUPPORT_MESSAGE", "REDACT")


def test_a_record_shared_with_another_subject_is_not_inferred_an_attachment(
    rules: list[DeletionRule],
) -> None:
    shared = {**RECORD, "customer_reference": "user_b"}
    a, _, _ = assess(rules, record(shared), [treatment(1, "DELETE_RECORD")])
    assert (a.category, a.action) == ("SUPPORT_MESSAGE", "REDACT")


def test_inference_is_rejected_when_it_alone_would_report_a_compliant_record(
    rules: list[DeletionRule],
) -> None:
    redacted: dict[str, JsonValue] = {
        "resource_id": "support_1",
        "customer_reference": "user_a",
        "requester_email": None,
        "message_excerpt": "Customer contacted support about account access.",
    }
    a, notes, _ = assess(rules, record(redacted), [treatment(1, "DELETE_RECORD")])
    assert (a.category, a.action, a.verdict) == ("SUPPORT_MESSAGE", "REDACT", "COMPLIANT")
    assert "rejected_support_category_inference:support_1" in notes
