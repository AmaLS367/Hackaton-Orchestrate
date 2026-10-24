import pytest

from evaluation.scoring import evaluate
from ghost_audit.output import OutputRow, OutputStep


def complete(case_id="fictional_deletion", evidence_id="fixture_file"):
    return OutputRow(case_id=case_id, deletion_status="COMPLETE", steps=[OutputStep(
        step_no=1, phase="VERIFICATION", system_id="account_service", resource_id="fictional_profile",
        operation="VERIFY_RECORD_ABSENT", state="ABSENT", evidence_id=evidence_id,
    )])


def test_custom_case_non_deletion_requires_empty_steps():
    reference = OutputRow(case_id="fictional_export_only", deletion_status="NOT_APPLICABLE", steps=[])
    result = evaluate([reference], [reference])
    assert result.status_accuracy == result.step_accuracy == result.sequence_accuracy == 1


def test_custom_case_wrong_citation_is_a_field_and_step_error():
    result = evaluate([complete(evidence_id="wrong_file")], [complete()])
    assert result.status_accuracy == 1
    assert result.field_accuracy == pytest.approx(6 / 7)
    assert result.step_accuracy == result.sequence_accuracy == result.exact_case_accuracy == 0


def test_custom_case_missing_prediction_is_not_filled_or_ignored():
    result = evaluate([], [complete()])
    assert result.missing_cases == 1
    assert result.status_accuracy == result.step_accuracy == result.field_accuracy == 0


def test_status_and_sequence_are_separate_metrics():
    prediction = OutputRow(case_id="fictional_deletion", deletion_status="NOT_APPLICABLE", steps=[])
    result = evaluate([prediction], [complete()])
    assert result.status_accuracy == result.sequence_accuracy == 0


def test_self_comparison_is_harness_sanity_only():
    reference = complete()
    metrics = evaluate([reference], [reference])
    assert metrics.exact_case_accuracy == metrics.step_precision == metrics.step_recall == 1


def test_unknown_or_duplicate_cases_are_rejected():
    with pytest.raises(ValueError):
        evaluate([complete("unrelated")], [complete()])
    with pytest.raises(ValueError):
        evaluate([complete(), complete()], [complete()])
    with pytest.raises(ValueError):
        evaluate([], [])
