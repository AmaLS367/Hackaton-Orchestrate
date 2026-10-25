"""Testing-only CLI. Sample labels never enter the production ingestion path."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ghost_audit.domain.citation_validation import validate_output
from ghost_audit.domain.models import DeletionRequest
from ghost_audit.infrastructure.serialization.csv_output import read_output
from ghost_audit.infrastructure.serialization.csv_records import load_models

from evaluation.failures import failure_analysis
from evaluation.scoring import evaluate

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "dataset")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--predictions", type=Path, help="Independent sample predictions to score")
    group.add_argument(
        "--check-reference", action="store_true", help="Check public sample schema only"
    )
    group.add_argument(
        "--run",
        action="store_true",
        help="Independently predict all samples, counting abstentions as errors",
    )
    parser.add_argument("--diagnostics", type=Path, help="Write prediction diagnostics for --run")
    parser.add_argument(
        "--engine",
        choices=("submission", "strict"),
        default="submission",
        help="Prediction pathway for --run (strict counts abstentions as errors)",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print metrics and per-case failure analysis as JSON"
    )
    args = parser.parse_args(argv)
    if args.diagnostics and args.diagnostics.resolve().is_relative_to(args.dataset.resolve()):
        parser.error("diagnostics must be outside the read-only dataset directory")
    requests = load_models(
        args.dataset / "sample_deletion_requests.csv", DeletionRequest, "case_id"
    )
    references = read_output(args.dataset / "sample_output.csv")
    validate_output(references, requests)
    if args.check_reference:
        print(
            f"Validated {len(references)} public sample reference rows; no prediction accuracy measured."
        )
    else:
        run = None
        summary = None
        if args.run and args.engine == "submission":
            from ghost_audit.application.submission_service import (
                predict_submission,
                submission_diagnostics,
            )
            from ghost_audit.infrastructure.ingestion.dataset_loader import load_dataset

            cases = predict_submission(load_dataset(args.dataset, samples=True))
            predictions = [c.row for c in cases]
            report = submission_diagnostics(cases)
            summary = report["summary"]
            if args.diagnostics:
                args.diagnostics.write_text(
                    json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
                )
        elif args.run:
            from ghost_audit.application.strict_audit import diagnostics, predict
            from ghost_audit.infrastructure.ingestion.dataset_loader import load_dataset
            from ghost_audit.infrastructure.serialization.prediction_artifacts import (
                write_diagnostics,
            )

            run = predict(load_dataset(args.dataset, samples=True))
            predictions = run.predictions
            summary = diagnostics(run)
            if args.diagnostics:
                write_diagnostics(args.diagnostics, run)
        else:
            if args.predictions.resolve() == (args.dataset / "sample_output.csv").resolve():
                parser.error("sample_output.csv is a reference, not an independent prediction file")
            predictions = read_output(args.predictions)
        metrics = evaluate(predictions, references)
        failures = failure_analysis(predictions, references, run.cases if run else ())
        result = {"metrics": asdict(metrics), "failures": failures}
        if summary is not None:
            result["prediction_summary"] = summary
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(metrics.markdown())
            print(
                f"- missing_steps: {failures['missing_steps']}\n- extra_steps: {failures['extra_steps']}"
                f"\n- incorrect_evidence_references: {failures['incorrect_evidence_references']}"
            )
            print("Failure investigation groups (nonexclusive):")
            for key, cases in failures["failure_groups"].items():
                print(f"- {key}: {len(cases)} ({', '.join(cases)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
