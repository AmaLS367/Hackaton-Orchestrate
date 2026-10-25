"""Independent synthetic evidence cases builders; never sample answers."""

from ghost_audit.domain.dataset import Dataset
from ghost_audit.domain.models import (
    Activity,
    DeletionRequest,
    EvidenceDocument,
    EvidenceFile,
    Identity,
)
from ghost_audit.infrastructure.ingestion.dataset_loader import row_observations
from ghost_audit.infrastructure.parsers.structured import ExtractionContext, parse_json

REQUESTED = "2026-03-01T08:00:00Z"


REPORTED = "2026-03-02T12:00:00Z"


LISTING = "2026-03-05T10:00:00Z"


CUTOFF = "2026-03-10T12:00:00Z"


AFTER = "2026-03-12T12:00:00Z"


RETAIN = "2034-01-01T00:00:00Z"


def person(user, email):
    return Identity(
        user_id=user,
        name=user.title(),
        email=email,
        phone="+1000000" + user[-4:].replace("_", "0"),
        email_hash=user + "_hash",
        updated_at="2025-01-01T00:00:00Z",
    )


PEOPLE = [
    person("user_a", "a@example.test"),
    person("user_b", "b@example.test"),
    person("user_c", "c@example.test"),
]


def request(
    case_id, email, status="COMPLETE", *, reported=REPORTED, audit=CUTOFF, requested=REQUESTED
):
    return DeletionRequest(
        case_id=case_id,
        email=email,
        requested_at=requested,
        reported_status=status,
        reported_at=reported,
        audit_at=audit,
        request_text="Please delete my account and data.",
    )


def worker(
    activity_id, at, resource, *, target="account_service", event="DELETE_RECORD", result="SUCCESS"
):
    return Activity(
        activity_id=activity_id,
        event_time=at,
        event_type=event,
        source_system="deletion_worker",
        target_system=target,
        resource_id=resource,
        reported_result=result,
        details="synthetic",
    )


def ctx(file, captured):
    return ExtractionContext(
        EvidenceFile(
            file_id=file,
            file_path=f"evidence/{file}.json",
            origin="fixture_store",
            captured_at=captured,
        ),
        "c" * 64,
    )


def snapshot(file, captured, sections, *, complete=False):
    """sections: [(data_store, collection, inner_captured_at, [records])]."""
    return parse_json(
        {
            "exported_at": captured,
            "snapshots": [
                {
                    "captured_at": at,
                    "data_store": store,
                    "collection": coll,
                    "records": records,
                    "complete_listing": complete,
                }
                for store, coll, at, records in sections
            ],
        },
        ctx(file, captured),
    )


def lookups(file, captured, rows):
    """Service-export profile lookups: rows of (resource_id, status, profile)."""
    return parse_json(
        {
            "exported_at": captured,
            "service_exports": {
                "account_service": {
                    "profile_lookups": [
                        {
                            "observed_at": captured,
                            "resource_id": rid,
                            "status_code": status,
                            "profile": profile,
                        }
                        for rid, status, profile in rows
                    ]
                }
            },
        },
        ctx(file, captured),
    )


def build(rules, requests, observations, activities=(), universe=None):
    observations = list(observations)
    files = {}
    for o in observations:
        files.setdefault(o.provenance.evidence_id, o)
    documents = [
        EvidenceDocument(
            manifest=EvidenceFile(
                file_id=o.provenance.evidence_id,
                file_path=o.provenance.file_path,
                origin=o.provenance.origin,
                captured_at=o.provenance.captured_at,
            ),
            sha256=o.provenance.sha256,
            status="parsed",
            observations=[
                x for x in observations if x.provenance.evidence_id == o.provenance.evidence_id
            ],
        )
        for o in files.values()
    ]
    activities = list(activities)
    rows = row_observations(
        "system_activity.csv", activities, "activity_id", "activity_claim", "event_time", "d" * 64
    )
    return Dataset(
        list(requests),
        PEOPLE,
        [],
        activities,
        rules,
        documents,
        [*observations, *rows],
        workflow_requests=list(universe or requests),
    )


def audit_record(rid, user, at=LISTING):
    return (
        "security_service",
        "security_audit_events",
        at,
        [{"resource_id": rid, "subject_reference": user, "retention_until": RETAIN}],
    )


def steps(case):
    assert case.prediction is not None, case.blockers
    return [(s.phase[0], s.operation, s.resource_id, s.evidence_id) for s in case.prediction.steps]
