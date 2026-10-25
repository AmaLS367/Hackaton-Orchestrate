"""Strict CSV decoding and atomic validated output publication."""

import csv
import json
import os
import tempfile
from pathlib import Path

from ghost_audit.domain.citation_validation import validate_output
from ghost_audit.domain.evidence_index import EvidenceIndex
from ghost_audit.domain.models import DeletionRequest
from ghost_audit.domain.output_contract import OUTPUT_COLUMNS, OutputRow
from ghost_audit.infrastructure.serialization.csv_records import read_csv


def read_output(path: Path) -> list[OutputRow]:
    """Read canonical official rows and reject malformed, duplicate or unsorted cases."""
    rows = []
    seen = set()
    for number, row in enumerate(read_csv(path, OUTPUT_COLUMNS), 2):
        try:
            steps = json.loads(row["steps_json"])
            parsed = OutputRow.model_validate(
                {
                    "case_id": row["case_id"],
                    "deletion_status": row["deletion_status"],
                    "steps": steps,
                }
            )
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{path.name}: invalid output row {number}") from exc
        if parsed.case_id in seen:
            raise ValueError(f"{path.name}: duplicate case_id")
        seen.add(parsed.case_id)
        rows.append(parsed)
    if [row.case_id for row in rows] != sorted(seen):
        raise ValueError(f"{path.name}: rows must be sorted by case_id")
    return rows


def write_output(
    path: Path,
    rows: list[OutputRow],
    requests: list[DeletionRequest],
    evidence: EvidenceIndex | None = None,
) -> None:
    """Validate the complete result before atomically replacing the destination CSV."""
    ordered = sorted(rows, key=lambda row: row.case_id)
    validate_output(ordered, requests, evidence)
    # Validate everything before replacing any existing output.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
            writer.writeheader()
            for row in ordered:
                writer.writerow(
                    {
                        "case_id": row.case_id,
                        "deletion_status": row.deletion_status,
                        "steps_json": json.dumps(
                            [s.model_dump() for s in row.steps],
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    }
                )
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
