"""Publication policy lives in the application; adapters only serialize prepared data."""

import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from ghost_audit.application.abstention_diagnostics import summarize
from ghost_audit.application.strict_audit import (
    PredictionBlocked,
    diagnostics,
    predict,
    publishable_rows,
)
from ghost_audit.domain.dataset import Dataset
from ghost_audit.domain.evidence_index import EvidenceIndex
from ghost_audit.domain.models import DeletionRule
from ghost_audit.domain.policy_models import PredictionRun
from ghost_audit.infrastructure.serialization.prediction_artifacts import (
    write_abstention_diagnostics,
    write_diagnostics,
)

from tests.fixtures.audit_cases import dataset, observation
from tests.fixtures.paths import PROJECT_ROOT
from tests.regression.test_architecture import dependency_graph


def test_infrastructure_never_imports_application() -> None:
    for module, dependencies in dependency_graph().items():
        if module.startswith("ghost_audit.infrastructure."):
            assert not any(name.startswith("ghost_audit.application.") for name in dependencies), (
                module
            )


def _lint(root: Path, contract: dict[str, object]) -> subprocess.CompletedProcess[str]:
    config = root / "contracts.toml"
    config.write_text(
        "[tool.importlinter]\n"
        'root_packages = ["ghost_audit"]\n\n'
        "[[tool.importlinter.contracts]]\n"
        f"name = {json.dumps(contract['name'])}\n"
        f"type = {json.dumps(contract['type'])}\n"
        f"source_modules = {json.dumps(contract['source_modules'])}\n"
        f"forbidden_modules = {json.dumps(contract['forbidden_modules'])}\n",
        encoding="utf-8",
    )
    lint = shutil.which("lint-imports", path=str(Path(sys.executable).parent))
    assert lint is not None
    # The copied package shadows the installed one, so only the copy is analysed.
    return subprocess.run(
        [lint, "--config", str(config)],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_import_linter_rejects_an_infrastructure_import_of_application(tmp_path: Path) -> None:
    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    [contract] = [
        c
        for c in config["tool"]["importlinter"]["contracts"]
        if c["name"] == "Infrastructure never imports application"
    ]
    assert contract["source_modules"] == ["ghost_audit.infrastructure"]
    assert contract["forbidden_modules"] == ["ghost_audit.application"]
    package = tmp_path / "ghost_audit"
    shutil.copytree(
        PROJECT_ROOT / "code/ghost_audit", package, ignore=shutil.ignore_patterns("__pycache__")
    )
    assert _lint(tmp_path, contract).returncode == 0
    adapter = package / "infrastructure/serialization/csv_records.py"
    adapter.write_text(
        "import ghost_audit.application.strict_audit  # noqa: F401\n"
        + adapter.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    result = _lint(tmp_path, contract)
    assert result.returncode != 0
    assert "BROKEN" in result.stdout and "csv_records" in result.stdout


def _run(rules: list[DeletionRule], grounded: bool) -> tuple[Dataset, PredictionRun]:
    data = dataset(rules, observation()) if grounded else dataset(rules)
    return data, predict(data)


def test_prepared_diagnostics_serialize_deterministically_in_the_original_layout(
    rules: list[DeletionRule], tmp_path: Path
) -> None:
    _, run = _run(rules, grounded=False)
    summary = diagnostics(run)
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    write_diagnostics(first, summary, run)
    write_diagnostics(second, summary, run)
    assert first.read_bytes() == second.read_bytes()
    expected = {
        "summary": summary,
        "cases": [case.model_dump(mode="json") for case in run.cases],
        "abstentions": [record.model_dump(mode="json") for record in run.abstentions],
    }
    assert first.read_text(encoding="utf-8") == (
        json.dumps(expected, ensure_ascii=False, indent=2) + "\n"
    )


def test_abstention_diagnostics_keep_one_compact_case_per_line(
    rules: list[DeletionRule], tmp_path: Path
) -> None:
    _, run = _run(rules, grounded=False)
    assert run.abstentions
    path = tmp_path / "abstentions.json"
    write_abstention_diagnostics(path, summarize(run.abstentions), run.abstentions)
    text = path.read_text(encoding="utf-8")
    assert text.startswith('{"summary": {\n "abstentions": 1,')
    lines = text.split('\n"cases": [\n', 1)[1].removesuffix("\n]}\n").split(",\n")
    assert [json.loads(line) for line in lines] == [
        r.model_dump(mode="json") for r in run.abstentions
    ]
    assert json.loads(text)["summary"] == json.loads(json.dumps(summarize(run.abstentions)))


def test_committed_abstention_artifact_matches_the_full_strict_run(
    strict_result: tuple[Dataset, EvidenceIndex, PredictionRun], tmp_path: Path
) -> None:
    _, _, run = strict_result
    path = tmp_path / "abstention_diagnostics.json"
    write_abstention_diagnostics(path, summarize(run.abstentions), run.abstentions)
    committed = PROJECT_ROOT / "code/evaluation/abstention_diagnostics.json"
    assert path.read_text(encoding="utf-8") == committed.read_text(encoding="utf-8")


def test_publication_gate_belongs_to_the_application(rules: list[DeletionRule]) -> None:
    _, blocked = _run(rules, grounded=False)
    with pytest.raises(PredictionBlocked, match="1 cases have no grounded prediction"):
        publishable_rows(blocked)
    _, grounded = _run(rules, grounded=True)
    assert publishable_rows(grounded) == grounded.predictions


def test_blocked_strict_cli_preserves_existing_output_and_exits_2(
    rules: list[DeletionRule],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ghost_audit.interfaces import cli

    monkeypatch.setattr(cli, "load_dataset", lambda *a, **k: dataset(rules))
    out = tmp_path / "output.csv"
    out.write_text("previous output", encoding="utf-8")
    args = ["--strict", "--predictions", str(out), "--diagnostics", str(tmp_path / "d.json")]
    assert cli.main(args) == 2
    assert json.loads(capsys.readouterr().out)["output_written"] is False
    assert out.read_text(encoding="utf-8") == "previous output"


def test_rejected_artifact_paths_write_no_diagnostics(
    rules: list[DeletionRule], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ghost_audit.interfaces import cli

    root, data = tmp_path / "repo", tmp_path / "dataset"
    data.mkdir()
    monkeypatch.setattr(cli, "ROOT", root)
    monkeypatch.setattr(cli, "load_dataset", lambda *a, **k: dataset(rules, observation()))
    with pytest.raises(SystemExit):
        cli.main(["--dataset", str(data), "--predictions", str(data / "output.csv")])
    assert not root.exists() and not any(data.iterdir())
