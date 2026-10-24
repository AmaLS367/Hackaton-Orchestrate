"""Testing-only CLI. Sample labels never enter the production ingestion path."""

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.scoring import evaluate
from ghost_audit.csvio import load_models
from ghost_audit.models import DeletionRequest
from ghost_audit.output import read_output, validate_output

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "dataset")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--predictions", type=Path, help="Independent sample predictions to score")
    group.add_argument("--check-reference", action="store_true", help="Check public sample schema only")
    args = parser.parse_args(argv)
    requests = load_models(args.dataset / "sample_deletion_requests.csv", DeletionRequest, "case_id")
    references = read_output(args.dataset / "sample_output.csv")
    validate_output(references, requests)
    if args.check_reference:
        print(f"Validated {len(references)} public sample reference rows; no prediction accuracy measured.")
    else:
        if args.predictions.resolve() == (args.dataset / "sample_output.csv").resolve():
            parser.error("sample_output.csv is a reference, not an independent prediction file")
        metrics = evaluate(read_output(args.predictions), references)
        print(metrics.markdown())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
