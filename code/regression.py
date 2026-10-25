"""Capture or compare a protected, local behavioral baseline (never packaged data)."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOLATILE_KEYS = {"runtime_seconds", "elapsed_seconds"}


def stable(value: object, workspace: Path, destination: Path) -> object:
    """Remove elapsed clocks and machine-specific artifact paths, retaining decisions."""
    if isinstance(value, dict):
        return {
            key: stable(item, workspace, destination)
            for key, item in value.items()
            if key not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [stable(item, workspace, destination) for item in value]
    if isinstance(value, str):
        return value.replace(str(destination), "<artifacts>").replace(str(workspace), "<root>")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def output_cases(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as stream:
        return [
            {**row, "steps_json": json.loads(row["steps_json"])} for row in csv.DictReader(stream)
        ]


def source_inventory(root: Path) -> dict:
    """Record imports, public interfaces and large functions before changing structure."""
    inventory = {}
    for path in sorted((root / "code").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        inventory[path.relative_to(root).as_posix()] = {
            "imports": [
                ast.unparse(node)
                for node in ast.walk(tree)
                if isinstance(node, (ast.Import, ast.ImportFrom))
            ],
            "interfaces": [
                node.name
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                and not node.name.startswith("_")
            ],
            "functions": {
                node.name: (node.end_lineno or node.lineno) - node.lineno + 1
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef)
            },
        }
    return inventory


def capture(destination: Path, *, root: Path = ROOT, run_tests: bool = True) -> dict:
    """Run the supported interfaces against unchanged participant inputs."""
    destination.mkdir(parents=True, exist_ok=True)
    if (destination / "snapshot.json").exists():
        raise ValueError("refusing to overwrite a captured baseline; select a new directory")
    commands = {}

    def run(name: str, arguments: list[str], expected: int = 0) -> None:
        process = subprocess.run(
            [sys.executable, *arguments],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        (destination / f"{name}.stdout.txt").write_text(process.stdout, encoding="utf-8")
        (destination / f"{name}.stderr.txt").write_text(process.stderr, encoding="utf-8")
        try:
            stdout = json.loads(process.stdout)
        except ValueError:
            stdout = process.stdout
        commands[name] = {
            "exit_code": process.returncode,
            "stdout": stable(stdout, root, destination),
        }
        print(f"{name}: exit {process.returncode}", flush=True)
        if process.returncode != expected:
            raise RuntimeError(f"{name}: expected exit {expected}; inspect {destination}")

    inputs_before = {
        p.relative_to(root / "dataset").as_posix(): digest(p)
        for p in sorted((root / "dataset").rglob("*"))
        if p.is_file()
    }
    if run_tests:
        run("tests", ["-m", "pytest", "-q"])
        run("collection", ["-m", "pytest", "--collect-only", "-q"])
    run("help", ["code/main.py", "--help"])
    run("inspect", ["code/main.py", "inspect"])
    run("association", ["code/main.py", "phase2"])
    run("temporal", ["code/main.py", "phase3"])
    with (root / "dataset/deletion_requests.csv").open(encoding="utf-8-sig") as stream:
        case_id = next(csv.DictReader(stream))["case_id"]
    for command in ("phase2", "phase3"):
        run(command + "_case", ["code/main.py", command, "--case-id", case_id])
    strict = destination / "strict.json"
    run(
        "strict",
        [
            "code/main.py",
            "--strict",
            "--predictions",
            str(destination / "strict.csv"),
            "--diagnostics",
            str(strict),
        ],
        expected=2,
    )
    run("submission", ["code/main.py", "--diagnostics", str(destination / "submission.json")])
    run("validation", ["code/main.py", "validate-output", "--predictions", "output.csv"])
    run(
        "sample_prediction",
        [
            "code/main.py",
            "--samples",
            "--predictions",
            str(destination / "samples.csv"),
            "--diagnostics",
            str(destination / "samples.json"),
        ],
    )
    run("sample_evaluation", ["code/evaluation/main.py", "--run", "--json"])
    run("strict_evaluation", ["code/evaluation/main.py", "--run", "--engine", "strict", "--json"])
    run(
        "independent_evaluation",
        ["code/evaluation/main.py", "--predictions", str(destination / "samples.csv"), "--json"],
    )
    run("reference", ["code/evaluation/main.py", "--check-reference"])
    run("evaluation_help", ["code/evaluation/main.py", "--help"])
    run("missing_predictions", ["code/main.py", "validate-output"], expected=2)
    run("invalid_case_option", ["code/main.py", "inspect", "--case-id", case_id], expected=2)
    run("package", ["code/package_submission.py", "--destination", str(destination / "code.zip")])
    run("package_help", ["code/package_submission.py", "--help"])
    run("trace_help", ["code/package_traces.py", "--help"])
    inputs_after = {
        p.relative_to(root / "dataset").as_posix(): digest(p)
        for p in sorted((root / "dataset").rglob("*"))
        if p.is_file()
    }
    if inputs_before != inputs_after:
        raise RuntimeError("participant dataset changed")
    output = root / "output.csv"
    (destination / "output.csv").write_bytes(output.read_bytes())
    cases = output_cases(output)
    snapshot = {
        "output_sha256": digest(output),
        "cases": cases,
        "counts": dict(Counter(row["deletion_status"] for row in cases)),
        "steps": sum(len(row["steps_json"]) for row in cases),
        "commands": commands,
        "strict": stable(json.loads(strict.read_text(encoding="utf-8")), root, destination),
        "submission": stable(
            json.loads((destination / "submission_diagnostics.json").read_text(encoding="utf-8")),
            root,
            destination,
        ),
        "dataset_sha256": inputs_before,
    }
    (destination / "snapshot.json").write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (destination / "inventory.json").write_text(
        json.dumps(source_inventory(root), indent=2) + "\n", encoding="utf-8"
    )
    return snapshot


def compare(baseline: Path, current: Path) -> list[dict]:
    """Produce a structured per-case diff; exact arrays include all seven step fields."""
    old = json.loads((baseline / "snapshot.json").read_text(encoding="utf-8"))
    new = json.loads((current / "snapshot.json").read_text(encoding="utf-8"))
    changes = []
    for field in ("output_sha256", "counts", "steps", "dataset_sha256", "strict", "submission"):
        if old[field] != new[field]:
            changes.append({"field": field, "before": old[field], "after": new[field]})
    before = {row["case_id"]: row for row in old["cases"]}
    after = {row["case_id"]: row for row in new["cases"]}
    for case_id in sorted(before.keys() | after.keys()):
        if before.get(case_id) != after.get(case_id):
            changes.append(
                {"case_id": case_id, "before": before.get(case_id), "after": after.get(case_id)}
            )
    # Help text and source/test inventories can change structurally. Business CLI
    # results, including invalid-command exit codes, must remain compatible.
    excluded = {
        "tests",
        "collection",
        "help",
        "evaluation_help",
        "package",
        "package_help",
        "trace_help",
    }
    for name in old["commands"].keys() - excluded:
        if old["commands"][name] != new["commands"].get(name):
            changes.append(
                {
                    "command": name,
                    "before": old["commands"][name],
                    "after": new["commands"].get(name),
                }
            )
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    capture(args.destination.resolve(), run_tests=not args.skip_tests)
    if args.baseline:
        changes = compare(args.baseline, args.destination)
        (args.destination / "diff.json").write_text(
            json.dumps(changes, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Behavior differences: {len(changes)}")
        return int(bool(changes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
