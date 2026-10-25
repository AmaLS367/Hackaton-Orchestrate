"""Offline deletion audit: predict, inspect evidence, or validate an output."""

import argparse
import json
from pathlib import Path

from ghost_audit.index import EvidenceIndex
from ghost_audit.ingestion import load_dataset
from ghost_audit.output import read_output, validate_output

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("predict", "inspect", "validate-output", "phase2", "phase3"), nargs="?", default="predict")
    parser.add_argument("--dataset", type=Path, default=ROOT / "dataset")
    parser.add_argument("--samples", action="store_true")
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--diagnostics", type=Path, help="Prediction diagnostic JSON (includes abstentions)")
    parser.add_argument("--case-id", help="Inspect one Phase 2/3 case (includes raw fictional evidence)")
    parser.add_argument("--strict", action="store_true",
                        help="Publish only the strict audit engine's fully grounded predictions (abstains otherwise)")
    args = parser.parse_args(argv)
    if args.command == "validate-output" and args.predictions is None:
        parser.error("validate-output requires --predictions")
    if args.command == 'validate-output' and not args.predictions.is_file():
        parser.error('prediction file does not exist; a blocked prediction run does not create output.csv')
    if args.case_id and args.command not in {'phase2', 'phase3'}:
        parser.error('--case-id is supported only for phase2 and phase3')
    dataset = load_dataset(args.dataset, samples=args.samples)
    index = EvidenceIndex(dataset.observations, registry=dataset.registry)
    if args.command == 'predict':
        from ghost_audit.prediction import (
            PredictionBlocked, diagnostics, predict, publish, write_abstention_diagnostics, write_diagnostics,
        )

        run = predict(dataset, index)
        diagnostic_path = args.diagnostics or ROOT / 'code/evaluation' / (
            'sample_prediction_diagnostics.json' if args.samples else 'full_prediction_diagnostics.json')
        # Identifier-only root causes of every abstention, written beside the diagnostics.
        write_abstention_diagnostics(diagnostic_path.with_name(
            ('sample_' if args.samples else '') + 'abstention_diagnostics.json'), run)
        output_path = args.predictions or ROOT / ('sample_predictions.csv' if args.samples else 'output.csv')
        if diagnostic_path.resolve() == output_path.resolve():
            parser.error('diagnostics and predictions must use different paths')
        if any(path.resolve().is_relative_to(args.dataset.resolve()) for path in (diagnostic_path, output_path)):
            parser.error('prediction artifacts must be outside the read-only dataset directory')
        write_diagnostics(diagnostic_path, run)
        summary = diagnostics(run)
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
        from ghost_audit.output import write_output
        from ghost_audit.submission import predict_submission, submission_diagnostics

        try:
            cases = predict_submission(dataset)
        except ValueError as exc:
            print(json.dumps({'output_written': False, 'error': str(exc)}, indent=2))
            return 2
        write_output(output_path, [c.row for c in cases], dataset.requests, index)
        report = submission_diagnostics(cases)
        submission_path = diagnostic_path.with_name(('sample_' if args.samples else '') + 'submission_diagnostics.json')
        submission_path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        print(json.dumps({'strict_engine': {k: summary[k] for k in ('status_counts', 'undecidable_count')},
                          'submission': report['summary'], 'output_written': True,
                          'output_path': str(output_path), 'diagnostics_path': str(submission_path)}, indent=2))
    elif args.command in {"phase2", "phase3"}:
        from ghost_audit.phase2 import Phase2Analyzer, diagnostics

        requests = sorted(dataset.requests, key=lambda r: r.case_id)
        if args.case_id:
            requests = [r for r in requests if r.case_id == args.case_id]
            if not requests:
                parser.error('case_id is not in the selected request set')
        analyzer = Phase2Analyzer(dataset, index)
        bundles = [analyzer.analyze(request) for request in requests]
        if args.command == 'phase3':
            from ghost_audit.temporal import TemporalStateEngine
            from ghost_audit.phase3 import diagnostics

            engine = TemporalStateEngine(index)
            bundles = [engine.analyze(bundle) for bundle in bundles]
        print(bundles[0].model_dump_json(indent=2) if args.case_id
              else json.dumps(diagnostics(bundles), indent=2))
    elif args.command == "validate-output":
        rows = read_output(args.predictions)
        checks = validate_output(rows, dataset.requests, index)
        print(f"Validated {len(rows)} rows. Citation existence/time checks do not establish semantic correctness.")
        unknown = sum(check.resource_support == 'unknown' for check in checks)
        print(f'{unknown} citations have unknown resource support. All cited state claims remain unverified.')
    else:
        print(json.dumps({
            "requests": len(dataset.requests), "identities": len(dataset.identities),
            "identity_changes": len(dataset.identity_changes), "activities": len(dataset.activities),
            "rules": len(dataset.rules), "evidence_files": len(dataset.documents),
            "parsed_files": sum(doc.status == "parsed" for doc in dataset.documents),
            "deferred_files": sum(doc.status == "deferred" for doc in dataset.documents),
            "observations": len(index.observations),
            "prediction_engine": "deterministic submission predictor (best-supported answer per request); "
                                 "--strict publishes only the abstaining audit engine's grounded predictions",
        }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
