"""Offline deletion audit: predict, inspect evidence, or validate an output."""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from ghost_audit.domain.citation_validation import validate_output
from ghost_audit.domain.dataset import Dataset
from ghost_audit.domain.evidence_index import EvidenceIndex
from ghost_audit.infrastructure.ingestion.dataset_loader import load_dataset
from ghost_audit.infrastructure.serialization.csv_output import read_output

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class _ArtifactPaths:
    diagnostics: Path
    predictions: Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("predict", "inspect", "validate-output", "phase2", "phase3"),
        nargs="?",
        default="predict",
    )
    parser.add_argument("--dataset", type=Path, default=ROOT / "dataset")
    parser.add_argument("--samples", action="store_true")
    parser.add_argument("--predictions", type=Path)
    parser.add_argument(
        "--diagnostics", type=Path, help="Prediction diagnostic JSON (includes abstentions)"
    )
    parser.add_argument(
        "--case-id", help="Inspect one Phase 2/3 case (includes raw fictional evidence)"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Publish only the strict audit engine's fully grounded predictions (abstains otherwise)",
    )
    return parser


def _validate_arguments(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.command == "validate-output" and args.predictions is None:
        parser.error("validate-output requires --predictions")
    if args.command == "validate-output" and not args.predictions.is_file():
        parser.error(
            "prediction file does not exist; a blocked prediction run does not create output.csv"
        )
    if args.case_id and args.command not in {"phase2", "phase3"}:
        parser.error("--case-id is supported only for phase2 and phase3")


def main(argv: list[str] | None = None) -> int:
    """Parse terminal options, assemble dependencies and dispatch one use case."""
    parser = _parser()
    args = parser.parse_args(argv)
    _validate_arguments(args, parser)
    dataset = load_dataset(args.dataset, samples=args.samples)
    index = EvidenceIndex(dataset.observations, registry=dataset.registry)
    if args.command == "predict":
        return _predict(args, parser, dataset, index)
    if args.command in {"phase2", "phase3"}:
        return _inspect_case(args, parser, dataset, index)
    if args.command == "validate-output":
        return _validate_predictions(args, dataset, index)
    return _inspect_dataset(dataset, index)


def _predict(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    dataset: Dataset,
    index: EvidenceIndex,
) -> int:
    from ghost_audit.application.strict_audit import PredictionBlocked, diagnostics, predict
    from ghost_audit.infrastructure.serialization.prediction_artifacts import (
        publish,
        write_abstention_diagnostics,
        write_diagnostics,
    )

    run = predict(dataset, index)
    diagnostic_path = args.diagnostics or ROOT / "code/evaluation" / (
        "sample_prediction_diagnostics.json" if args.samples else "full_prediction_diagnostics.json"
    )
    # Identifier-only root causes of every abstention, written beside the diagnostics.
    write_abstention_diagnostics(
        diagnostic_path.with_name(
            ("sample_" if args.samples else "") + "abstention_diagnostics.json"
        ),
        run,
    )
    output_path = args.predictions or ROOT / (
        "sample_predictions.csv" if args.samples else "output.csv"
    )
    if diagnostic_path.resolve() == output_path.resolve():
        parser.error("diagnostics and predictions must use different paths")
    if any(
        path.resolve().is_relative_to(args.dataset.resolve())
        for path in (diagnostic_path, output_path)
    ):
        parser.error("prediction artifacts must be outside the read-only dataset directory")
    write_diagnostics(diagnostic_path, run)
    summary: dict[str, object] = dict(diagnostics(run))
    if args.strict:
        try:
            publish(output_path, run, dataset, index)
        except PredictionBlocked as exc:
            summary.update(output_written=False, error=str(exc))
            print(json.dumps(summary, indent=2))
            return 2
        summary.update(output_written=True, output_path=str(output_path))
        print(json.dumps(summary, indent=2))
        return 0
    # Submission pathway: the best-supported official answer for every request. The
    # strict diagnostics above are kept as the audit-confidence record.
    return _publish_submission(
        args, dataset, index, _ArtifactPaths(diagnostic_path, output_path), summary
    )


def _publish_submission(
    args: argparse.Namespace,
    dataset: Dataset,
    index: EvidenceIndex,
    paths: _ArtifactPaths,
    summary: dict[str, object],
) -> int:
    from ghost_audit.application.submission_service import (
        predict_submission,
        submission_diagnostics,
    )
    from ghost_audit.infrastructure.serialization.csv_output import write_output

    try:
        cases = predict_submission(dataset)
    except ValueError as exc:
        print(json.dumps({"output_written": False, "error": str(exc)}, indent=2))
        return 2
    write_output(paths.predictions, [c.row for c in cases], dataset.requests, index)
    report = submission_diagnostics(cases)
    submission_path = paths.diagnostics.with_name(
        ("sample_" if args.samples else "") + "submission_diagnostics.json"
    )
    submission_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "strict_engine": {k: summary[k] for k in ("status_counts", "undecidable_count")},
                "submission": report["summary"],
                "output_written": True,
                "output_path": str(paths.predictions),
                "diagnostics_path": str(submission_path),
            },
            indent=2,
        )
    )

    return 0


def _inspect_case(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    dataset: Dataset,
    index: EvidenceIndex,
) -> int:
    from ghost_audit.application.evidence_association import (
        EvidenceAssociationService,
    )
    from ghost_audit.application.evidence_association import (
        diagnostics as association_diagnostics,
    )

    requests = sorted(dataset.requests, key=lambda r: r.case_id)
    if args.case_id:
        requests = [r for r in requests if r.case_id == args.case_id]
        if not requests:
            parser.error("case_id is not in the selected request set")
    analyzer = EvidenceAssociationService(dataset, index)
    bundles = [analyzer.analyze(request) for request in requests]
    if args.command == "phase3":
        from ghost_audit.application.temporal_diagnostics import diagnostics as state_diagnostics
        from ghost_audit.application.temporal_service import TemporalStateEngine

        engine = TemporalStateEngine(index)
        state_bundles = [engine.analyze(bundle) for bundle in bundles]
        payload = (
            state_bundles[0].model_dump_json(indent=2)
            if args.case_id
            else json.dumps(state_diagnostics(state_bundles), indent=2)
        )
    else:
        payload = (
            bundles[0].model_dump_json(indent=2)
            if args.case_id
            else json.dumps(association_diagnostics(bundles), indent=2)
        )
    print(payload)
    return 0


def _validate_predictions(args: argparse.Namespace, dataset: Dataset, index: EvidenceIndex) -> int:
    rows = read_output(args.predictions)
    checks = validate_output(rows, dataset.requests, index)
    print(
        f"Validated {len(rows)} rows. Citation existence/time checks do not establish semantic correctness."
    )
    unknown = sum(check.resource_support == "unknown" for check in checks)
    print(
        f"{unknown} citations have unknown resource support. All cited state claims remain unverified."
    )

    return 0


def _inspect_dataset(dataset: Dataset, index: EvidenceIndex) -> int:
    print(
        json.dumps(
            {
                "requests": len(dataset.requests),
                "identities": len(dataset.identities),
                "identity_changes": len(dataset.identity_changes),
                "activities": len(dataset.activities),
                "rules": len(dataset.rules),
                "evidence_files": len(dataset.documents),
                "parsed_files": sum(doc.status == "parsed" for doc in dataset.documents),
                "deferred_files": sum(doc.status == "deferred" for doc in dataset.documents),
                "observations": len(index.observations),
                "prediction_engine": "deterministic submission predictor (best-supported answer per request); "
                "--strict publishes only the abstaining audit engine's grounded predictions",
            },
            indent=2,
        )
    )

    return 0
