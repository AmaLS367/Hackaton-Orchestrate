"""Phase 1 terminal entry point: inspect inputs or validate supplied predictions."""

import argparse
import json
from pathlib import Path

from ghost_audit.index import EvidenceIndex
from ghost_audit.ingestion import load_dataset
from ghost_audit.output import read_output, validate_output

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "validate-output", "phase2"), nargs="?", default="inspect")
    parser.add_argument("--dataset", type=Path, default=ROOT / "dataset")
    parser.add_argument("--samples", action="store_true")
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--case-id", help="Inspect one Phase 2 case (includes raw fictional evidence)")
    args = parser.parse_args(argv)
    if args.command == "validate-output" and args.predictions is None:
        parser.error("validate-output requires --predictions")
    dataset = load_dataset(args.dataset, samples=args.samples)
    index = EvidenceIndex(dataset.observations, registry=dataset.registry)
    if args.command == "phase2":
        from ghost_audit.phase2 import Phase2Analyzer, diagnostics

        requests = sorted(dataset.requests, key=lambda r: r.case_id)
        if args.case_id:
            requests = [r for r in requests if r.case_id == args.case_id]
            if not requests:
                parser.error('case_id is not in the selected request set')
        analyzer = Phase2Analyzer(dataset, index)
        bundles = [analyzer.analyze(request) for request in requests]
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
            "prediction_engine": "not implemented in Phase 1",
        }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
