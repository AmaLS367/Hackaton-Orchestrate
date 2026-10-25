import pytest
from evaluation.scoring import evaluate
from ghost_audit.domain.output_contract import OutputRow, OutputStep


def complete(case_id="fictional_deletion", evidence_id="fixture_file"):
    return OutputRow(
        case_id=case_id,
        deletion_status="COMPLETE",
        steps=[
            OutputStep(
                step_no=1,
                phase="VERIFICATION",
                system_id="account_service",
                resource_id="fictional_profile",
                operation="VERIFY_RECORD_ABSENT",
                state="ABSENT",
                evidence_id=evidence_id,
            )
        ],
    )


def test_custom_case_non_deletion_requires_empty_steps():
    reference = OutputRow(
        case_id="fictional_export_only", deletion_status="NOT_APPLICABLE", steps=[]
    )
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


def test_failure_analysis_distinguishes_wrong_citation_and_missing_case():
    from evaluation.failures import failure_analysis

    references = [complete("one"), complete("two")]
    result = failure_analysis([complete("one", "wrong_file")], references)
    assert result["missing_steps"] == 2 and result["extra_steps"] == 1
    assert result["incorrect_evidence_references"] == 1
    assert result["failure_groups"]["Ordering and evidence selection"] == ["one"]
    assert result["cases"][1]["predicted_status"] == "ABSTAINED"


def test_sample_run_harness_counts_abstentions_against_all_32_cases(
    dataset_path, monkeypatch, capsys
):
    import json

    import ghost_audit.application.strict_audit
    from evaluation.main import main
    from ghost_audit.domain.models import DeletionRequest
    from ghost_audit.domain.policy_models import CaseDecision, PredictionRun
    from ghost_audit.infrastructure.serialization.csv_records import load_models

    requests = load_models(
        dataset_path / "sample_deletion_requests.csv", DeletionRequest, "case_id"
    )
    run = PredictionRun(
        cases=[
            CaseDecision(
                case_id=r.case_id,
                decision="UNDECIDABLE",
                prediction=None,
                assessments=[],
                unresolved=["synthetic_missing_evidence"],
                blockers=["no_grounded_answer"],
            )
            for r in requests
        ],
        elapsed_seconds=0.0,
    )
    monkeypatch.setattr(ghost_audit.application.strict_audit, "predict", lambda *a, **k: run)
    assert main(["--run", "--engine", "strict", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["metrics"]["reference_cases"] == result["metrics"]["missing_cases"] == 32
    assert result["metrics"]["status_accuracy"] == result["metrics"]["exact_case_accuracy"] == 0
