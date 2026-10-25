import json
import zipfile

from package_submission import build_archive
from package_traces import discover, sanitized_jsonl


def test_submission_archive_is_deterministic_and_excludes_private_or_generated_files(tmp_path):
    for name in (
        "README.md",
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        "code/main.py",
        "code/requirements.txt",
        "code/tests/test_example.py",
        "code/evaluation/evaluation_report.md",
        "code/evaluation/usage_report.md",
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
    first, second = tmp_path / "one.zip", tmp_path / "two.zip"
    assert build_archive(tmp_path, first) == build_archive(tmp_path, second)
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert "code/main.py" in archive.namelist()
        assert "code/tests/test_example.py" in archive.namelist()
        assert "evaluation/evaluation_report.md" in archive.namelist()
        assert "evaluation/usage_report.md" in archive.namelist()
        assert not any(
            "dataset" in n or "private" in n or "secret" in n or "diagnostics" in n
            for n in archive.namelist()
        )


def test_trace_redaction_preserves_structured_jsonl_and_safe_raw_lines(tmp_path):
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


def test_trace_discovery_excludes_other_checkouts_and_active_session(tmp_path):
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
