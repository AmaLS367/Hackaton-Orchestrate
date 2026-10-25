"""Submission pathway: one best-supported, citation-valid answer for every request."""

import pytest
from evaluation.scoring import evaluate
from ghost_audit.application.submission_service import predict_submission
from ghost_audit.domain.citation_validation import validate_output
from ghost_audit.domain.evidence_index import EvidenceIndex
from ghost_audit.domain.snapshot_inventory import snapshot_listings
from ghost_audit.infrastructure.serialization.csv_output import read_output

from tests.fixtures.paths import DATASET_ROOT


@pytest.fixture(scope="module")
def full(participant_dataset):
    return participant_dataset


@pytest.fixture(scope="module")
def samples(sample_dataset):
    data = sample_dataset
    return data, {c.case_id: c for c in predict_submission(data)}


def test_full_submission_covers_every_request_with_valid_citations(full):
    cases = predict_submission(full)
    rows = [c.row for c in cases]
    assert [r.case_id for r in rows] == sorted(r.case_id for r in full.requests)
    checks = validate_output(
        rows, full.requests, EvidenceIndex(full.observations, registry=full.registry)
    )
    assert all(check.resource_support in {"linked", "coverage"} for check in checks)
    assert {r.deletion_status for r in rows} <= {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"}
    # Deterministic: a second run serializes identically.
    assert [r.model_dump() for r in rows] == [c.row.model_dump() for c in predict_submission(full)]


def test_sample_regression_floor(samples):
    _, cases = samples
    metrics = evaluate(
        [c.row for c in cases.values()], read_output(DATASET_ROOT / "sample_output.csv")
    )
    assert metrics.status_accuracy == 1.0
    assert metrics.step_precision == 1.0
    assert metrics.step_recall >= 0.93


def test_unique_batch_submission_attributes_the_primary_profile(samples):
    _, cases = samples
    # One SUCCESS submission ~1h before reported_at matches this COMPLETE report.
    assert cases["case_21"].resources["account_6440"] == ["workflow_batch_unique"]


def test_old_lookup_does_not_override_the_request_batch(samples):
    _, cases = samples
    # A March lookup by the subject's key touched another request's account.
    assert "account_6523" not in cases["case_17"].resources
    assert "account_4092" in cases["case_17"].resources


def test_ambiguous_batch_candidates_are_never_attributed(samples):
    _, cases = samples
    for case_id in ("case_28", "case_29"):
        assert not {"account_5482", "account_7012"} & set(cases[case_id].resources)
        assert any(n.startswith("ambiguous_workflow_account:") for n in cases[case_id].notes)


def test_replica_copy_in_the_case_file_outranks_an_unrelated_inventory(samples):
    _, cases = samples
    row = cases["case_05"].row
    assert row.deletion_status == "INCOMPLETE"
    assert [(s.operation, s.evidence_id) for s in row.steps if s.phase == "FINDING"] == [
        ("REPORT_REMAINING_RECORD", "evidence_54")
    ]


def test_snapshot_listings_read_tables_and_collection_envelopes(full):
    listings = snapshot_listings(full.observations)
    # An empty JSON collection snapshot still lists its (empty) account collection.
    assert any(
        item.evidence_id == "evidence_51" and not item.ids
        for item in listings[("account_service", "account")]
    )
    assert any(
        item.evidence_id == "evidence_54" and "account_005" in item.ids
        for item in listings[("account_service", "account")]
    )
