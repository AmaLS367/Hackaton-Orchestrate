"""Read only the participant allowlist; parse each manifest file once per load."""

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import timedelta
from pathlib import Path

from pypdf import PdfReader

from .csvio import load_models
from .extraction import (
    COLLECTION_SYSTEMS, ExtractionContext, parse_csv, parse_json, parse_text, timestamps,
)
from .index import EvidenceRegistry
from .models import (
    Activity, DeletionRequest, DeletionRule, EvidenceDocument, EvidenceFile, Identity,
    IdentityChange, Observation, Provenance, ResourceRef,
)
from .ocr import image_panels, image_text
from .sql import parse_sql

# "Data catalog linked export_1 (NST-...) to ..." / "Attachment catalog confirmed object_1 (object_1.pdf) ..."
CATALOG_LINK = re.compile(r"(?:linked|confirmed) (?P<resource>[\w-]+) \((?P<alias>[^)]+)\)")
RESOURCE_TOKEN = re.compile(r"(?<![\w-])(?!user_)[a-z]+(?:_[a-z]+)*_\d+(?![\w-])")
EMAIL_TOKEN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
USER_TOKEN = re.compile(r"(?<![\w-])user_\d+(?![\w-])")


def catalog_references(activities: list[Activity]) -> dict[str, tuple[str, str, object]]:
    """Reference text -> (system, resource, catalogued_at) from data-catalog link events."""
    references = {}
    for activity in sorted(activities, key=lambda a: a.activity_id):
        match = CATALOG_LINK.search(activity.details)
        if (activity.event_type == 'LINK_RESOURCE_IDENTITY' and activity.target_system
                and match and match['resource'] == activity.resource_id):
            for key in (activity.resource_id, match['alias']):
                if not EMAIL_TOKEN.fullmatch(key):
                    references.setdefault(key, (activity.target_system, activity.resource_id, activity.event_time))
    return references


def document_observations(text: str, context: ExtractionContext, catalog: dict[str, tuple[str, str, object]],
                          *, catalogued_only: bool) -> list[Observation]:
    """One document-level observation per explicitly referenced resource.

    Line observations cannot connect a subject on one line to a resource on another.
    Resources are explicit tokens or catalogued reference texts; a manifest origin
    supplies the system only when it is a known participant system. A reference text
    other than the resource ID itself (a statement number, or a subject key shown as a
    page title) matches only a document captured within a day of its catalogue entry.
    OCR uses catalogued resources only and keeps just the lines naming the reference,
    so neither a misread token nor another customer's row on the same screen is used.
    """
    origin = context.manifest.origin if context.manifest.origin in set(COLLECTION_SYSTEMS.values()) else None
    found = {}
    for token in RESOURCE_TOKEN.findall(text):
        if catalogued_only and token not in catalog:
            continue
        system, resource = catalog[token][:2] if token in catalog else (origin, token)
        if system:
            found.setdefault((system, resource), token)
    captured = context.manifest.captured_at
    for alias, (system, resource, at) in sorted(catalog.items()):
        if alias != resource and re.search(rf'(?<![\w-]){re.escape(alias)}(?![\w-])', text) \
                and abs(captured - at) <= timedelta(days=1):
            found.setdefault((system, resource), alias)
    observations = []
    for (system, resource), reference in sorted(found.items()):
        scoped = text if not catalogued_only else "\n".join(
            line for line in text.splitlines() if reference in line)
        emails = sorted(set(EMAIL_TOKEN.findall(scoped)))
        users = sorted(set(USER_TOKEN.findall(scoped)))
        payload = {'resource_id': resource, 'document_reference': reference, 'document_text': scoped}
        if catalogued_only:
            payload['ocr_identity_unverified'] = True
        if len(emails) == 1:
            payload['email'] = emails[0]
        if len(users) == 1:
            payload['subject_reference'] = users[0]
        observations.append(replace(context, system=system).observation(
            payload, f'document:{resource}', raw_text=scoped))
    return observations


def evidence_path(dataset: Path, relative: str) -> Path:
    candidate = Path(relative)
    path = (dataset / candidate).resolve()
    if candidate.is_absolute() or not path.is_relative_to(dataset.resolve() / "evidence"):
        raise ValueError("manifest path must remain inside dataset/evidence")
    return path


def parse_document(dataset: Path, manifest: EvidenceFile,
                   catalog: dict[str, tuple[str, str, object]] | None = None) -> EvidenceDocument:
    path = evidence_path(dataset, manifest.file_path)
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    context = ExtractionContext(manifest, digest)
    catalog = catalog or {}
    notes = []
    status = "parsed"
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        observations = []
        pages = []
        for page_no, page in enumerate(PdfReader(path).pages, 1):
            text = page.extract_text() or ""
            pages.append(text)
            observations.extend(parse_text(text, context, f"page:{page_no}:line"))
            if not text.strip():
                status = "deferred"
                notes.append(f"Page {page_no} has no extractable text; OCR is required.")
        observations.extend(document_observations("\n".join(pages), context, catalog, catalogued_only=False))
    elif suffix in {".png", ".jpg", ".jpeg"}:
        observations = []
        status = "deferred"
        text = image_text(path, digest)
        if text is None:
            notes.append("Image content retained by manifest and digest; OCR is unavailable.")
        else:
            # Raw OCR is an unverified extraction: only catalogued resources become
            # observations, and identifiers must still match exactly downstream.
            observations = document_observations(text, context, catalog, catalogued_only=True)
            for reference, panel in image_panels(path, digest):
                if reference not in catalog:
                    continue
                # A spatially isolated detail panel can link fields on different
                # lines to its exact title; OCR identifiers still need an independent
                # structured identity/resource anchor in the correlator.
                for observation in document_observations(panel, context, {reference: catalog[reference]},
                                                         catalogued_only=False):
                    if observation.payload['document_reference'] != reference:
                        continue
                    observations.append(observation.model_copy(update={
                        'payload': {**observation.payload, 'ocr_identity_unverified': True,
                                    'ocr_method': 'tesseract_psm11_spatial_detail_panel'},
                        'provenance': observation.provenance.model_copy(update={
                            'locator': observation.provenance.locator + ':ocr-panel'})}))
            status = "parsed" if observations else "deferred"
            notes.append("Tesseract OCR (default + PSM 11 spatial panels); catalogued resources only; "
                         "identifiers require independent linkage.")
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
    # Every participant request (both request files): the deletion workflow's
    # activity stream is shared, so batch attribution must see all of them.
    workflow_requests: list[DeletionRequest] = field(default_factory=list)
    registry: EvidenceRegistry = field(init=False)

    def __post_init__(self):
        self.registry = EvidenceRegistry(documents=self.documents, activities=self.activities,
                                         identity_changes=self.identity_changes)


def row_observations(filename, rows, key, kind, time_field, digest) -> list[Observation]:
    """CSV rows (identities, identity changes, activity claims) as provenance-bearing observations."""
    observations = []
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
    return observations


def load_dataset(dataset: Path, *, samples: bool = False) -> Dataset:
    """Never opens sample_output.csv, organizer files, or the prediction template."""
    dataset = dataset.resolve()
    request_file = "sample_deletion_requests.csv" if samples else "deletion_requests.csv"
    requests = load_models(dataset / request_file, DeletionRequest, "case_id")
    workflow_requests = {r.case_id: r for name in ("sample_deletion_requests.csv", "deletion_requests.csv")
                         if (dataset / name).is_file()
                         for r in load_models(dataset / name, DeletionRequest, "case_id")}
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
    return Dataset(requests, identities, changes, activities, rules, documents, observations,
                   workflow_requests=sorted(workflow_requests.values(), key=lambda r: r.case_id))
