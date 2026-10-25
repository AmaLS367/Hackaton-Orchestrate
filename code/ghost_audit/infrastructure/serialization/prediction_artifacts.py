"""Write prepared strict diagnostics; publication policy stays in the application layer."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from ghost_audit.domain.diagnostic_models import AbstentionDiagnostic
from ghost_audit.domain.policy_models import PredictionRun


def write_diagnostics(path: Path, summary: Mapping[str, object], run: PredictionRun) -> None:
    """Explicit diagnostic artifact, including partial predictions; never a submission CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": summary,
        "cases": [case.model_dump(mode="json") for case in run.cases],
        "abstentions": [record.model_dump(mode="json") for record in run.abstentions],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_abstention_diagnostics(
    path: Path, summary: Mapping[str, object], records: Sequence[AbstentionDiagnostic]
) -> None:
    """Identifier-only case diagnostics and root-cause totals, safe to keep with the code."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # One compact case per line keeps the file small and reviewable as a diff.
    cases = [
        json.dumps(
            record.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for record in records
    ]
    text = json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=1)
    path.write_text(
        '{"summary": ' + text + ',\n"cases": [\n' + ",\n".join(cases) + "\n]}\n",
        encoding="utf-8",
    )
