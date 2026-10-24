"""Read only the participant allowlist; parse each manifest file once per load."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from .csvio import load_models
from .extraction import ExtractionContext, parse_csv, parse_json, parse_text, timestamps
from .models import (
    Activity, DeletionRequest, DeletionRule, EvidenceDocument, EvidenceFile, Identity,
    IdentityChange, Observation, Provenance, ResourceRef,
)
from .sql import parse_sql


def evidence_path(dataset: Path, relative: str) -> Path:
    candidate = Path(relative)
    path = (dataset / candidate).resolve()
    if candidate.is_absolute() or not path.is_relative_to(dataset.resolve() / "evidence"):
        raise ValueError("manifest path must remain inside dataset/evidence")
    return path


def parse_document(dataset: Path, manifest: EvidenceFile) -> EvidenceDocument:
    path = evidence_path(dataset, manifest.file_path)
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    context = ExtractionContext(manifest, digest)
    notes = []
    status = "parsed"
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        observations = []
        for page_no, page in enumerate(PdfReader(path).pages, 1):
            text = page.extract_text() or ""
            observations.extend(parse_text(text, context, f"page:{page_no}:line"))
            if not text.strip():
                status = "deferred"
                notes.append(f"Page {page_no} has no extractable text; OCR is required.")
    elif suffix in {".png", ".jpg", ".jpeg"}:
        observations = []
        status = "deferred"
        notes.append("Image content retained by manifest and digest; OCR/visual extraction is not implemented.")
    else:
        text = content.decode("utf-8-sig")
        if suffix == ".json":
            observations = parse_json(json.loads(text), context)
        elif suffix == ".sql":
            observations = parse_sql(text, context)
        elif suffix == ".csv":
            observations = parse_csv(text, context)
        elif suffix in {".log", ".txt"}:
            observations = parse_text(text, context)
        else:
            raise ValueError(f"unsupported evidence extension: {suffix}")
    return EvidenceDocument(manifest=manifest, sha256=digest, status=status,
                            observations=observations, notes=notes)


@dataclass
class Dataset:
    requests: list[DeletionRequest]
    identities: list[Identity]
    identity_changes: list[IdentityChange]
    activities: list[Activity]
    rules: list[DeletionRule]
    documents: list[EvidenceDocument]
    observations: list[Observation]


def load_dataset(dataset: Path, *, samples: bool = False) -> Dataset:
    """Never opens sample_output.csv, organizer files, or the prediction template."""
    dataset = dataset.resolve()
    request_file = "sample_deletion_requests.csv" if samples else "deletion_requests.csv"
    requests = load_models(dataset / request_file, DeletionRequest, "case_id")
    identities = load_models(dataset / "user_identities.csv", Identity, "user_id")
    changes = load_models(dataset / "user_audit_log.csv", IdentityChange, "audit_id")
    activities = load_models(dataset / "system_activity.csv", Activity, "activity_id")
    rules = load_models(dataset / "deletion_rules.csv", DeletionRule, "rule_id")
    manifests = load_models(dataset / "evidence_files.csv", EvidenceFile, "file_id")
    documents = [parse_document(dataset, manifest) for manifest in manifests]
    observations = [item for document in documents for item in document.observations]
    for filename, rows, key, kind, time_field in (
        ("user_identities.csv", identities, "user_id", "identity", "updated_at"),
        ("user_audit_log.csv", changes, "audit_id", "identity", "event_time"),
        ("system_activity.csv", activities, "activity_id", "activity_claim", "event_time"),
    ):
        digest = hashlib.sha256((dataset / filename).read_bytes()).hexdigest()
        for row_no, item in enumerate(rows, 2):
            payload = item.model_dump(mode="json")
            systems = sorted({payload[k] for k in ("source_system", "target_system") if payload.get(k)})
            resource = payload.get("resource_id")
            observations.append(Observation(
                provenance=Provenance(
                    evidence_id=getattr(item, key), file_path=filename, origin=filename,
                    locator=f"row:{row_no}", captured_at=getattr(item, time_field),
                    sha256=digest, timestamps=timestamps(payload, f"row:{row_no}"),
                ), kind=kind, payload=payload, system_ids=systems,
                resources=[ResourceRef(resource_id=resource, system_id=item.target_system or None)]
                if resource else [],
            ))
    return Dataset(requests, identities, changes, activities, rules, documents, observations)
