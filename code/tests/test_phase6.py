"""Original adversarial cases: ownership, policy, replicas, coverage, and OCR."""

import pytest
from ghost_audit.domain.citation_validation import omitted_from_listing
from ghost_audit.domain.evidence_index import EvidenceIndex
from ghost_audit.domain.models import EvidenceFile
from ghost_audit.domain.snapshot_coverage import coverage_surfaces
from ghost_audit.infrastructure.parsers.documents import document_observations, parse_document
from ghost_audit.infrastructure.parsers.image_ocr import image_panels, image_text, panels_from_tsv
from ghost_audit.infrastructure.parsers.structured import parse_json
from test_phase5 import ctx, snapshot
from test_prediction import (
    EARLY,
    FUTURE,
    LATE,
    absent,
    dataset,
    decision,
    observation,
)
from test_prediction import rules as rules


def test_new_primary_read_does_not_erase_older_surviving_replica(rules):
    replica = observation(
        file="replica", replica_scope="read_replica", email="subject@example.test"
    )
    primary = absent(file="primary", at=LATE, replica_scope="primary")
    case = decision(rules, replica, primary)
    assert case.decision == "INCOMPLETE"
    finding = case.prediction.steps[0]
    assert finding.operation == "REPORT_REMAINING_RECORD"
    assert finding.evidence_id == "replica"
    assert any(a.observed_state == "ABSENT" for a in case.assessments)
    assert any(a.observed_state == "PRESENT" for a in case.assessments)


def test_new_tombstone_cannot_retype_surviving_profile_replica(rules):
    replica = observation(
        file="replica", replica_scope="read_replica", email="subject@example.test"
    )
    tombstone = observation(
        file="primary",
        at=LATE,
        replica_scope="primary",
        category="ACCOUNT_TOMBSTONE",
        account_status="DELETED",
        name=None,
        email=None,
        phone=None,
        email_hash=None,
    )
    case = decision(rules, replica, tombstone)
    # One output resource cannot express both DELETE for a profile replica and
    # REDACT for its converted primary; abstain rather than choose a destructive plan.
    assert case.prediction is None
    assert any(
        a.category == "USER_PROFILE" and a.required_action == "DELETE" for a in case.assessments
    )
    assert any(
        a.category == "ACCOUNT_TOMBSTONE" and a.required_action == "REDACT"
        for a in case.assessments
    )


@pytest.mark.parametrize(
    "category,system,collection",
    [
        ("SUPPORT_MESSAGE", "support_platform", "support_conversations"),
        ("SUPPORT_ATTACHMENT", "support_platform", "ticket_attachments"),
        ("SECURITY_AUDIT_LOG", "security_service", "security_audit_records"),
        ("LEGAL_HOLD_RECORD", "legal_service", "retained_order_records"),
    ],
)
def test_missing_rule_condition_never_means_compliance_or_destructive_permission(
    rules, category, system, collection
):
    record = observation(category=category, system=system, collection=collection)
    case = decision(rules, absent(resource="deleted", file="deleted"), record)
    assert case.prediction is None
    assert any(a.compliance == "UNKNOWN" for a in case.assessments)
    assert not any(a.compliance == "VIOLATION" for a in case.assessments)


def test_current_contradictory_condition_cannot_reuse_old_true_flag(rules):
    old = observation(
        category="SUPPORT_ATTACHMENT",
        system="support_platform",
        collection="ticket_attachments",
        subject_only=True,
    )
    new = [
        observation(
            category="SUPPORT_ATTACHMENT",
            system="support_platform",
            collection="ticket_attachments",
            subject_only=value,
            file=f"new{i}",
            at=LATE,
        )
        for i, value in enumerate((True, False))
    ]
    assert decision(rules, old, *new).prediction is None


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"complete_listing": False},
        {"complete_listing": True, "partial": True},
        {"complete_listing": True, "next_cursor": "next"},
        {"complete_listing": True, "filter": {"region": "eu"}},
    ],
)
def test_incomplete_or_filtered_listing_cannot_prove_absence(metadata):
    rows = parse_json(
        {
            "snapshots": [
                {
                    "data_store": "account_service",
                    "collection": "customer_profiles",
                    "records": [],
                    **metadata,
                }
            ]
        },
        ctx("listing", EARLY),
    )
    assert coverage_surfaces(rows) == {}


def test_complete_listing_cannot_verify_wrong_or_unknown_collection(rules):
    listing = snapshot(
        "listing", EARLY, [("account_service", "customer_profiles", EARLY, [])], complete=True
    )
    wrong = observation("other", collection="archived_profiles")
    data = dataset(rules, *listing, wrong)
    index = EvidenceIndex(data.observations, registry=data.registry)
    assert not omitted_from_listing(
        index, "listing", "account_service", "other", data.requests[0].audit_at
    )
    assert not omitted_from_listing(
        index, "listing", "account_service", "unknown", data.requests[0].audit_at
    )


def test_tombstone_partial_identifier_projection_does_not_prove_redaction(rules):
    row = observation(
        category="ACCOUNT_TOMBSTONE",
        collection="deleted_customer_references",
        account_status="DELETED",
        email=None,
    )
    case = decision(rules, row)
    assert case.prediction is None
    assert "redaction_field_coverage_insufficient" in case.unresolved


def test_post_audit_clean_replica_does_not_change_supported_violation(rules):
    case = decision(
        rules,
        observation(replica_scope="replica"),
        absent(file="future", at=FUTURE, replica_scope="replica"),
    )
    assert case.decision == "INCOMPLETE"
    assert all(s.evidence_id != "future" for s in case.prediction.steps)


def test_potential_resource_never_becomes_a_future_verification(rules):
    foreign = observation("foreign", file="foreign", user_id="unresolved_other_subject")
    case = decision(rules, observation(), foreign)
    assert case.decision == "INCOMPLETE"
    assert all(s.resource_id != "foreign" for s in case.prediction.steps)


def tsv(words):
    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    page = "1\t1\t0\t0\t0\t0\t0\t0\t1800\t1100\t-1\t\n"
    return (
        header
        + page
        + "".join(
            f"5\t1\t1\t1\t{i}\t1\t{x}\t{y}\t100\t14\t95\t{text}\n"
            for i, (x, y, text) in enumerate(words, 1)
        )
    )


def test_spatial_ocr_keeps_panel_fields_and_excludes_neighbour_table():
    text = tsv(
        [
            (1442, 334, "export_700"),
            (1442, 382, "Owner"),
            (1558, 383, "subject@example.test"),
            (750, 383, "other@example.test"),
            (280, 455, "export_701"),
            (1442, 446, "Expires"),
            (1558, 447, "2026-01-05"),
        ]
    )
    [(reference, panel)] = panels_from_tsv(text)
    assert reference == "export_700"
    assert "Owner subject@example.test" in panel
    assert "Expires 2026-01-05" in panel
    assert "other@example.test" not in panel and "export_701" not in panel


def test_ocr_exact_identity_still_needs_independent_resource_link(rules):
    image = ctx("image", EARLY)
    o = document_observations(
        "export_700 subject@example.test",
        image,
        {"export_700": ("export_service", "export_700", None)},
        catalogued_only=True,
    )[0]
    assert decision(rules, o).prediction is None
    anchor = observation(
        "export_700",
        "USER_EXPORT",
        system="export_service",
        collection="customer_exports",
        event="catalog_entry",
    )
    assert decision(rules, o, anchor).decision == "INCOMPLETE"


def test_alternate_ocr_recovers_observed_text_without_repairing_identifier(
    rules, tmp_path, monkeypatch
):
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence/image.png").write_bytes(b"fixture image bytes")
    monkeypatch.setattr(
        "ghost_audit.infrastructure.parsers.documents.image_text",
        lambda *a: "export_700 subject@exarnple.test",
    )
    monkeypatch.setattr(
        "ghost_audit.infrastructure.parsers.documents.image_panels",
        lambda *a: [("export_700", "export_700\nOwner subject@example.test\nSize 18 MB")],
    )
    manifest = EvidenceFile(
        file_id="image", file_path="evidence/image.png", origin="export_service", captured_at=EARLY
    )
    doc = parse_document(tmp_path, manifest, {"export_700": ("export_service", "export_700", None)})
    assert any("exarnple" in o.raw_text for o in doc.observations)
    assert any("Owner subject@example.test" in o.raw_text for o in doc.observations)
    assert all(o.provenance.captured_at == doc.manifest.captured_at for o in doc.observations)
    anchor = observation(
        "export_700",
        "USER_EXPORT",
        system="export_service",
        collection="customer_exports",
        event="catalog_entry",
    )
    case = decision(rules, *doc.observations, anchor)
    assert case.decision == "INCOMPLETE"
    assert case.prediction.steps[0].evidence_id == "image"


def test_catalog_does_not_override_foreign_subject_shown_in_ocr(rules):
    image = document_observations(
        "export_700 other@example.test",
        ctx("image", EARLY),
        {"export_700": ("export_service", "export_700", None)},
        catalogued_only=True,
    )[0]
    anchor = observation(
        "export_700",
        "USER_EXPORT",
        system="export_service",
        collection="customer_exports",
        event="catalog_entry",
    )
    assert decision(rules, image, anchor).prediction is None


@pytest.mark.parametrize(
    "category,system,collection",
    [
        ("DATA_FLOW", "integration_service", "connector_configurations"),
        ("BACKUP_ARCHIVE", "backup_service", "backup_catalog"),
    ],
)
def test_missing_safety_field_cannot_be_inferred_from_record_existence(
    rules, category, system, collection
):
    case = decision(
        rules,
        absent(resource="deleted", file="deleted"),
        observation(category=category, system=system, collection=collection),
    )
    assert case.prediction is None
    assert "process_safety_unproven" in case.unresolved


@pytest.mark.parametrize("disabled", [True, False])
def test_ocr_disabled_or_missing_binary_is_portable(tmp_path, monkeypatch, disabled):
    if disabled:
        monkeypatch.setenv("GHOST_AUDIT_OCR", "0")
    else:
        monkeypatch.delenv("GHOST_AUDIT_OCR", raising=False)
        monkeypatch.setenv("GHOST_AUDIT_TESSERACT", str(tmp_path / "missing-tesseract"))
    assert image_text(tmp_path / "missing.png", "digest") is None
    assert image_panels(tmp_path / "missing.png", "digest") == []
