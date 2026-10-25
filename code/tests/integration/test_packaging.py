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
        "Dockerfile",
        ".dockerignore",
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
    for name in (
        "README.md",
        "LICENSE",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        ".editorconfig",
        "Dockerfile",
        ".dockerignore",
    ):
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
        "Dockerfile",
        ".dockerignore",
        "evaluation/evaluation_report.md",
        "evaluation/usage_report.md",
        "code/main.py",
    }
    assert required <= names, sorted(required - names)
    with zipfile.ZipFile(first) as archive:
        assert not [n for n in names if b"\r\n" in archive.read(n)]
    forbidden_parts = {"dataset", ".venv", ".git", "__pycache__", ".env"}
    forbidden_names = {"output.csv", "code.zip", "agent-trace.zip", "log.txt"}
    assert not any(
        forbidden_parts & set(Path(n).parts) or Path(n).name in forbidden_names for n in names
    )


_CHECKOUT_TEXT = {
    "README.md": "# Ghost Data — données personnelles 日本語 🔒\nsecond line\n",
    "LICENSE": "MIT-style licence text\nCopyright holder: «fictional»\n",
    "CONTRIBUTING.md": "Contributing\n",
    "CODE_OF_CONDUCT.md": "Conduct\n",
    ".editorconfig": "root = true\n\n[*]\nend_of_line = lf\n",
    "Dockerfile": "FROM python:3.12-slim\nRUN echo ok \\\n    && true\n",
    ".dockerignore": "dataset/\noutput.csv\n",
    "pyproject.toml": '[project]\nname = "x"\nreadme = "README.md"\nlicense = { file = "LICENSE" }\n',
    "uv.lock": 'version = 1\n\n[[package]]\nname = "x"\n',
    ".python-version": "3.12\n",
    "code/main.py": 'print("naïve café")\n',
    "code/tests/test_example.py": "def test_ok() -> None:\n    assert True\n",
    "code/tests/fixtures/baseline_contract.json": '{\n  "key": "valeur é"\n}\n',
    "code/evaluation/evaluation_report.md": "# Evaluation\n",
    "code/evaluation/usage_report.md": "# Usage\n",
    "docs/architecture.md": "# Architecture\n\nparagraph\n",
}


def _write_checkout(root: Path, newline: str) -> None:
    """Write the same logical text as a Git checkout would with the given line ending."""
    for name, text in _CHECKOUT_TEXT.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.replace("\n", newline).encode("utf-8"))


def test_archive_is_byte_identical_for_lf_and_crlf_checkouts(tmp_path: Path) -> None:
    lf_root, crlf_root = tmp_path / "lf", tmp_path / "crlf"
    _write_checkout(lf_root, "\n")
    _write_checkout(crlf_root, "\r\n")
    lf_archive, crlf_archive = tmp_path / "lf.zip", tmp_path / "crlf.zip"
    assert build_archive(lf_root, lf_archive) == build_archive(crlf_root, crlf_archive)
    assert lf_archive.read_bytes() == crlf_archive.read_bytes()
    with zipfile.ZipFile(crlf_archive) as archive:
        for name, text in _CHECKOUT_TEXT.items():
            assert archive.read(name).decode("utf-8") == text
        assert not any(b"\r" in archive.read(name) for name in archive.namelist())


def test_archive_bytes_do_not_depend_on_the_host_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_checkout(tmp_path / "root", "\n")
    digests = {}
    for platform in ("win32", "linux"):
        monkeypatch.setattr("sys.platform", platform)
        digests[platform] = build_archive(tmp_path / "root", tmp_path / f"{platform}.zip")
    assert digests["win32"] == digests["linux"]
    with zipfile.ZipFile(tmp_path / "win32.zip") as archive:
        assert {info.create_system for info in archive.infolist()} == {3}
        assert {info.date_time for info in archive.infolist()} == {(2026, 1, 1, 0, 0, 0)}
        assert archive.namelist() == sorted(archive.namelist())


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [
        ("README.md", b"a\r\nb\r\n", b"a\nb\n"),
        ("code/main.py", b"print(1)\nprint(2)\n", b"print(1)\nprint(2)\n"),
        ("LICENSE", b"\xef\xbb\xbfMIT \xc2\xab\xe6\x97\xa5\xe6\x9c\xac\xc2\xbb\r\n", None),
        ("code/a.py", b"x = 1\rprint(2)\r\n", b"x = 1\rprint(2)\n"),
        ("Dockerfile", b"FROM scratch\r\n\r\nCMD x\r\n", b"FROM scratch\n\nCMD x\n"),
        ("uv.lock", b"version = 1\r\n", b"version = 1\n"),
    ],
)
def test_text_assets_lose_only_crlf_pairs(name: str, data: bytes, expected: bytes | None) -> None:
    from package_submission import normalize_text

    if expected is None:  # BOM and multi-byte characters must survive byte for byte
        expected = data.replace(b"\r\n", b"\n")
        assert normalize_text(name, data).startswith(b"\xef\xbb\xbfMIT \xc2\xab")
    assert normalize_text(name, data) == expected


@pytest.mark.parametrize(
    "name",
    [
        "logo.png",
        "evidence/scan.pdf",
        "data/rows.csv",
        "dataset/db.sql",
        "bundle.zip",
        "NOTICE.bin",
    ],
)
def test_other_file_types_keep_their_exact_bytes(name: str) -> None:
    from package_submission import normalize_text

    data = b"\x89PNG\r\n\x1a\n\xff\xfe\r\nrow,1\r\n"
    assert normalize_text(name, data) == data


def test_invalid_utf8_in_a_text_asset_is_rejected_instead_of_rewritten() -> None:
    from package_submission import normalize_text

    with pytest.raises(ValueError, match=r"docs/broken\.md"):
        normalize_text("docs/broken.md", b"caf\xe9\r\n")


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
