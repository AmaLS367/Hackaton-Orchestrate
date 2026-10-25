"""Recovery-round regressions: temporal availability, scoped ownership and state semantics.

Synthetic fixtures only, never copied from sample answers. Each test pins one boundary
through the real modules; the last builds participant-style files end to end.
"""

import json
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest
from ghost_audit.application.evidence_association import EvidenceAssociationService
from ghost_audit.application.observation_interpretation import interpret
from ghost_audit.application.strict_audit import predict
from ghost_audit.application.temporal_service import TemporalStateEngine
from ghost_audit.domain.association_models import (
    AssociatedObservation,
    CaseEvidenceBundle,
    CorrelationLink,
    IntentResult,
    ObservationLink,
    ResolvedIdentity,
)
from ghost_audit.domain.dataset import Dataset
from ghost_audit.domain.evidence_index import EvidenceIndex
from ghost_audit.domain.models import (
    Activity,
    DeletionRule,
    EvidenceFile,
    Identity,
    IdentityChange,
    Observation,
)
from ghost_audit.domain.observation_clocks import known_at, time_profile
from ghost_audit.domain.policy import PolicyEvaluator
from ghost_audit.domain.snapshot_coverage import coverage_surfaces
from ghost_audit.domain.temporal_models import CaseStateBundle, TemporalObservation
from ghost_audit.domain.time import parse_timestamp
from ghost_audit.infrastructure.ingestion.dataset_loader import load_dataset
from ghost_audit.infrastructure.parsers.documents import catalog_references, document_observations
from ghost_audit.infrastructure.parsers.sql_snapshot import parse_sql
from ghost_audit.infrastructure.parsers.structured import ExtractionContext, parse_json, parse_text
from ghost_audit.infrastructure.serialization.prediction_artifacts import (
    write_abstention_diagnostics,
)
from pydantic import JsonValue

from tests.fixtures.evidence_cases import (
    AFTER,
    CUTOFF,
    LISTING,
    PEOPLE,
    audit_record,
    build,
    ctx,
    lookups,
    request,
    snapshot,
    steps,
    worker,
)
from tests.fixtures.paths import DATASET_ROOT


def search_row(
    file: str, at: str, email: str, rid: str = "search_1", observed: str | None = None
) -> list[Observation]:
    return snapshot(
        file,
        at,
        [
            (
                "search_service",
                "customer_search_documents",
                observed or at,
                [{"resource_id": rid, "document": {"email": email}}],
            )
        ],
    )


def associations(bundle: CaseEvidenceBundle) -> dict[tuple[str, str], str]:
    return {
        (o.observation.provenance.evidence_id, o.observation.provenance.locator): o.association
        for o in bundle.observations
    }


def with_identities(
    data: Dataset, identities: list[Identity], changes: list[IdentityChange]
) -> Dataset:
    return Dataset(
        data.requests,
        identities,
        changes,
        data.activities,
        data.rules,
        data.documents,
        data.observations,
        workflow_requests=data.workflow_requests,
    )


def confirmed(o: Observation) -> AssociatedObservation:
    return AssociatedObservation(
        observation=o,
        association="CONFIRMED",
        reason="synthetic_grounded_link",
        links=[
            CorrelationLink(
                method="DIRECT_IDENTIFIER", supporting_observations=[ObservationLink.of(o)]
            )
        ],
    )


def fact(o: Observation) -> TemporalObservation:
    return interpret(confirmed(o), o.resources[0])


def state_bundle(observations: list[Observation], cutoff: str = CUTOFF) -> CaseStateBundle:
    """Temporal reconstruction over synthetic CONFIRMED links for user_a."""
    evidence = CaseEvidenceBundle.model_validate(
        {
            "case_id": "synthetic",
            "audit_at": cutoff,
            "intent": IntentResult.model_validate(
                {
                    "decision": "DELETE_INTENT",
                    "reason_id": "fixture",
                    "confidence": "HIGH",
                    "fallback_recommended": False,
                }
            ),
            "identity": ResolvedIdentity(status="RESOLVED", user_id="user_a"),
            "user_id": "user_a",
            "aliases": [],
            "observations": [confirmed(o) for o in observations if o.resources],
            "resources": [],
            "supporting_evidence_ids": [],
            "deferred_evidence": [],
            "ambiguities": [],
            "limitations": [],
            "unrelated_observation_count": 0,
        }
    )
    return TemporalStateEngine(EvidenceIndex(observations)).analyze(evidence)


def trace(file: str, lines: Sequence[str], captured: str = LISTING) -> list[Observation]:
    context = ExtractionContext(
        EvidenceFile.model_validate(
            {
                "file_id": file,
                "file_path": f"evidence/logs/{file}.log",
                "origin": "service_readback_logs",
                "captured_at": captured,
            }
        ),
        "b" * 64,
    )
    return parse_text("\n".join(lines), context)


# 1. A catalogue link made after the audit cannot reveal an earlier document's resource.
def test_late_catalog_link_does_not_reveal_earlier_document_reference() -> None:
    linked_at = "2026-03-10T20:00:00Z"
    acts = [
        Activity.model_validate(
            {
                "activity_id": "cat_1",
                "event_time": linked_at,
                "event_type": "LINK_RESOURCE_IDENTITY",
                "source_system": "data_catalog",
                "target_system": "export_service",
                "resource_id": "export_1",
                "reported_result": "SUCCESS",
                "details": "Data catalog linked export_1 (NST-1) to a@example.test.",
            }
        )
    ]
    document = ExtractionContext(
        EvidenceFile.model_validate(
            {
                "file_id": "pdf",
                "file_path": "evidence/documents/s.pdf",
                "origin": "history",
                "captured_at": "2026-03-10T06:00:00Z",
            }
        ),
        "f" * 64,
    )
    [o] = document_observations(
        "Statement NST-1\na@example.test", document, catalog_references(acts), catalogued_only=False
    )
    profile = time_profile(o)
    assert profile["captured_at"] is not None and profile["known_at"] is not None
    assert profile["observed_at"] is not None
    assert (
        profile["captured_at"]
        < parse_timestamp(CUTOFF)
        < profile["known_at"]
        == parse_timestamp(linked_at)
    )
    index = EvidenceIndex([o])
    assert index.lookup(identifiers=["a@example.test"], audit_at=CUTOFF) == []
    assert index.lookup(identifiers=["a@example.test"], audit_at="2026-03-11T00:00:00Z") == [o]


# 2. A late document with an earlier source clock is later evidence.
def test_late_document_with_earlier_source_time_establishes_no_ownership(
    rules: list[DeletionRule],
) -> None:
    a = request("case_a", "a@example.test")
    late = search_row("late", AFTER, "a@example.test", observed=LISTING)
    o = next(o for o in late if o.resources)
    profile = time_profile(o)
    assert profile["captured_at"] is not None and profile["known_at"] is not None
    assert profile["observed_at"] is not None
    assert profile["observed_at"] < a.audit_at < profile["known_at"] == known_at(o)
    bundle = EvidenceAssociationService(build(rules, [a], late)).analyze(a)
    assert bundle.observations == [] and bundle.resources == []


# 3. An email reassigned to another user confirms neither past nor present owner.
def test_reassigned_historical_email_confirms_neither_user(rules: list[DeletionRule]) -> None:
    a = request("case_a", "a2@example.test")
    people = [
        Identity.model_validate(
            {
                "user_id": "user_a",
                "name": "A",
                "email": "a2@example.test",
                "phone": "+10000001",
                "email_hash": "ha",
                "updated_at": "2025-07-01T00:00:00Z",
            }
        ),
        Identity.model_validate(
            {
                "user_id": "user_b",
                "name": "B",
                "email": "shared@example.test",
                "phone": "+10000002",
                "email_hash": "hb",
                "updated_at": "2025-10-01T00:00:00Z",
            }
        ),
    ]
    changes = [
        IdentityChange.model_validate(
            {
                "audit_id": "audit_1",
                "user_id": "user_a",
                "event_time": "2025-06-01T00:00:00Z",
                "field_name": "email",
                "old_value": "shared@example.test",
                "new_value": "a2@example.test",
            }
        ),
        IdentityChange.model_validate(
            {
                "audit_id": "audit_2",
                "user_id": "user_b",
                "event_time": "2025-09-01T00:00:00Z",
                "field_name": "email",
                "old_value": "b@example.test",
                "new_value": "shared@example.test",
            }
        ),
    ]
    data = with_identities(
        build(rules, [a], search_row("rows", LISTING, "shared@example.test")), people, changes
    )
    bundle = EvidenceAssociationService(data).analyze(a)
    assert "shared_alias:email" in bundle.ambiguities
    assert "CONFIRMED" not in associations(bundle).values() and bundle.resources == []


# 4. A legitimate former alias still links, with the audit entry that proves it.
def test_legitimate_historical_alias_links_with_its_audit_origin(rules: list[DeletionRule]) -> None:
    a = request("case_a", "a@example.test")
    changes = [
        IdentityChange.model_validate(
            {
                "audit_id": "audit_9",
                "user_id": "user_a",
                "event_time": "2025-06-01T00:00:00Z",
                "field_name": "email",
                "old_value": "old@example.test",
                "new_value": "a@example.test",
            }
        )
    ]
    data = with_identities(
        build(rules, [a], search_row("rows", LISTING, "old@example.test")), PEOPLE, changes
    )
    bundle = EvidenceAssociationService(data).analyze(a)
    [item] = [o for o in bundle.observations if o.observation.resources]
    assert item.association == "CONFIRMED"
    assert {x.audit_id for link in item.links for x in link.alias_origins} == {"audit_9"}
    assert "audit_9" in bundle.supporting_evidence_ids


# 5. Interleaved batches of two requests reported together attribute nothing.
def test_multi_user_workflow_batch_attributes_no_resource(rules: list[DeletionRule]) -> None:
    a, b = request("case_a", "a@example.test"), request("case_b", "b@example.test")
    acts = [
        worker("p1", "2026-03-02T11:00:00Z", "account_1"),
        worker("p2", "2026-03-02T11:05:00Z", "account_2"),
        worker(
            "x1",
            "2026-03-02T11:40:00Z",
            "analytics_1",
            target="analytics_platform",
            event="ANONYMIZE_RECORD",
        ),
        worker(
            "x2",
            "2026-03-02T11:41:00Z",
            "analytics_2",
            target="analytics_platform",
            event="ANONYMIZE_RECORD",
        ),
    ]
    analyzer = EvidenceAssociationService(build(rules, [a, b], [], acts))
    assert analyzer.workflow.attributed(a) == analyzer.workflow.attributed(b) == []
    assert all(
        o.association != "CONFIRMED" for c in (a, b) for o in analyzer.analyze(c).observations
    )


# 6. A record owned by someone else earlier is not the subject's history.
def test_resource_ownership_change_keeps_foreign_period_unconfirmed(
    rules: list[DeletionRule],
) -> None:
    a = request("case_a", "a@example.test")
    earlier = search_row("s1", "2026-03-03T10:00:00Z", "b@example.test")
    later = search_row("s2", LISTING, "a@example.test")
    bundle = EvidenceAssociationService(build(rules, [a], [*earlier, *later])).analyze(a)
    by_file = {k[0]: v for k, v in associations(bundle).items() if k[1].endswith(".records[0]")}
    assert by_file["s2"] == "CONFIRMED" and by_file.get("s1") != "CONFIRMED"


# 7. Mixed-subject documents keep identifiers with their own section and row.
def test_mixed_subject_document_scopes_identifiers_to_resource_section() -> None:
    pdf = ExtractionContext(
        EvidenceFile.model_validate(
            {
                "file_id": "pdf",
                "file_path": "evidence/documents/t.pdf",
                "origin": "support_platform",
                "captured_at": LISTING,
            }
        ),
        "f" * 64,
    )
    two = "Ticket support_001\nPriya\np@example.test\fTicket support_002\nOmar\no@example.test"
    assert {
        o.resources[0].resource_id: o.payload.get("email")
        for o in document_observations(two, pdf, {}, catalogued_only=False)
    } == {"support_001": "p@example.test", "support_002": "o@example.test"}
    continued = (
        "Ticket support_001\np@example.test\fTicket form\nContinued - attachment properties\nx.pdf"
    )
    [o] = document_observations(continued, pdf, {}, catalogued_only=False)
    assert isinstance(o.payload["document_text"], str)
    assert (
        "attachment properties" in o.payload["document_text"]
        and o.payload["email"] == "p@example.test"
    )
    register = "Register\nsupport_003 | user_101 | dispute\nsupport_004 | user_102 | refund"
    observations = document_observations(register, pdf, {}, catalogued_only=False)
    assert {
        o.resources[0].resource_id: o.payload.get("subject_reference") for o in observations
    } == {"support_003": "user_101", "support_004": "user_102"}
    assert all(
        "user_102" not in o.raw_text
        for o in observations
        if o.resources[0].resource_id == "support_003"
    )


# 8. One resource ID in two collections of a system is two records.
def test_cross_collection_resource_id_collision_is_not_joined(rules: list[DeletionRule]) -> None:
    a = request("case_a", "a@example.test")
    owned = snapshot(
        "own",
        LISTING,
        [
            (
                "account_service",
                "customer_profiles",
                LISTING,
                [{"resource_id": "account_1", "email": "a@example.test"}],
            )
        ],
    )
    other = snapshot(
        "other",
        LISTING,
        [
            (
                "account_service",
                "marketing_preferences",
                LISTING,
                [{"resource_id": "account_1", "email": None}],
            )
        ],
    )
    bundle = EvidenceAssociationService(build(rules, [a], [*owned, *other])).analyze(a)
    statuses = {k[0]: v for k, v in associations(bundle).items() if k[1].endswith(".records[0]")}
    assert statuses == {"own": "CONFIRMED", "other": "POTENTIAL"}
    item = next(o for o in bundle.observations if o.observation.provenance.evidence_id == "other")
    assert item.reason == "incompatible_resource_collection"


TRACES = [
    "2026-03-05T09:00:00Z level=DEBUG service=account_service trace_id=rb-1 event=profile_lookup_started "
    "lookup_key=a@example.test",
    "2026-03-05T09:00:00Z level=INFO service=account_service trace_id=rb-1 event=profile_lookup_completed "
    "resource_id=account_1 rows=0 http_status=404 email=stranger@example.test",
    "2026-03-05T09:10:00Z level=DEBUG service=account_service trace_id=rb-2 event=profile_lookup_started "
    "lookup_key=a@example.test",
    "2026-03-05T09:10:00Z level=INFO service=account_service trace_id=rb-2 event=profile_lookup_completed "
    "resource_id=account_2 rows=0 http_status=404",
]


# 9. A trace that also names an unknown subject cannot assign its results.
def test_scoped_trace_with_foreign_unknown_subject_stays_potential(
    rules: list[DeletionRule],
) -> None:
    a = request("case_a", "a@example.test")
    bundle = EvidenceAssociationService(build(rules, [a], trace("rb", TRACES))).analyze(a)
    status = {
        o.observation.resources[0].resource_id: (o.association, o.reason)
        for o in bundle.observations
        if o.observation.resources
    }
    assert status["account_1"][0] == "POTENTIAL"


# 10. A clean direct anchor survives an unrelated ambiguous trace in the same file.
def test_confirmed_direct_anchor_survives_unrelated_ambiguity(rules: list[DeletionRule]) -> None:
    a = request("case_a", "a@example.test")
    bundle = EvidenceAssociationService(build(rules, [a], trace("rb", TRACES))).analyze(a)
    status = {
        o.observation.resources[0].resource_id: o.association
        for o in bundle.observations
        if o.observation.resources
    }
    assert status == {"account_1": "POTENTIAL", "account_2": "CONFIRMED"}
    assert [r.reference.resource_id for r in bundle.resources] == ["account_2"]


def readback(fields: JsonValue, *, resource: bool = True) -> Observation:
    target = "resource_id=account_1 " if resource else ""
    return trace(
        "read",
        [
            f"2026-03-05T09:00:00Z level=INFO service=account_service trace_id=rb-9 "
            f"event=profile_lookup_completed {target}{fields}"
        ],
    )[0]


# 11. An exact-resource 404 proves absence of that record.
def test_exact_resource_readback_404_proves_absence() -> None:
    f = fact(readback("rows=0 http_status=404"))
    assert (f.record_state, f.support) == ("ABSENT", "PROVEN")


# 12. An empty answer to a subject query or filtered read proves nothing exact.
@pytest.mark.parametrize("fields", ["rows=0 query_scope=SUBJECT", "rows=0 filter=region:eu"])
def test_generic_empty_read_without_exact_target_stays_unknown(fields: str) -> None:
    f = fact(readback(fields))
    assert f.record_state == "UNKNOWN" and f.reason == "negative_read_lacks_exact_resource_scope"


def test_empty_read_naming_no_resource_has_no_state_scope() -> None:
    assert readback("rows=0 http_status=404", resource=False).resources == []


def envelope(file: str, **extra: JsonValue) -> list[Observation]:
    return parse_json(
        {
            "exported_at": LISTING,
            "snapshots": [
                {
                    "captured_at": LISTING,
                    "data_store": "account_service",
                    "collection": "customer_profiles",
                    "records": [{"resource_id": "account_9", "email": None}],
                    **extra,
                }
            ],
        },
        ctx(file, LISTING),
    )


# 13. An explicit unfiltered complete listing is a coverage surface.
def test_explicit_complete_collection_listing_is_coverage() -> None:
    [item] = coverage_surfaces(envelope("full", complete_listing=True))[
        ("account_service", "customer_profiles")
    ]
    assert (
        item.complete
        and item.proof == "complete_listing_flag"
        and item.resource_ids == {"account_9"}
    )


# 14. Pagination, truncation or filters make a listing incomplete, whatever its flag says.
@pytest.mark.parametrize(
    "extra,field",
    [
        ({"next_cursor": "abc"}, "truncated"),
        ({"truncated": True}, "truncated"),
        ({"filter": "region=eu"}, "filter_scope"),
    ],
)
def test_paginated_or_filtered_listing_is_not_coverage(
    extra: dict[str, JsonValue], field: str
) -> None:
    observations = envelope("page", complete_listing=True, **extra)
    assert coverage_surfaces(observations) == {}
    [item] = coverage_surfaces(observations, include_incomplete=True)[
        ("account_service", "customer_profiles")
    ]
    assert not item.complete and getattr(item, field)
    assert (
        coverage_surfaces(envelope("plain"), include_incomplete=True)[
            ("account_service", "customer_profiles")
        ][0].proof
        is None
    )


SQL = f"""-- Captured at: {LISTING}
CREATE TABLE customer_profiles_primary (resource_id TEXT PRIMARY KEY, user_id TEXT, email TEXT, updated_at TEXT);
CREATE TABLE customer_profiles_failover_replica (resource_id TEXT PRIMARY KEY, user_id TEXT, email TEXT,
    updated_at TEXT);
{{rows}}"""


def sql(rows: str, file: str = "db", captured: str = LISTING) -> list[Observation]:
    context = ExtractionContext(
        EvidenceFile.model_validate(
            {
                "file_id": file,
                "file_path": f"evidence/databases/{file}.sql",
                "origin": "customer_data_capture",
                "captured_at": captured,
            }
        ),
        "d" * 64,
    )
    return parse_sql(SQL.replace("{rows}", rows), context)


# 15. A replica table missing a row is a coverage gap in the known logical collection.
def test_sql_replica_coverage_gap_is_not_absence() -> None:
    observations = sql(
        "INSERT INTO customer_profiles_primary VALUES "
        "('account_1','user_a','a@example.test','2026-03-05T09:00:00Z');"
    )
    result = state_bundle(observations)
    by_scope = {h.scope.replica_scope: h for h in result.resource_histories}
    assert {h.scope.collection for h in by_scope.values()} == {"customer_profiles"}
    assert by_scope["primary"].record.state == "PRESENT"
    assert by_scope["failover_replica"].record.state == "UNKNOWN"
    assert [o.category for o in by_scope["failover_replica"].observations] == ["SNAPSHOT_GAP"]
    assert [d.kind for d in result.replica_drift] == ["COVERAGE_GAP"]


# 16. A newer primary absence never erases a surviving replica copy.
def test_newer_primary_absence_does_not_override_surviving_replica(
    rules: list[DeletionRule],
) -> None:
    a = request("case_a", "a@example.test")
    replica = sql(
        "INSERT INTO customer_profiles_failover_replica VALUES "
        "('account_1','user_a','a@example.test','2026-03-05T09:00:00Z');"
    )
    newer = lookups("primary_read", "2026-03-08T10:00:00Z", [("account_1", 404, None)])
    case = predict(build(rules, [a], [*replica, *newer])).cases[0]
    assert case.decision == "INCOMPLETE"
    assert ("F", "REPORT_REMAINING_RECORD", "account_1", "db") in steps(case)
    by_scope = {x.scope.replica_scope: x.compliance for x in case.assessments}
    assert by_scope["failover_replica"] == "VIOLATION" and "COMPLIANT" in by_scope.values()


def export(system: str, container: str, record: dict[str, JsonValue]) -> list[Observation]:
    return parse_json(
        {
            "exported_at": LISTING,
            "service_exports": {system: {container: [{"observed_at": LISTING, **record}]}},
        },
        ctx("export", LISTING),
    )


# 17. Every attribution slot observed empty is valid anonymization evidence.
def test_valid_anonymization_evidence_is_compliant(rules: list[DeletionRule]) -> None:
    observations = export(
        "analytics_platform",
        "profiles",
        {
            "resource_id": "analytics_1",
            "customer_reference": None,
            "email": None,
            "phone": None,
            "email_hash": None,
            "audience_cohort": "general_shopper",
        },
    )
    [assessment] = PolicyEvaluator(rules).evaluate(state_bundle(observations))
    assert (assessment.category, assessment.required_action, assessment.compliance) == (
        "ANALYTICS_PROFILE",
        "ANONYMIZE",
        "COMPLIANT",
    )


# 18. A single nulled email is partial redaction, not proof of redaction.
def test_partial_redaction_evidence_remains_unknown(rules: list[DeletionRule]) -> None:
    observations = export(
        "support_platform",
        "tickets",
        {
            "resource_id": "support_1",
            "requester_email": None,
            "shared_context": True,
            "message_excerpt": "Customer asked about an order.",
        },
    )
    [assessment] = PolicyEvaluator(rules).evaluate(state_bundle(observations))
    assert (assessment.required_action, assessment.compliance) == ("REDACT", "UNKNOWN")
    assert assessment.reasons == ["redaction_field_coverage_insufficient"]


# 19. A readback after the audit never changes the state at the audit.
def test_future_readback_is_excluded() -> None:
    present = search_row("earlier", LISTING, "a@example.test")
    future = trace(
        "future",
        [
            "2026-03-11T09:00:00Z level=INFO service=search_service trace_id=rb-7 "
            "event=index_query_completed resource_id=search_1 query_scope=RESOURCE_ID "
            "total_hits=0"
        ],
        captured="2026-03-11T10:00:00Z",
    )
    result = state_bundle([*present, *future])
    [history] = [h for h in result.resource_histories if h.record.support == "PROVEN"]
    assert history.record.state == "PRESENT"
    assert all(
        o.provenance.evidence_id != "future"
        for h in result.resource_histories
        for o in h.observations
    )
    assert "evidence_unavailable_at_audit_cutoff" in {u.reason for u in result.unresolved_states}


# 20. Abstentions carry deterministic, identifier-only root causes.
def test_abstention_diagnostic_attributes_root_cause_deterministically(
    rules: list[DeletionRule], tmp_path: Path
) -> None:
    a = request("case_a", "a@example.test")
    acts = [worker("act_1", "2026-03-02T11:00:00Z", "account_1")]
    obs = [
        *lookups("export", LISTING, [("account_1", 404, None)]),
        *snapshot("audits", LISTING, [audit_record("audit_a", "user_a")]),
    ]
    runs = [predict(build(rules, [a], obs, acts)) for _ in range(2)]
    [record] = runs[0].abstentions
    assert record.case_id == "case_a" and runs[0].cases[0].prediction is None
    assert record.account_attribution == "WORKFLOW_CANDIDATE_ONLY"
    assert record.unlinked_readbacks == {"account_service:account_1": ["export=ABSENT"]}
    assert "readback_exists_but_unlinked" in record.root_causes
    assert record.earliest_failure_stage == "ASSOCIATE"
    assert "account_service:account_1" not in record.confirmed_resources
    paths = [tmp_path / f"run{i}.json" for i in range(2)]
    for path, run in zip(paths, runs, strict=False):
        write_abstention_diagnostics(path, run)
    assert paths[0].read_bytes() == paths[1].read_bytes()
    assert "@" not in paths[0].read_text(encoding="utf-8")


# Integration: participant-style files -> ingestion -> correlation -> state -> policy -> plan.
def write_csv(path: Path, header: str, rows: Sequence[str]) -> None:
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")


@pytest.mark.parametrize(
    "audit,expected",
    [
        ("2026-03-10T12:00:00Z", "COMPLETE"),
        # Once the late bundle is available, its surviving search document is a finding.
        ("2026-03-13T12:00:00Z", "INCOMPLETE"),
    ],
)
def test_participant_style_ingestion_through_planning(
    tmp_path: Path, audit: str, expected: str
) -> None:
    (tmp_path / "evidence/logs").mkdir(parents=True)
    (tmp_path / "evidence/records").mkdir(parents=True)
    shutil.copy(DATASET_ROOT / "deletion_rules.csv", tmp_path / "deletion_rules.csv")
    write_csv(
        tmp_path / "deletion_requests.csv",
        "case_id,email,requested_at,reported_status,reported_at,audit_at,request_text",
        [
            f"case_x,a@example.test,2026-03-01T08:00:00Z,COMPLETE,2026-03-02T12:00:00Z,{audit},"
            "Please delete my account and all my personal data."
        ],
    )
    write_csv(
        tmp_path / "user_identities.csv",
        "user_id,name,email,phone,email_hash,updated_at",
        ["user_a,Alex Example,a@example.test,+1 555 0100," + "a" * 64 + ",2025-01-01T00:00:00Z"],
    )
    write_csv(
        tmp_path / "user_audit_log.csv",
        "audit_id,user_id,event_time,field_name,old_value,new_value",
        [],
    )
    write_csv(
        tmp_path / "system_activity.csv",
        "activity_id,event_time,event_type,source_system,target_system,"
        "resource_id,reported_result,details",
        [],
    )
    write_csv(
        tmp_path / "evidence_files.csv",
        "file_id,file_path,origin,captured_at",
        [
            "ev_1,evidence/logs/readback.log,service_readback_logs,2026-03-05T10:30:00Z",
            "ev_2,evidence/records/late_bundle.json,records_assurance_snapshot_bundle,2026-03-12T12:00:00Z",
        ],
    )
    (tmp_path / "evidence/logs/readback.log").write_text(
        "\n".join(
            [
                "2026-03-05T10:00:00Z level=DEBUG service=account_service trace_id=rb-1 event=profile_lookup_started "
                "resource_id=account_1 lookup_key=a@example.test",
                "2026-03-05T10:00:00Z level=INFO service=account_service trace_id=rb-1 event=profile_lookup_completed "
                "resource_id=account_1 rows=0 http_status=404",
                "2026-03-05T10:05:00Z level=DEBUG service=security_service trace_id=rb-2 event=audit_record_read_started "
                "resource_id=audit_record_1 lookup_key=user_a",
                "2026-03-05T10:05:00Z level=INFO service=security_service trace_id=rb-2 event=audit_record_read_completed "
                "resource_id=audit_record_1 rows=1 subject_reference=user_a event_code=X retention_until=2034-09-30T23:59:59Z",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "evidence/records/late_bundle.json").write_text(
        json.dumps(
            {
                "exported_at": "2026-03-12T12:00:00Z",
                "snapshots": [
                    {
                        "captured_at": "2026-03-04T09:00:00Z",
                        "data_store": "search_service",
                        "collection": "customer_search_documents",
                        "records": [
                            {"resource_id": "search_1", "document": {"email": "a@example.test"}}
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    run = predict(load_dataset(tmp_path))
    [case] = run.cases
    assert case.decision == expected
    assert case.prediction is not None
    found = [
        (s.phase, s.operation, s.system_id, s.resource_id, s.evidence_id)
        for s in case.prediction.steps
    ]
    if expected == "COMPLETE":
        assert found == [
            ("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_1", "ev_1"),
            ("VERIFICATION", "VERIFY_RECORD_PRESENT", "security_service", "audit_record_1", "ev_1"),
        ]
    else:
        assert ("FINDING", "REPORT_REMAINING_RECORD", "search_service", "search_1", "ev_2") in found
