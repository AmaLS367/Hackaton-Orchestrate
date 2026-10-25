"""Submission field-exposure semantics independent of dataset I/O."""

from datetime import UTC, datetime

from ghost_audit.application.submission.records import SubmissionRecords
from ghost_audit.application.submission_service import SubmissionPredictor
from ghost_audit.domain.dataset import Dataset
from ghost_audit.domain.submission_models import Fact


def test_stable_reference_is_permitted_for_redaction_not_anonymization() -> None:
    direct, stable, subject = SubmissionRecords._exposure(
        {
            "customer_reference": "user_26",
            "requester_email": None,
            "message_excerpt": "Order update.",
        },
        {"user_26", "subject@example.test"},
    )
    assert (direct, stable, subject) == (False, True, False)
    _, _, subject = SubmissionRecords._exposure(
        {"message_text": "Send it to SUBJECT@example.test please"},
        {"user_26", "subject@example.test"},
    )
    assert subject


def test_temporal_found_then_not_found_in_same_file_and_scope() -> None:
    # 1. FOUND -> NOT_FOUND in one file, same scope
    f_old = Fact(
        evidence_id="evidence_01",
        at=datetime(2026, 8, 31, 7, 0, tzinfo=UTC),
        captured_at=datetime(2026, 9, 6, 7, 0, tzinfo=UTC),
        scope="service:search_index_service",
        verdicts={"DELETE": "VIOLATION"},
        kind="readback",
    )
    f_new = Fact(
        evidence_id="evidence_01",
        at=datetime(2026, 9, 6, 7, 0, tzinfo=UTC),
        captured_at=datetime(2026, 9, 6, 7, 0, tzinfo=UTC),
        scope="service:search_index_service",
        verdicts={"DELETE": "COMPLIANT"},
        kind="readback",
    )
    verdict, fact = SubmissionRecords.assess("DELETE", [f_old, f_new])
    assert verdict == "COMPLIANT"
    assert fact == f_new


def test_temporal_not_found_then_found_in_same_file_and_scope() -> None:
    # 2. NOT_FOUND -> FOUND in one file, same scope
    f_old = Fact(
        evidence_id="evidence_02",
        at=datetime(2026, 8, 20, 10, 0, tzinfo=UTC),
        captured_at=datetime(2026, 8, 25, 10, 0, tzinfo=UTC),
        scope="service:export_service",
        verdicts={"DELETE": "COMPLIANT"},
        kind="readback",
    )
    f_new = Fact(
        evidence_id="evidence_02",
        at=datetime(2026, 8, 25, 10, 0, tzinfo=UTC),
        captured_at=datetime(2026, 8, 25, 10, 0, tzinfo=UTC),
        scope="service:export_service",
        verdicts={"DELETE": "VIOLATION"},
        kind="readback",
    )
    verdict, fact = SubmissionRecords.assess("DELETE", [f_old, f_new])
    assert verdict == "VIOLATION"
    assert fact == f_new


def test_temporal_older_replica_present_newer_primary_absent() -> None:
    # 3. Older replica PRESENT + newer primary ABSENT
    f_replica = Fact(
        evidence_id="evidence_03",
        at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        captured_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        scope="table:users_replica",
        verdicts={"DELETE": "VIOLATION"},
        kind="readback",
    )
    f_primary = Fact(
        evidence_id="evidence_04",
        at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
        captured_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
        scope="table:users_primary",
        verdicts={"DELETE": "COMPLIANT"},
        kind="readback",
    )
    verdict, fact = SubmissionRecords.assess("DELETE", [f_replica, f_primary])
    assert verdict == "VIOLATION"
    assert fact == f_replica


def test_temporal_direct_readback_vs_snapshot_omission() -> None:
    # 4. Direct readback versus snapshot omission
    t = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    readback = Fact(
        evidence_id="evidence_readback",
        at=t,
        captured_at=t,
        scope="service:search_index_service",
        verdicts={"DELETE": "VIOLATION"},
        kind="readback",
    )
    omission = Fact(
        evidence_id="evidence_snapshot",
        at=t,
        captured_at=t,
        scope="service:search_index_service",
        verdicts={"DELETE": "COMPLIANT"},
        kind="listing",
    )
    # At same observation time, readback outranks snapshot omission
    verdict, fact = SubmissionRecords.assess("DELETE", [readback, omission])
    assert verdict == "VIOLATION"
    assert fact == readback

    # When snapshot omission is newer in the same scope, the newer omission wins
    t_newer = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    newer_omission = Fact(
        evidence_id="evidence_snapshot_new",
        at=t_newer,
        captured_at=t_newer,
        scope="service:search_index_service",
        verdicts={"DELETE": "COMPLIANT"},
        kind="listing",
    )
    verdict2, fact2 = SubmissionRecords.assess("DELETE", [readback, newer_omission])
    assert verdict2 == "COMPLIANT"
    assert fact2 == newer_omission


def test_temporal_contradictory_same_time_observations() -> None:
    # 5. Contradictory same-time observations
    t = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    f_violation = Fact(
        evidence_id="evidence_a",
        at=t,
        captured_at=t,
        scope="service:customer_service",
        verdicts={"DELETE": "VIOLATION"},
        kind="readback",
    )
    f_compliant = Fact(
        evidence_id="evidence_b",
        at=t,
        captured_at=t,
        scope="service:customer_service",
        verdicts={"DELETE": "COMPLIANT"},
        kind="readback",
    )
    verdict, fact = SubmissionRecords.assess("DELETE", [f_violation, f_compliant])
    assert verdict == "UNKNOWN"
    assert fact is None


def test_temporal_post_audit_evidence_excluded() -> None:
    # 6. Post-audit evidence excluded
    audit_at = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)
    f_valid = Fact(
        evidence_id="evidence_early",
        at=datetime(2026, 9, 5, 0, 0, tzinfo=UTC),
        captured_at=datetime(2026, 9, 5, 0, 0, tzinfo=UTC),
        scope="service:backup_service",
        verdicts={"BLOCK": "COMPLIANT"},
        kind="readback",
    )
    f_post_at = Fact(
        evidence_id="evidence_late_at",
        at=datetime(2026, 9, 15, 0, 0, tzinfo=UTC),
        captured_at=datetime(2026, 9, 15, 0, 0, tzinfo=UTC),
        scope="service:backup_service",
        verdicts={"BLOCK": "VIOLATION"},
        kind="readback",
    )
    f_post_captured = Fact(
        evidence_id="evidence_late_captured",
        at=datetime(2026, 9, 5, 0, 0, tzinfo=UTC),
        captured_at=datetime(2026, 9, 20, 0, 0, tzinfo=UTC),
        scope="service:backup_service",
        verdicts={"BLOCK": "VIOLATION"},
        kind="readback",
    )
    verdict, fact = SubmissionRecords.assess(
        "BLOCK", [f_valid, f_post_at, f_post_captured], audit_at=audit_at
    )
    assert verdict == "COMPLIANT"
    assert fact == f_valid


def test_temporal_dataset_regressions_case_86_and_case_390(
    participant_dataset: Dataset,
) -> None:
    # 7. Real dataset regressions involving case_86 and case_390
    predictor = SubmissionPredictor(participant_dataset)

    req_86 = next(r for r in participant_dataset.requests if r.case_id == "case_86")
    pred_86 = predictor.predict_case(req_86)
    assert pred_86.row.deletion_status == "COMPLETE"
    assert not any(s.phase == "FINDING" for s in pred_86.row.steps)
    account_step_86 = next(s for s in pred_86.row.steps if s.resource_id == "account_8473")
    assert account_step_86.operation == "VERIFY_RECORD_ABSENT"
    assert account_step_86.evidence_id == "evidence_08"

    req_390 = next(r for r in participant_dataset.requests if r.case_id == "case_390")
    pred_390 = predictor.predict_case(req_390)
    assert pred_390.row.deletion_status == "COMPLETE"
    assert not any(s.phase == "FINDING" for s in pred_390.row.steps)
    account_step_390 = next(s for s in pred_390.row.steps if s.resource_id == "account_7618")
    assert account_step_390.operation == "VERIFY_RECORD_ABSENT"
    assert account_step_390.evidence_id == "evidence_36"
