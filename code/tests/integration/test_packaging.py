import json
import tomllib
import zipfile
from pathlib import Path

import pytest
from package_submission import ROOT, build_archive
from package_traces import discover, sanitized_jsonl


def test_submission_archive_is_deterministic_and_excludes_private_or_generated_files(
    tmp_path: Path,
) -> None:
    for name in (
        "README.md",
        "LICENSE",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        ".editorconfig",
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        "code/main.py",
        "code/tests/test_example.py",
        "code/evaluation/evaluation_report.md",
        "code/evaluation/usage_report.md",
        "docs/architecture.md",
        "code/tests/fixtures/baseline_contract.json",
        "dataset/private.json",
        ".env",
        "code/.env",
        "code/secret.zip",
        "code/__pycache__/cache.pyc",
        "code/.venv/private.py",
        "code/evaluation/full_prediction_diagnostics.json",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nreadme = "README.md"\nlicense = { file = "LICENSE" }\n'
    )
    first, second = tmp_path / "one.zip", tmp_path / "two.zip"
    assert build_archive(tmp_path, first) == build_archive(tmp_path, second)
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert "LICENSE" in archive.namelist()
        assert "code/main.py" in archive.namelist()
        assert "pyproject.toml" in archive.namelist()
        assert "uv.lock" in archive.namelist()
        assert not any(Path(name).name == "requirements.txt" for name in archive.namelist())
        assert "code/tests/test_example.py" in archive.namelist()
        assert "evaluation/evaluation_report.md" in archive.namelist()
        assert "evaluation/usage_report.md" in archive.namelist()
        assert "docs/architecture.md" in archive.namelist()
        assert "code/tests/fixtures/baseline_contract.json" in archive.namelist()
        assert not any(
            "dataset" in n or "private" in n or "secret" in n or "diagnostics" in n
            for n in archive.namelist()
        )


def test_archive_refuses_metadata_referencing_a_file_it_would_omit(tmp_path: Path) -> None:
    for name in ("README.md", "LICENSE", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", ".editorconfig"):
        (tmp_path / name).write_text(name)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nreadme = "README.md"\nlicense = { file = "NOTICE" }\n'
    )
    for name in ("uv.lock", ".python-version"):
        (tmp_path / name).write_text(name)
    for report in ("evaluation_report.md", "usage_report.md"):
        path = tmp_path / "code/evaluation" / report
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report)
    (tmp_path / "docs").mkdir()
    with pytest.raises(ValueError, match="NOTICE"):
        build_archive(tmp_path, tmp_path / "out.zip")


def test_real_archive_contains_every_file_install_metadata_references(tmp_path: Path) -> None:
    first, second = tmp_path / "one.zip", tmp_path / "two.zip"
    assert build_archive(ROOT, first) == build_archive(ROOT, second)
    assert first.read_bytes() == second.read_bytes()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    referenced = {project["readme"], project["license"]["file"]}
    with zipfile.ZipFile(first) as archive:
        names = set(archive.namelist())
        extracted_pyproject = tomllib.loads(archive.read("pyproject.toml").decode())["project"]
    assert extracted_pyproject == project
    required = referenced | {
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        "LICENSE",
        "README.md",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        ".editorconfig",
        "evaluation/evaluation_report.md",
        "evaluation/usage_report.md",
        "code/main.py",
    }
    assert required <= names, sorted(required - names)
    forbidden_parts = {"dataset", ".venv", ".git", "__pycache__", ".env"}
    forbidden_names = {"output.csv", "code.zip", "agent-trace.zip", "log.txt"}
    assert not any(
        forbidden_parts & set(Path(n).parts) or Path(n).name in forbidden_names for n in names
    )


def test_trace_redaction_preserves_structured_jsonl_and_safe_raw_lines(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    safe = '{"type": "message", "text": "safe synthetic data"}\n'
    path.write_text(
        safe
        + json.dumps(
            {
                "api_key": "fictional-secret-value",
                "text": "Bearer " + "x" * 32,
                "creator_account_id": "private-account",
            }
        )
        + "\n"
    )
    data, count = sanitized_jsonl(path)
    assert count == 1 and data.startswith(safe.encode())
    assert (
        b"fictional-secret-value" not in data
        and b"private-account" not in data
        and b"x" * 32 not in data
    )
    assert len([json.loads(line) for line in data.splitlines()]) == 2


def test_trace_discovery_excludes_other_checkouts_and_active_session(tmp_path: Path) -> None:
    codex = tmp_path / "codex"
    folder = codex / "sessions/2026/10/24"
    folder.mkdir(parents=True)
    (folder / "rollout-empty.jsonl").write_text("")
    for name, cwd in [
        ("relevant", str(tmp_path)),
        ("active", str(tmp_path)),
        ("unrelated", "/elsewhere"),
    ]:
        (folder / f"rollout-{name}.jsonl").write_text(
            json.dumps({"type": "session_meta", "payload": {"cwd": cwd, "id": name}}) + "\n"
        )
    files = discover(tmp_path, codex, tmp_path / "claude", {"active"})
    assert list(files) == ["agent-trace/codex/sessions/2026/10/24/rollout-relevant.jsonl"]
