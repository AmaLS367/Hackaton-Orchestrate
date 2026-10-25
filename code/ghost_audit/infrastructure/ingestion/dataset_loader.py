"""Load only participant-facing CSVs and manifest evidence into domain inputs."""

import hashlib
from pathlib import Path
from ghost_audit.infrastructure.serialization.csv_records import load_models
from ghost_audit.infrastructure.parsers.structured import timestamps
from ghost_audit.domain.models import (
    Activity,
    DeletionRequest,
    DeletionRule,
    EvidenceFile,
    Identity,
    IdentityChange,
    Observation,
    Provenance,
    ResourceRef,
)

from ghost_audit.domain.dataset import Dataset
from ghost_audit.infrastructure.parsers.documents import catalog_references, parse_document


def row_observations(filename, rows, key, kind, time_field, digest) -> list[Observation]:
    """CSV rows (identities, identity changes, activity claims) as provenance-bearing observations."""
    observations = []
    for row_no, item in enumerate(rows, 2):
        payload = item.model_dump(mode="json")
        systems = sorted({payload[k] for k in ("source_system", "target_system") if payload.get(k)})
        resource = payload.get("resource_id")
        observations.append(
            Observation(
                provenance=Provenance(
                    evidence_id=getattr(item, key),
                    file_path=filename,
                    origin=filename,
                    locator=f"row:{row_no}",
                    captured_at=getattr(item, time_field),
                    sha256=digest,
                    timestamps=timestamps(payload, f"row:{row_no}"),
                ),
                kind=kind,
                payload=payload,
                system_ids=systems,
                resources=[ResourceRef(resource_id=resource, system_id=item.target_system or None)]
                if resource
                else [],
            )
        )
    return observations


def load_dataset(dataset: Path, *, samples: bool = False) -> Dataset:
    """Never opens sample_output.csv, organizer files, or the prediction template."""
    dataset = dataset.resolve()
    request_file = "sample_deletion_requests.csv" if samples else "deletion_requests.csv"
    requests = load_models(dataset / request_file, DeletionRequest, "case_id")
    workflow_requests = {
        r.case_id: r
        for name in ("sample_deletion_requests.csv", "deletion_requests.csv")
        if (dataset / name).is_file()
        for r in load_models(dataset / name, DeletionRequest, "case_id")
    }
    workflow_requests.update((r.case_id, r) for r in requests)
    identities = load_models(dataset / "user_identities.csv", Identity, "user_id")
    changes = load_models(dataset / "user_audit_log.csv", IdentityChange, "audit_id")
    activities = load_models(dataset / "system_activity.csv", Activity, "activity_id")
    rules = load_models(dataset / "deletion_rules.csv", DeletionRule, "rule_id")
    manifests = load_models(dataset / "evidence_files.csv", EvidenceFile, "file_id")
    catalog = catalog_references(activities)
    documents = [parse_document(dataset, manifest, catalog) for manifest in manifests]
    observations = [item for document in documents for item in document.observations]
    for filename, rows, key, kind, time_field in (
        ("user_identities.csv", identities, "user_id", "identity", "updated_at"),
        ("user_audit_log.csv", changes, "audit_id", "identity", "event_time"),
        ("system_activity.csv", activities, "activity_id", "activity_claim", "event_time"),
    ):
        digest = hashlib.sha256((dataset / filename).read_bytes()).hexdigest()
        observations.extend(row_observations(filename, rows, key, kind, time_field, digest))
    return Dataset(
        requests,
        identities,
        changes,
        activities,
        rules,
        documents,
        observations,
        workflow_requests=sorted(workflow_requests.values(), key=lambda r: r.case_id),
    )
