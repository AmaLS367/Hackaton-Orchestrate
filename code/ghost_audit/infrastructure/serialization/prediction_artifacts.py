"""Write strict diagnostics and publish only a fully supported run."""

import json
from pathlib import Path

from ghost_audit.application.abstention_diagnostics import summarize
from ghost_audit.application.strict_audit import PredictionBlocked, diagnostics
from ghost_audit.domain.dataset import Dataset
from ghost_audit.domain.evidence_index import EvidenceIndex
from ghost_audit.domain.policy_models import PredictionRun
from ghost_audit.infrastructure.serialization.csv_output import write_output


def write_diagnostics(path: Path, run: PredictionRun) -> None:
    """Explicit diagnostic artifact, including partial predictions; never a submission CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": diagnostics(run),
        "cases": [case.model_dump(mode="json") for case in run.cases],
        "abstentions": [record.model_dump(mode="json") for record in run.abstentions],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_abstention_diagnostics(path: Path, run: PredictionRun) -> None:
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
        for record in run.abstentions
    ]
    summary = json.dumps(summarize(run.abstentions), ensure_ascii=False, sort_keys=True, indent=1)
    path.write_text(
        '{"summary": ' + summary + ',\n"cases": [\n' + ",\n".join(cases) + "\n]}\n",
        encoding="utf-8",
    )


def publish(path: Path, run: PredictionRun, dataset: Dataset, index: EvidenceIndex) -> None:
    """Preserve the destination when a strict run has abstentions or validation errors."""
    if not run.publishable:
        raise PredictionBlocked(
            f"{len(run.cases) - len(run.predictions)} cases have no grounded prediction; "
            "output was not written or replaced. See diagnostics for blockers."
        )
    write_output(path, run.predictions, dataset.requests, index)
