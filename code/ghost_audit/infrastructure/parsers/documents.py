"""Read and scope PDF, OCR and structured evidence without assigning case verdicts."""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import JsonValue
from pypdf import PdfReader

from ghost_audit.domain.catalog import COLLECTION_SYSTEMS
from ghost_audit.domain.models import (
    Activity,
    EvidenceDocument,
    EvidenceFile,
    Observation,
    SourceTimestamp,
)
from ghost_audit.infrastructure.parsers.image_ocr import image_panels, image_text
from ghost_audit.infrastructure.parsers.sql_snapshot import parse_sql
from ghost_audit.infrastructure.parsers.structured import (
    ExtractionContext,
    parse_csv,
    parse_json,
    parse_text,
)

CATALOG_LINK = re.compile(r"(?:linked|confirmed) (?P<resource>[\w-]+) \((?P<alias>[^)]+)\)")


RESOURCE_TOKEN = re.compile(r"(?<![\w-])(?!user_)[a-z]+(?:_[a-z]+)*_\d+(?![\w-])")


EMAIL_TOKEN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


USER_TOKEN = re.compile(r"(?<![\w-])user_\d+(?![\w-])")


def catalog_references(activities: list[Activity]) -> dict[str, tuple[str, str, datetime]]:
    """Reference text -> (system, resource, catalogued_at) from data-catalog link events."""
    references: dict[str, tuple[str, str, datetime]] = {}
    for activity in sorted(activities, key=lambda a: a.activity_id):
        match = CATALOG_LINK.search(activity.details)
        if (
            activity.event_type == "LINK_RESOURCE_IDENTITY"
            and activity.target_system
            and match
            and match["resource"] == activity.resource_id
        ):
            for key in (activity.resource_id, match["alias"]):
                if not EMAIL_TOKEN.fullmatch(key):
                    references.setdefault(
                        key, (activity.target_system, activity.resource_id, activity.event_time)
                    )
    return references


def section_text(text: str, reference: str) -> str:
    """The document section(s) naming a reference, narrowed to its own lines when mixed.

    Pages are separated by form feeds; a page headed "Continued" extends the previous
    section. A section naming more than one subject (several emails or user IDs) is a
    multi-person register: only the lines naming the reference describe its subject.
    """
    sections: list[str] = []
    for page in text.split("\f"):
        if sections and re.search(r"\bcontinued\b", page[:200], re.I):
            sections[-1] += "\n" + page
        else:
            sections.append(page)
    scoped = "\n".join(section for section in sections if reference in section)
    if len(set(EMAIL_TOKEN.findall(scoped))) > 1 or len(set(USER_TOKEN.findall(scoped))) > 1:
        scoped = "\n".join(line for line in scoped.splitlines() if reference in line)
    return scoped


def document_observations(
    text: str,
    context: ExtractionContext,
    catalog: Mapping[str, tuple[str, str, datetime | None]],
    *,
    catalogued_only: bool,
) -> list[Observation]:
    """One document-level observation per explicitly referenced resource.

    Line observations cannot connect a subject on one line to a resource on another.
    Resources are explicit tokens or catalogued reference texts; a manifest origin
    supplies the system only when it is a known participant system. A reference text
    other than the resource ID itself (a statement number, or a subject key shown as a
    page title) matches only a document captured within a day of its catalogue entry.
    OCR uses catalogued resources only and keeps just the lines naming the reference,
    so neither a misread token nor another customer's row on the same screen is used.
    A catalogue-derived reference is known only from its catalogue time, which becomes
    a source timestamp of the observation, so an earlier audit cannot use it.
    """
    origin = (
        context.manifest.origin
        if context.manifest.origin in set(COLLECTION_SYSTEMS.values())
        else None
    )
    found: dict[tuple[str, str], tuple[str, datetime | None]] = {}
    for token in RESOURCE_TOKEN.findall(text):
        if catalogued_only and token not in catalog:
            continue
        system, resource = catalog[token][:2] if token in catalog else (origin, token)
        if system:
            found.setdefault(
                (system, resource), (token, catalog[token][2] if token in catalog else None)
            )
    captured = context.manifest.captured_at
    for alias, (system, resource, at) in sorted(catalog.items()):
        if alias != resource and re.search(rf"(?<![\w-]){re.escape(alias)}(?![\w-])", text):
            assert at is not None, "non-ID catalogue aliases require an observation time"
            if abs(captured - at) <= timedelta(days=1):
                found.setdefault((system, resource), (alias, at))
    observations = []
    for (system, resource), (reference, catalogued_at) in sorted(found.items()):
        scoped = (
            section_text(text, reference)
            if not catalogued_only
            else "\n".join(line for line in text.splitlines() if reference in line)
        )
        emails = sorted(set(EMAIL_TOKEN.findall(scoped)))
        users = sorted(set(USER_TOKEN.findall(scoped)))
        payload: dict[str, JsonValue] = {
            "resource_id": resource,
            "document_reference": reference,
            "document_text": scoped,
        }
        if catalogued_only:
            payload["ocr_identity_unverified"] = True
        if len(emails) == 1:
            payload["email"] = emails[0]
        if len(users) == 1:
            payload["subject_reference"] = users[0]
        scope = replace(context, system=system)
        if catalogued_at is not None:
            scope = replace(
                scope,
                times=(
                    *scope.times,
                    SourceTimestamp(
                        locator=f"catalog:{reference}", field="catalogued_at", value=catalogued_at
                    ),
                ),
            )
        observations.append(scope.observation(payload, f"document:{resource}", raw_text=scoped))
    return observations


def evidence_path(dataset: Path, relative: str) -> Path:
    """Reject manifest paths escaping the participant evidence directory."""
    candidate = Path(relative)
    path = (dataset / candidate).resolve()
    if candidate.is_absolute() or not path.is_relative_to(dataset.resolve() / "evidence"):
        raise ValueError("manifest path must remain inside dataset/evidence")
    return path


def parse_document(
    dataset: Path,
    manifest: EvidenceFile,
    catalog: Mapping[str, tuple[str, str, datetime | None]] | None = None,
) -> EvidenceDocument:
    """Decode one manifest file while preserving provenance and explicit extraction deferrals."""
    path = evidence_path(dataset, manifest.file_path)
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    context = ExtractionContext(manifest, digest)
    catalog = catalog or {}
    notes = []
    status: Literal["parsed", "deferred"] = "parsed"
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
        # Form feeds keep page boundaries so each resource is scoped to its own section.
        observations.extend(
            document_observations("\f".join(pages), context, catalog, catalogued_only=False)
        )
    elif suffix in {".png", ".jpg", ".jpeg"}:
        observations = []
        status = "deferred"
        image_content = image_text(path, digest)
        if image_content is None:
            notes.append("Image content retained by manifest and digest; OCR is unavailable.")
        else:
            # Raw OCR is an unverified extraction: only catalogued resources become
            # observations, and identifiers must still match exactly downstream.
            observations = document_observations(
                image_content, context, catalog, catalogued_only=True
            )
            for reference, panel in image_panels(path, digest):
                if reference not in catalog:
                    continue
                # A spatially isolated detail panel can link fields on different
                # lines to its exact title; OCR identifiers still need an independent
                # structured identity/resource anchor in the correlator.
                for observation in document_observations(
                    panel, context, {reference: catalog[reference]}, catalogued_only=False
                ):
                    if observation.payload["document_reference"] != reference:
                        continue
                    observations.append(
                        observation.model_copy(
                            update={
                                "payload": {
                                    **observation.payload,
                                    "ocr_identity_unverified": True,
                                    "ocr_method": "tesseract_psm11_spatial_detail_panel",
                                },
                                "provenance": observation.provenance.model_copy(
                                    update={
                                        "locator": observation.provenance.locator + ":ocr-panel"
                                    }
                                ),
                            }
                        )
                    )
            status = "parsed" if observations else "deferred"
            notes.append(
                "Tesseract OCR (default + PSM 11 spatial panels); catalogued resources only; "
                "identifiers require independent linkage."
            )
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
    return EvidenceDocument(
        manifest=manifest, sha256=digest, status=status, observations=observations, notes=notes
    )
