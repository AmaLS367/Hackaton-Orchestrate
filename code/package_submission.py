"""Build and verify a deterministic source-only code.zip; never packages dataset or traces."""

import argparse
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = ('README.md', 'pyproject.toml', 'uv.lock', '.python-version')
REPORTS = ('evaluation_report.md', 'usage_report.md')


def contents(root: Path) -> dict[str, bytes]:
    files = {name: (root / name).read_bytes() for name in ROOT_FILES}
    for path in sorted((root / 'code').rglob('*')):
        relative = path.relative_to(root)
        if any(part.startswith('.') or part == '__pycache__' for part in relative.parts):
            continue
        if path.is_file() and path.suffix in {'.py', '.md'} or path == root / 'code/requirements.txt':
            files[relative.as_posix()] = path.read_bytes()
    # The challenge requires these archive-root paths; source locations stay intact.
    for name in REPORTS:
        files['evaluation/' + name] = (root / 'code/evaluation' / name).read_bytes()
    return files


def build_archive(root: Path, destination: Path) -> str:
    root, destination = root.resolve(), destination.resolve()
    if destination.is_relative_to(root / 'dataset'):
        raise ValueError('archive must remain outside the read-only dataset')
    files = contents(root)
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None or archive.namelist() != sorted(files):
            raise ValueError('archive content/CRC verification failed')
        for name, data in files.items():
            if archive.read(name) != data:
                raise ValueError(f'archive bytes differ: {name}')
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=ROOT / 'code.zip')
    args = parser.parse_args()
    digest = build_archive(ROOT, args.destination)
    print(f'Verified {args.destination}: sha256={digest}')


if __name__ == '__main__':
    main()
