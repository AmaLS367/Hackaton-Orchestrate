"""The comparator must expose real drift rather than trusting a matching CSV hash."""

import copy
import json
from pathlib import Path

import pytest
from regression import capture, compare, stable


def snapshot():
    return {
        "output_sha256": "synthetic-hash",
        "counts": {"COMPLETE": 1},
        "steps": 2,
        "dataset_sha256": {"synthetic.csv": "input-hash"},
        "cases": [
            {
                "case_id": "synthetic",
                "deletion_status": "COMPLETE",
                "steps_json": [
                    {
                        "step_no": 1,
                        "phase": "VERIFICATION",
                        "system_id": "store",
                        "resource_id": "first",
                        "operation": "VERIFY_RECORD_ABSENT",
                        "state": "ABSENT",
                        "evidence_id": "fixture",
                    },
                    {
                        "step_no": 2,
                        "phase": "VERIFICATION",
                        "system_id": "store",
                        "resource_id": "second",
                        "operation": "VERIFY_RECORD_ABSENT",
                        "state": "ABSENT",
                        "evidence_id": "fixture",
                    },
                ],
            }
        ],
        "strict": {
            "summary": {"undecidable_count": 0},
            "cases": [{"case_id": "synthetic", "decision": "COMPLETE"}],
            "abstentions": [],
        },
        "submission": {"summary": {}, "cases": [{"case_id": "synthetic", "low_confidence": []}]},
        "commands": {"sample_evaluation": {"exit_code": 0, "stdout": {"accuracy": 1.0}}},
    }


def stored_comparison(tmp_path, before, after):
    for name, value in (("before", before), ("after", after)):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "snapshot.json").write_text(json.dumps(value), encoding="utf-8")
    return compare(tmp_path / "before", tmp_path / "after")


def test_identical_snapshots_have_no_differences(tmp_path):
    assert stored_comparison(tmp_path, snapshot(), snapshot()) == []


@pytest.mark.parametrize(
    "field", ["step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"]
)
def test_each_official_step_field_is_compared_even_with_unchanged_hash(tmp_path, field):
    before = snapshot()
    after = copy.deepcopy(before)
    after["cases"][0]["steps_json"][0][field] = "changed"
    changes = stored_comparison(tmp_path, before, after)
    assert changes[0]["case_id"] == "synthetic"
    assert changes[0]["before"] != changes[0]["after"]


def test_step_order_is_part_of_the_contract(tmp_path):
    before = snapshot()
    after = copy.deepcopy(before)
    after["cases"][0]["steps_json"].reverse()
    assert stored_comparison(tmp_path, before, after)[0]["case_id"] == "synthetic"


@pytest.mark.parametrize(
    "change", ["status", "strict", "abstention", "confidence", "sample", "input", "missing_case"]
)
def test_decision_confidence_input_and_metric_drift_are_reported(tmp_path, change):
    before = snapshot()
    after = copy.deepcopy(before)
    if change == "status":
        after["cases"][0]["deletion_status"] = "INCOMPLETE"
    elif change == "strict":
        after["strict"]["cases"][0]["decision"] = "UNDECIDABLE"
    elif change == "abstention":
        after["strict"]["abstentions"].append({"case_id": "synthetic", "blockers": ["unknown"]})
    elif change == "confidence":
        after["submission"]["cases"][0]["low_confidence"] = ["first"]
    elif change == "sample":
        after["commands"]["sample_evaluation"]["stdout"]["accuracy"] = 0.5
    elif change == "input":
        after["dataset_sha256"]["synthetic.csv"] = "different"
    else:
        after["cases"] = []
    assert stored_comparison(tmp_path, before, after)


def test_only_elapsed_times_and_artifact_paths_are_normalized(tmp_path):
    payload = {
        "runtime_seconds": 1,
        "case": {"elapsed_seconds": 2, "audit_at": "fixed-cutoff"},
        "output_path": str(tmp_path / "artifacts/output.csv"),
    }
    result = stable(payload, tmp_path, tmp_path / "artifacts")
    assert result == {
        "case": {"audit_at": "fixed-cutoff"},
        "output_path": str(Path("<artifacts>") / "output.csv"),
    }


def test_completed_capture_cannot_be_overwritten(tmp_path):
    (tmp_path / "snapshot.json").write_text("protected", encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        capture(tmp_path)
    assert (tmp_path / "snapshot.json").read_text(encoding="utf-8") == "protected"
