"""Evidence recovery: synthetic regressions through the real pipeline.

Fixtures are constructed, never copied from sample answers. They pin the new linkage
(workflow batches, late-packaged snapshots, documents), state (complete listings,
freshest surface) and policy behaviour, including the cases that must still abstain.
"""

import pytest
from ghost_audit.application.evidence_association import EvidenceAssociationService
from ghost_audit.application.strict_audit import predict
from ghost_audit.domain.citation_validation import validate_output
from ghost_audit.domain.evidence_index import EvidenceIndex
from ghost_audit.domain.models import (
    Activity,
    EvidenceFile,
)
from ghost_audit.infrastructure.parsers.documents import (
    catalog_references,
    document_observations,
    parse_document,
)
from ghost_audit.infrastructure.parsers.structured import ExtractionContext, parse_json

from tests.fixtures.evidence_cases import (
    AFTER,
    LISTING,
    REPORTED,
    audit_record,
    build,
    ctx,
    lookups,
    request,
    snapshot,
    steps,
    worker,
)


def test_result_status_consistency_is_only_a_candidate_search(rules):
    # The window/status heuristic cannot prove ownership of either primary profile.
    a, b = (
        request("case_a", "a@example.test", "COMPLETE"),
        request("case_b", "b@example.test", "NOT_STARTED"),
    )
    acts = [
        worker("act_1", "2026-03-02T11:00:00Z", "account_1", result="SUCCESS"),
        worker("act_2", "2026-03-02T11:10:00Z", "account_2", result="FAILED"),
    ]
    obs = [
        *lookups("export", LISTING, [("account_1", 404, None), ("account_2", 404, None)]),
        *snapshot(
            "audits",
            LISTING,
            [audit_record("audit_a", "user_a"), audit_record("audit_b", "user_b")],
        ),
    ]
    run = predict(build(rules, [a, b], obs, acts))
    by = {c.case_id: c for c in run.cases}
    assert by["case_a"].prediction is by["case_b"].prediction is None
    assert all(
        x.compliance != "COMPLIANT"
        for c in by.values()
        for x in c.assessments
        if x.scope.system_id == "account_service"
    )


def test_ambiguous_profiles_all_absent_do_not_prove_search_coverage(rules):
    a, c = request("case_a", "a@example.test"), request("case_c", "c@example.test")
    acts = [
        worker("act_1", "2026-03-02T11:00:00Z", "account_1"),
        worker("act_2", "2026-03-02T11:10:00Z", "account_2"),
    ]
    listing = (
        "account_service",
        "customer_profiles",
        LISTING,
        [{"resource_id": "account_9", "email": None}],
    )
    obs = snapshot(
        "state",
        LISTING,
        [listing, audit_record("audit_a", "user_a"), audit_record("audit_c", "user_c")],
    )
    run = predict(build(rules, [a, c], obs, acts))
    case = next(x for x in run.cases if x.case_id == "case_a")
    assert case.prediction is None
    assert "no_verified_deletion_treatment" in case.blockers
    # If one candidate is still listed, the subject's profile may survive: abstain.
    listing = (
        "account_service",
        "customer_profiles",
        LISTING,
        [{"resource_id": "account_2", "email": None}],
    )
    obs = snapshot(
        "state",
        LISTING,
        [listing, audit_record("audit_a", "user_a"), audit_record("audit_c", "user_c")],
    )
    case = next(x for x in predict(build(rules, [a, c], obs, acts)).cases if x.case_id == "case_a")
    assert case.prediction is None and "no_verified_deletion_treatment" in case.blockers


def test_identity_exclusion_observed_after_audit_is_not_used(rules):
    a, c = request("case_a", "a@example.test"), request("case_c", "c@example.test", audit=AFTER)
    acts = [
        worker("act_1", "2026-03-02T11:00:00Z", "account_1"),
        worker("act_2", "2026-03-02T11:10:00Z", "account_2"),
    ]
    late = lookups(
        "late", "2026-03-11T09:00:00Z", [("account_2", 200, {"email": "c@example.test"})]
    )
    analyzer = EvidenceAssociationService(build(rules, [a, c], late, acts))
    # At case_a's cutoff nobody has claimed account_2 yet: still ambiguous for case_a.
    assert analyzer.workflow.attributed(a) == []
    assert {r.resource_id for r in analyzer.analyze(a).primary_profile_candidates} == {
        "account_1",
        "account_2",
    }
    # case_c's later cutoff sees its own profile, and so excludes it from elimination.
    assert len(analyzer.workflow.attributed(c)) == 1


def test_crowded_window_blocks_per_resource_attribution(rules):
    a = request("case_a", "a@example.test")
    action = worker(
        "act_3",
        "2026-03-02T11:31:00Z",
        "analytics_7",
        target="analytics_platform",
        event="ANONYMIZE_RECORD",
    )
    alone = EvidenceAssociationService(
        build(rules, [a], [], [worker("act_1", "2026-03-02T11:00:00Z", "account_1"), action])
    )
    assert len(alone.workflow.attributed(a)) == 2
    # A second profile with no visible request means another batch shares the window.
    crowded = EvidenceAssociationService(
        build(
            rules,
            [a],
            [],
            [
                worker("act_1", "2026-03-02T11:00:00Z", "account_1"),
                worker("act_2", "2026-03-02T11:10:00Z", "account_2"),
                action,
            ],
        )
    )
    assert crowded.workflow.attributed(a) == []


def test_late_packaged_earlier_snapshot_neither_links_nor_is_cited(rules):
    # Captured after the audit, the bundle is later evidence even though its inner
    # snapshot clock is earlier: it must not add a record to the answer at the cutoff.
    a = request("case_a", "a@example.test")
    present = (
        "search_service",
        "customer_search_documents",
        LISTING,
        [{"resource_id": "search_1", "document": {"email": "a@example.test"}}],
    )
    late = snapshot("late_bundle", AFTER, [audit_record("audit_a", "user_a", at=LISTING)])
    case = predict(build(rules, [a], [*snapshot("current", LISTING, [present]), *late])).cases[0]
    assert case.decision == "INCOMPLETE"
    assert all(rid != "audit_a" and e != "late_bundle" for _, _, rid, e in steps(case))
    assert all(x.scope.resource_id != "audit_a" for x in case.assessments)
    # At a cutoff after the bundle's capture, the same fact links and is citable.
    later = request("case_a", "a@example.test", audit="2026-03-13T12:00:00Z")
    case = predict(build(rules, [later], [*snapshot("current", LISTING, [present]), *late])).cases[
        0
    ]
    assert ("V", "VERIFY_RECORD_PRESENT", "audit_a", "") in steps(case)


def test_complete_listing_proves_absence_and_validator_accepts_coverage(rules):
    a = request("case_a", "a@example.test")
    acts = [worker("act_1", "2026-03-02T11:00:00Z", "account_1")]
    listing = (
        "account_service",
        "customer_profiles",
        LISTING,
        [{"resource_id": "account_9", "email": None}],
    )
    anchor = parse_json(
        {
            "resource_id": "account_1",
            "subject_reference": "user_a",
            "event": "catalog_entry",
            "system": "account_service",
            "collection": "customer_profiles",
        },
        ctx("anchor", REPORTED),
    )
    data = build(
        rules,
        [a],
        [
            *anchor,
            *snapshot(
                "state", LISTING, [listing, audit_record("audit_a", "user_a")], complete=True
            ),
        ],
        acts,
    )
    run = predict(data)
    assert steps(run.cases[0]) == [
        ("V", "VERIFY_RECORD_ABSENT", "account_1", "state"),
        ("V", "VERIFY_RECORD_PRESENT", "audit_a", "state"),
    ]
    checks = validate_output(
        run.predictions, data.requests, EvidenceIndex(data.observations, registry=data.registry)
    )
    assert [c.resource_support for c in checks] == ["coverage", "linked"]
    # The same listing cannot support any other operation.
    bad = run.predictions[0].model_copy(
        update={
            "steps": [
                run.predictions[0]
                .steps[0]
                .model_copy(update={"operation": "VERIFY_RECORD_PRESENT", "state": "PRESENT"})
            ]
        }
    )
    with pytest.raises(ValueError):
        validate_output(
            [bad], data.requests, EvidenceIndex(data.observations, registry=data.registry)
        )


def test_explicit_read_outranks_listing_and_listed_record_remains(rules):
    a = request("case_a", "a@example.test")
    acts = [worker("act_1", "2026-03-02T11:00:00Z", "account_1")]
    read = lookups(
        "read", "2026-03-04T10:00:00Z", [("account_1", 404, {"email": "a@example.test"})]
    )
    listing = (
        "account_service",
        "customer_profiles",
        LISTING,
        [{"resource_id": "account_9", "email": None}],
    )
    obs = [*read, *snapshot("state", LISTING, [listing, audit_record("audit_a", "user_a")])]
    assert ("V", "VERIFY_RECORD_ABSENT", "account_1", "read") in steps(
        predict(build(rules, [a], obs, acts)).cases[0]
    )
    # Still listed (identifiers nulled or not): the profile row remains, so DELETE is unmet.
    listing = (
        "account_service",
        "customer_profiles",
        LISTING,
        [{"resource_id": "account_1", "subject_reference": "user_a", "email": None}],
    )
    obs = snapshot("state", LISTING, [listing, audit_record("audit_a", "user_a")])
    case = predict(build(rules, [a], obs, acts)).cases[0]
    assert ("F", "REPORT_REMAINING_RECORD", "account_1", "state") in steps(case)


def test_newest_surface_supersedes_stale_replica(rules):
    a = request("case_a", "a@example.test")
    old = snapshot(
        "old_replica",
        "2026-02-01T10:00:00Z",
        [
            (
                "account_service",
                "customer_profiles",
                "2026-02-01T10:00:00Z",
                [{"resource_id": "account_1", "email": "a@example.test"}],
            )
        ],
    )
    new = lookups("new_export", LISTING, [("account_1", 404, None)])
    case = predict(build(rules, [a], [*old, *new])).cases[0]
    assert steps(case) == [("V", "VERIFY_RECORD_ABSENT", "account_1", "new_export")]


def test_backup_has_only_a_restore_obligation(rules):
    a = request("case_a", "a@example.test")
    rows = [
        (
            "backup_service",
            "backup_catalog",
            LISTING,
            [
                {
                    "resource_id": "backup_1",
                    "subject_reference": "user_a",
                    "restore_allowed": True,
                    "archive_path": "s3://x",
                }
            ],
        ),
        ("account_service", "customer_profiles", LISTING, []),
    ]
    acts = [worker("act_1", "2026-03-02T11:00:00Z", "account_1")]
    case = predict(build(rules, [a], snapshot("state", LISTING, rows), acts)).cases[0]
    assert [op for _, op, rid, _ in steps(case) if rid == "backup_1"] == [
        "REPORT_RESTORE_RISK",
        "BLOCK_RESTORE",
        "VERIFY_RESTORE_BLOCKED",
    ]


def test_worker_delete_types_an_otherwise_untyped_support_record(rules):
    a = request("case_a", "a@example.test")
    row = parse_json(
        {
            "resource_id": "support_1",
            "event": "contact_query_completed",
            "rows": 1,
            "subject_only": True,
            "lookup_key": "a@example.test",
            "observed_at": LISTING,
        },
        ExtractionContext(
            EvidenceFile(
                file_id="log", file_path="evidence/log.json", origin="x", captured_at=LISTING
            ),
            "e" * 64,
            system="support_replica",
        ),
    )
    acts = [worker("act_9", "2026-03-02T11:40:00Z", "support_1", target="support_platform")]
    case = predict(build(rules, [a], row, acts)).cases[0]
    assert ("F", "REPORT_REMAINING_RECORD", "support_1", "log") in steps(case)


def test_earlier_request_of_same_subject_keeps_its_evidence(rules):
    early = request(
        "case_early",
        "a@example.test",
        requested="2026-01-01T08:00:00Z",
        reported="2026-01-02T12:00:00Z",
        audit="2026-01-05T12:00:00Z",
    )
    later = request("case_later", "a@example.test")
    old = lookups(
        "old", "2026-01-03T10:00:00Z", [("account_old", 404, {"email": "a@example.test"})]
    )
    new = snapshot(
        "new",
        LISTING,
        [
            (
                "search_service",
                "customer_search_documents",
                LISTING,
                [{"resource_id": "search_1", "document": {"email": "a@example.test"}}],
            )
        ],
    )
    run = predict(build(rules, [early, later], [*old, *new]))
    by = {c.case_id: c for c in run.cases}
    assert all(rid != "account_old" for _, _, rid, _ in steps(by["case_later"]))


def test_document_observation_links_subject_and_resource_across_lines():
    context = ExtractionContext(
        EvidenceFile(
            file_id="pdf",
            file_path="evidence/documents/x.pdf",
            origin="support_platform",
            captured_at=LISTING,
        ),
        "f" * 64,
    )
    text = (
        "Support reference CS-1 / support_001\nPriya Example\npriya@example.test\nfile delivery.pdf"
    )
    [o] = document_observations(text, context, {}, catalogued_only=False)
    assert (o.resources[0].system_id, o.resources[0].resource_id) == (
        "support_platform",
        "support_001",
    )
    assert o.payload["email"] == "priya@example.test"
    assert o.provenance.captured_at.isoformat().startswith("2026-03-05")


def test_catalog_reference_text_matches_only_near_its_catalogue_time():
    acts = [
        Activity(
            activity_id="cat_1",
            event_time="2026-03-05T10:07:00Z",
            event_type="LINK_RESOURCE_IDENTITY",
            source_system="data_catalog",
            target_system="export_service",
            resource_id="export_1",
            reported_result="SUCCESS",
            details="Data catalog linked export_1 (NST-1) to a@example.test and user_a.",
        )
    ]
    catalog = catalog_references(acts)
    near = ExtractionContext(
        EvidenceFile(
            file_id="d1", file_path="evidence/d1.pdf", origin="history", captured_at=LISTING
        ),
        "f" * 64,
    )
    far = ExtractionContext(
        EvidenceFile(
            file_id="d2",
            file_path="evidence/d2.pdf",
            origin="history",
            captured_at="2026-06-01T00:00:00Z",
        ),
        "f" * 64,
    )
    assert [
        o.resources[0].resource_id
        for o in document_observations("Statement NST-1", near, catalog, catalogued_only=False)
    ] == ["export_1"]
    assert document_observations("Register row NST-1", far, catalog, catalogued_only=False) == []


def test_ocr_text_keeps_only_catalogued_resources_and_their_lines():
    catalog = {
        "account_5": ("account_service", "account_5", None),
        "backup_1": ("backup_service", "backup_1", None),
    }
    image = ExtractionContext(
        EvidenceFile(
            file_id="img", file_path="evidence/images/x.png", origin="admin", captured_at=LISTING
        ),
        "f" * 64,
    )
    text = "user_a - account_5\nother row account_6 other@example.test\nsupport_9 misread@exarnple.test"
    [o] = document_observations(text, image, catalog, catalogued_only=True)
    assert o.resources[0].resource_id == "account_5"
    assert o.payload["document_text"] == "user_a - account_5"
    assert "other@example.test" not in o.raw_text


def test_images_stay_deferred_without_ocr(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOST_AUDIT_OCR", "0")
    (tmp_path / "evidence/images").mkdir(parents=True)
    (tmp_path / "evidence/images/screen.png").write_bytes(b"\x89PNG\r\n\x1a\nnot really an image")
    manifest = EvidenceFile(
        file_id="img", file_path="evidence/images/screen.png", origin="admin", captured_at=LISTING
    )
    document = parse_document(tmp_path, manifest)
    assert document.status == "deferred" and document.observations == []


def test_collection_system_fallback_alias_and_envelope_scope():
    rows = parse_json(
        {"collection": "customer_export_jobs", "records": [{"resource_id": "export_1"}]},
        ctx("jobs", LISTING),
    )
    assert rows[-1].resources[0].system_id == "export_service"
    replica = ExtractionContext(
        EvidenceFile(file_id="r", file_path="evidence/r.log", origin="x", captured_at=LISTING),
        "f" * 64,
        system="support_replica",
    )
    assert (
        parse_json({"resource_id": "support_1"}, replica)[0].resources[0].system_id
        == "support_platform"
    )
    # A lookup list inside another store's envelope names its own system, not the envelope collection.
    history = snapshot(
        "hist",
        LISTING,
        [
            (
                "backup_restore_service",
                "operational_record_history",
                LISTING,
                [
                    {
                        "resource_id": "account_1",
                        "system": "account_service",
                        "record_type": "USER_PROFILE",
                        "result": "NOT_FOUND",
                        "recorded_at": LISTING,
                    }
                ],
            )
        ],
    )
    ref = next(o for o in history if o.resources).resources[0]
    assert (ref.system_id, ref.collection) == ("account_service", None)
