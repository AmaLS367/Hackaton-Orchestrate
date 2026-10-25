"""Build and verify a deterministic source-only code.zip; never packages dataset or traces.

Archive bytes depend only on file content, not on the host: entries are sorted, carry fixed
timestamps, permissions and creator system, and known UTF-8 text is stored with LF endings
so Windows (core.autocrlf) and Linux checkouts of the same commit give identical archives.
"""

import argparse
import hashlib
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
# Only these known UTF-8 text assets are line-ending normalized. Every other type keeps its
# exact bytes: binaries by definition, and CSV, logs or SQL snapshots because their CRLF
# rows or embedded CR bytes can be data rather than checkout noise (none is packaged today).
TEXT_SUFFIXES = frozenset({".py", ".md", ".json", ".toml", ".lock"})
TEXT_NAMES = frozenset(
    {"LICENSE", "Dockerfile", ".dockerignore", ".editorconfig", ".python-version"}
)
ROOT_FILES = (
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
)
REPORTS = ("evaluation_report.md", "usage_report.md")


def metadata_files(pyproject: bytes) -> set[str]:
    """Name the local files that build metadata requires for installation."""
    project = tomllib.loads(pyproject.decode())["project"]
    readme, license_ = project.get("readme"), project.get("license")
    names = {readme} if isinstance(readme, str) else set()
    if isinstance(readme, dict) and "file" in readme:
        names.add(readme["file"])
    if isinstance(license_, dict) and "file" in license_:
        names.add(license_["file"])
    return names


def normalize_text(name: str, data: bytes) -> bytes:
    """Return known UTF-8 text with CRLF replaced by LF; any other file is returned unchanged.

    The replacement is byte-level, which is safe for UTF-8 because CR and LF never occur
    inside a multi-byte sequence. A BOM, lone CR and all other characters are preserved.
    Text that is not valid UTF-8 is rejected rather than silently rewritten.
    """
    path = PurePosixPath(name)
    if path.suffix not in TEXT_SUFFIXES and path.name not in TEXT_NAMES:
        return data
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{name} is not valid UTF-8 text; refusing to rewrite it") from exc
    return data.replace(b"\r\n", b"\n")


def contents(root: Path) -> dict[str, bytes]:
    """Collect allowed source, documentation and fixture files without participant data."""
    files = {name: normalize_text(name, (root / name).read_bytes()) for name in ROOT_FILES}
    missing = metadata_files(files["pyproject.toml"]) - files.keys()
    if missing:
        raise ValueError(f"pyproject.toml references files absent from the archive: {missing}")
    for directory in (root / "code", root / "docs"):
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(root)
            if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
                continue
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
                continue
            fixture = relative.is_relative_to("code/tests/fixtures") and path.suffix == ".json"
            if path.suffix in {".py", ".md"} or fixture:
                name = relative.as_posix()
                files[name] = normalize_text(name, path.read_bytes())
    # The challenge requires these archive-root paths; source locations stay intact.
    for name in REPORTS:
        archive_name = "evaluation/" + name
        files[archive_name] = normalize_text(
            archive_name, (root / "code/evaluation" / name).read_bytes()
        )
    return files


def build_archive(root: Path, destination: Path) -> str:
    """Write sorted fixed-timestamp entries and verify their CRCs and source bytes."""
    root, destination = root.resolve(), destination.resolve()
    if destination.is_relative_to(root / "dataset"):
        raise ValueError("archive must remain outside the read-only dataset")
    files = contents(root)
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3  # ZipInfo would otherwise record the building host's OS
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None or archive.namelist() != sorted(files):
            raise ValueError("archive content/CRC verification failed")
        for name, data in files.items():
            if archive.read(name) != data:
                raise ValueError(f"archive bytes differ: {name}")
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def main() -> None:
    """Run this terminal command and preserve its documented exit behavior."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=ROOT / "code.zip")
    args = parser.parse_args()
    digest = build_archive(ROOT, args.destination)
    print(f"Verified {args.destination}: sha256={digest}")


if __name__ == "__main__":
    main()
