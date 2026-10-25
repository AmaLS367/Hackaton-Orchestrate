"""Exact contract hashes protect predictions without committing participant records."""

import hashlib
import json
import subprocess
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import pytest
from evaluation.scoring import evaluate
from ghost_audit.application.strict_audit import predict
from ghost_audit.application.submission_service import predict_submission, submission_diagnostics
from ghost_audit.infrastructure.serialization.csv_output import read_output, write_output
from ghost_audit.infrastructure.serialization.prediction_artifacts import write_diagnostics
from regression import stable

from tests.fixtures.paths import DATASET_ROOT, PROJECT_ROOT


@pytest.fixture(scope="module")
def contract():
    path = Path(__file__).resolve().parents[1] / "fixtures/baseline_contract.json"
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_hash(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def test_original_parametrized_scenarios_are_still_collected(contract):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "code/tests"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    collected = Counter(
        line.split("::", 1)[1] for line in result.stdout.splitlines() if "::" in line
    )
    expected = []
    for scenario in contract["original_scenarios"]:
        name, separator, parameters = scenario.partition("[")
        expected.append(contract["scenario_renames"].get(name, name) + separator + parameters)
    assert len(expected) == 499
    assert not Counter(expected) - collected


def test_participant_inputs_are_byte_identical_to_the_protected_baseline(contract):
    inputs = {
        path.relative_to(DATASET_ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(DATASET_ROOT.rglob("*"))
        if path.is_file()
    }
    assert canonical_hash(inputs) == contract["dataset_sha256"]


def test_all_submission_statuses_and_ordered_steps_match_original_bytes(
    participant_dataset, submission_cases, contract, tmp_path
):
    output = tmp_path / "output.csv"
    write_output(output, [case.row for case in submission_cases], participant_dataset.requests)
    assert hashlib.sha256(output.read_bytes()).hexdigest() == contract["output_sha256"]
    assert (
        dict(Counter(case.row.deletion_status for case in submission_cases)) == contract["counts"]
    )
    assert sum(len(case.row.steps) for case in submission_cases) == contract["steps"]


def test_strict_decisions_steps_and_every_abstention_remain_identical(
    strict_result, contract, tmp_path
):
    _, _, run = strict_result
    path = tmp_path / "strict.json"
    write_diagnostics(path, run)
    payload = stable(json.loads(path.read_text(encoding="utf-8")), PROJECT_ROOT, tmp_path)
    assert canonical_hash(payload) == contract["strict_sha256"], (
        "Run code/regression.py for a per-case diff"
    )


def test_submission_attribution_and_low_confidence_remain_identical(submission_cases, contract):
    assert canonical_hash(submission_diagnostics(submission_cases)) == contract["submission_sha256"]


def test_every_public_sample_metric_matches_the_baseline(sample_dataset, contract):
    rows = [case.row for case in predict_submission(sample_dataset)]
    references = read_output(DATASET_ROOT / "sample_output.csv")
    assert asdict(evaluate(rows, references)) == contract["sample_metrics"]


def test_every_strict_sample_metric_matches_the_baseline(sample_dataset, contract):
    run = predict(sample_dataset)
    references = read_output(DATASET_ROOT / "sample_output.csv")
    assert asdict(evaluate(run.predictions, references)) == contract["strict_sample_metrics"]
