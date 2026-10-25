"""Policy classification sees only evidence available at audit_at.

Synthetic fixtures only, never copied from sample answers. A later scan, schema,
record type or catalogue link must not change which rule applied at the cutoff,
and ownership learned after the cutoff must not turn earlier facts into findings.
"""

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

import pytest
from ghost_audit.application.submission.records import SubmissionRecords
from ghost_audit.application.submission_service import SubmissionPredictor
from ghost_audit.domain.models import Activity, DeletionRule, Observation
from ghost_audit.domain.submission_models import CasePrediction, Fact, Resource
from ghost_audit.domain.time import parse_timestamp
from ghost_audit.infrastructure.parsers.structured import parse_json
from pydantic import JsonValue

from tests.fixtures.evidence_cases import AFTER, CUTOFF, LISTING, build, ctx, request, snapshot

AUDIT = parse_timestamp(CUTOFF)
LATER = parse_timestamp(AFTER) + timedelta(days=1)
EMAIL = "a@example.test"


def support(
    file: str,
    captured: str,
    collection: str,
    record: dict[str, JsonValue],
    observed: str | None = None,
) -> list[Observation]:
    """One support_platform row; observed is the inner snapshot clock."""
    return snapshot(
        file, captured, [("support_platform", collection, observed or captured, [record])]
    )


def manifest(file: str, captured: str, rows: Sequence[tuple[str, str, str]]) -> list[Observation]:
    """Export-manifest readbacks: rows of (recorded_at, resource_id, FOUND|NOT_FOUND)."""
    return parse_json(
        {
            "exported_at": captured,
            "records": [
                {
                    "recorded_at": at,
                    "system": "search_service",
                    "resource_id": rid,
                    "record_type": "SEARCH_INDEX_ENTRY",
                    "result": result,
                    "subject_reference": EMAIL,
                }
                for at, rid, result in rows
            ],
        },
        ctx(file, captured),
    )


def catalogue(activity_id: str, at: str, resource: str) -> Activity:
    return Activity.model_validate(
        {
            "activity_id": activity_id,
            "event_time": at,
            "event_type": "LINK_RESOURCE_IDENTITY",
            "source_system": "attachment_catalog",
            "target_system": "support_platform",
            "resource_id": resource,
            "reported_result": "SUCCESS",
            "details": f"Attachment catalog confirmed {resource} (file.pdf) belongs only to {EMAIL}.",
        }
    )


def predictor(
    rules: list[DeletionRule],
    observations: Iterable[Observation],
    activities: Iterable[Activity] = (),
) -> SubmissionPredictor:
    return SubmissionPredictor(build(rules, [request("case_1", EMAIL)], observations, activities))


def category(records: SubmissionRecords, resource_id: str, audit_at: datetime = AUDIT) -> str:
    signals = records.facts(resource_id, "user_a", audit_at)[1]
    return records.category(resource_id, signals, audit_at)


CONVERSATION: dict[str, JsonValue] = {
    "resource_id": "support_1",
    "requester_email": EMAIL,
    "message_excerpt": "Customer asked about delivery.",
}


def test_future_attachment_scan_cannot_change_earlier_category(
    rules: list[DeletionRule],
) -> None:
    # The scan's own clock precedes the cutoff, but its file was captured afterwards.
    scan = parse_json(
        {
            "exported_at": AFTER,
            "events": [
                {
                    "timestamp": LISTING,
                    "event": "attachment_pii_scan",
                    "resource_id": "support_1",
                    "service": "support_platform",
                    "file": "file.pdf",
                    "matched_value": EMAIL,
                }
            ],
        },
        ctx("scan", AFTER),
    )
    records = predictor(
        rules, [*support("early", LISTING, "support_records", CONVERSATION), *scan]
    ).records
    assert category(records, "support_1") == "SUPPORT_MESSAGE"
    assert category(records, "support_1", LATER) == "SUPPORT_ATTACHMENT"


def test_source_clock_inside_a_later_file_does_not_make_its_schema_available(
    rules: list[DeletionRule],
) -> None:
    attachment: dict[str, JsonValue] = {
        "resource_id": "support_1",
        "file_name": "file.pdf",
        "storage_class": "ticket_attachment",
        "uploaded_by": EMAIL,
    }
    records = predictor(
        rules,
        [
            *support("early", LISTING, "support_records", CONVERSATION),
            *support("late", AFTER, "ticket_attachments", attachment, observed=LISTING),
        ],
    ).records
    assert category(records, "support_1") == "SUPPORT_MESSAGE"
    assert category(records, "support_1", LATER) == "SUPPORT_ATTACHMENT"


def test_future_explicit_record_type_cannot_change_earlier_category(
    rules: list[DeletionRule],
) -> None:
    typed = {**CONVERSATION, "record_type": "SUPPORT_ATTACHMENT"}
    records = predictor(
        rules,
        [
            *support("early", LISTING, "support_records", CONVERSATION),
            *support("late", AFTER, "support_records", typed),
        ],
    ).records
    assert category(records, "support_1") == "SUPPORT_MESSAGE"
    assert category(records, "support_1", LATER) == "SUPPORT_ATTACHMENT"


def test_pre_audit_named_conversation_is_not_made_ambiguous_by_a_later_type(
    rules: list[DeletionRule],
) -> None:
    named = {**CONVERSATION, "record_type": "SUPPORT_MESSAGE"}
    later = {**CONVERSATION, "record_type": "SUPPORT_ATTACHMENT"}
    records = predictor(
        rules,
        [
            *support("early", LISTING, "support_conversations", named),
            *support("late", AFTER, "support_records", later),
        ],
    ).records
    assert category(records, "support_1") == "SUPPORT_MESSAGE"


@pytest.mark.parametrize("resource", ["support_1", "object_1"])
def test_future_catalogue_link_cannot_change_earlier_treatment(
    rules: list[DeletionRule], resource: str
) -> None:
    row = {**CONVERSATION, "resource_id": resource}
    early = support("early", LISTING, "support_records", row)
    late_link = predictor(rules, early, [catalogue("activity_1", AFTER, resource)]).records
    assert category(late_link, resource) != "SUPPORT_ATTACHMENT"
    assert category(late_link, resource, LATER) == "SUPPORT_ATTACHMENT"
    early_link = predictor(rules, early, [catalogue("activity_1", LISTING, resource)]).records
    assert category(early_link, resource) == "SUPPORT_ATTACHMENT"


@pytest.mark.parametrize(
    ("record_type", "extra"),
    [
        ("SECURITY_AUDIT_LOG", {"retention_until": "2034-01-01T00:00:00Z"}),
        ("LEGAL_HOLD_RECORD", {"hold_status": "ACTIVE"}),
    ],
)
def test_future_retention_or_legal_hold_metadata_cannot_change_earlier_policy(
    rules: list[DeletionRule], record_type: str, extra: dict[str, JsonValue]
) -> None:
    retained = {**CONVERSATION, "record_type": record_type, **extra}
    early = support("early", LISTING, "support_records", CONVERSATION)
    late = predictor(rules, [*early, *support("late", AFTER, "support_records", retained)])
    assert late.records.required[category(late.records, "support_1")] == "REDACT"
    timely = predictor(rules, support("early", LISTING, "support_records", retained))
    assert category(timely.records, "support_1") == record_type
    assert timely.records.required[record_type] == "RETAIN"


def test_pre_audit_attachments_and_conversations_stay_distinguishable(
    rules: list[DeletionRule],
) -> None:
    attachment: dict[str, JsonValue] = {
        "resource_id": "support_1",
        "file_name": "file.pdf",
        "storage_class": "ticket_attachment",
        "uploaded_by": EMAIL,
    }
    conversation = {**CONVERSATION, "resource_id": "support_2"}
    records = predictor(
        rules,
        snapshot(
            "early",
            LISTING,
            [
                ("support_platform", "ticket_attachments", LISTING, [attachment]),
                ("support_platform", "support_conversations", LISTING, [conversation]),
            ],
        ),
    ).records
    assert category(records, "support_1") == "SUPPORT_ATTACHMENT"
    assert category(records, "support_2") == "SUPPORT_MESSAGE"


def test_signals_exactly_at_the_cutoff_count_and_one_second_later_do_not(
    rules: list[DeletionRule],
) -> None:
    just_after = (AUDIT + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    at_cutoff = predictor(
        rules,
        support(
            "edge", CUTOFF, "support_records", {**CONVERSATION, "record_type": "SUPPORT_ATTACHMENT"}
        ),
    ).records
    assert category(at_cutoff, "support_1") == "SUPPORT_ATTACHMENT"
    beyond = predictor(
        rules,
        [
            *support("early", LISTING, "support_records", CONVERSATION),
            *support(
                "edge",
                just_after,
                "support_records",
                {**CONVERSATION, "record_type": "SUPPORT_ATTACHMENT"},
            ),
        ],
    ).records
    assert category(beyond, "support_1") == "SUPPORT_MESSAGE"


def test_future_ownership_does_not_create_historical_findings(
    rules: list[DeletionRule],
) -> None:
    # Before the cutoff the row names nobody; only a later file ties it to the subject.
    anonymous: dict[str, JsonValue] = {"resource_id": "search_1", "document": {"title": "Order"}}
    named: dict[str, JsonValue] = {"resource_id": "search_1", "document": {"email": EMAIL}}
    p = predictor(
        rules,
        [
            *snapshot(
                "early",
                LISTING,
                [("search_service", "customer_search_documents", LISTING, [anonymous])],
            ),
            *snapshot(
                "late", AFTER, [("search_service", "customer_search_documents", AFTER, [named])]
            ),
        ],
    )
    case = p.evidence.dataset.requests[0]
    resources, _ = p.resources_for(case, "user_a")
    assert resources["search_1"].methods == {"explicit_identifier_after_audit"}
    [future] = p._assess_resources(case, "user_a", resources, [])
    assert (future.verdict, future.fact) == ("UNKNOWN", None)
    # The same facts under timely ownership are a violation: the guard is what blocks it.
    timely = {"search_1": Resource("search_1", "search_service", {"explicit_identifier"})}
    [known] = p._assess_resources(case, "user_a", timely, [])
    assert known.verdict == "VIOLATION"
    assert known.fact is not None and known.fact.evidence_id == "early"


@pytest.mark.parametrize(
    ("late_captured", "late_recorded", "verdict", "evidence"),
    [
        (AFTER, AFTER, "VIOLATION", "early"),  # a later readback cannot overwrite
        (AFTER, LISTING, "VIOLATION", "early"),  # an early clock in a later file neither
        (CUTOFF, CUTOFF, "COMPLIANT", "late"),  # available exactly at the cutoff
    ],
)
def test_future_observation_cannot_overwrite_earlier_state(
    rules: list[DeletionRule],
    late_captured: str,
    late_recorded: str,
    verdict: str,
    evidence: str,
) -> None:
    early = manifest(
        "early", "2026-03-04T10:00:00Z", [("2026-03-04T10:00:00Z", "search_1", "FOUND")]
    )
    late = manifest("late", late_captured, [(late_recorded, "search_1", "NOT_FOUND")])
    p = predictor(rules, [*early, *late])
    case = p.evidence.dataset.requests[0]
    resources = {"search_1": Resource("search_1", "search_service", {"explicit_identifier"})}
    [assessment] = p._assess_resources(case, "user_a", resources, [])
    assert assessment.verdict == verdict
    assert assessment.fact is not None and assessment.fact.evidence_id == evidence


def test_future_absence_of_one_copy_cannot_erase_another_surviving_copy() -> None:
    def fact(evidence: str, day: int, scope: str, present: bool) -> Fact:
        at = AUDIT.replace(day=day)
        return Fact(evidence, at, at, scope, {"DELETE": "VIOLATION" if present else "COMPLIANT"})

    facts = [
        fact("replica_present", 5, "table:replica", True),
        fact("primary_absent", 8, "table:primary", False),
        fact("replica_absent_later", 12, "table:replica", False),
    ]
    verdict, chosen = SubmissionRecords.assess("DELETE", facts, audit_at=AUDIT)
    assert verdict == "VIOLATION"
    assert chosen is not None and chosen.evidence_id == "replica_present"


# Support resources whose only attachment evidence was captured after audit_at; the
# time-valid evidence is a support record without attachment schema, type or link.
LATE_ATTACHMENT_EVIDENCE = {
    "case_71": "support_1370",
    "case_119": "support_9309",
    "case_131": "support_2315",
    "case_179": "support_2283",
    "case_227": "support_5830",
    "case_275": "support_3684",
    "case_431": "support_3615",
    "case_527": "support_3896",
}


def _operations(case: CasePrediction, resource: str) -> list[tuple[str, str]]:
    return [(s.operation, s.evidence_id) for s in case.row.steps if s.resource_id == resource]


def test_participant_support_records_use_the_policy_known_at_audit(
    submission_cases: list[CasePrediction],
) -> None:
    by_case = {case.case_id: case for case in submission_cases}
    for case_id, resource in LATE_ATTACHMENT_EVIDENCE.items():
        case = by_case[case_id]
        assert case.row.deletion_status == "INCOMPLETE"
        operations = [operation for operation, _ in _operations(case, resource)]
        assert operations == ["REPORT_EXPOSED_PII", "REDACT_RECORD", "VERIFY_RECORD_REDACTED"]
    # A catalogue link recorded before the cutoff still establishes an attachment, while
    # a resource first linked after it gets no policy from that later document.
    case_61 = by_case["case_61"]
    assert [op for op, _ in _operations(case_61, "object_19")] == [
        "REPORT_REMAINING_RECORD",
        "DELETE_RECORD",
        "VERIFY_RECORD_ABSENT",
    ]
    assert _operations(case_61, "support_001") == [("VERIFY_RECORD_REDACTED", "")]
