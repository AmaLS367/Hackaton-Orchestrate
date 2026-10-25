"""In-memory inverted indexes; lookups never re-open evidence files."""

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from functools import cached_property

from ghost_audit.domain.models import (
    Activity,
    EvidenceDocument,
    EvidenceEntry,
    IdentityChange,
    Observation,
)
from ghost_audit.domain.snapshot_coverage import Listing as CoverageListing
from ghost_audit.domain.snapshot_coverage import coverage_surfaces
from ghost_audit.domain.snapshot_inventory import Inventory, snapshot_listings
from ghost_audit.domain.time import parse_timestamp

TOKEN = re.compile(r"[\w.+%'-]+@[\w.-]+\.[A-Za-z]{2,}|[\w]+(?:_[\w]+)+|\b[a-fA-F0-9]{64}\b")
PHONE = re.compile(r"(?<!\w)\+\d[\d ()-]{6,}\d(?!\w)")


def normalize_identifier(value: str) -> str:
    """Normalize exact text and phone formatting without fuzzy identity matching."""
    value = value.strip().casefold()
    if value.startswith("+") and re.fullmatch(r"\+[\d ()-]+", value):
        return "+" + re.sub(r"\D", "", value)
    return value


def identifier_values(value: object) -> set[str]:
    """Extract exact normalized atoms while retaining complete scalar strings."""
    if isinstance(value, dict):
        return {token for child in value.values() for token in identifier_values(child)}
    if isinstance(value, list):
        return {token for child in value for token in identifier_values(child)}
    if not isinstance(value, str) or not value.strip():
        return set()
    return {
        normalize_identifier(value),
        *(normalize_identifier(token) for token in TOKEN.findall(value)),
        *(normalize_identifier(token) for token in PHONE.findall(value)),
    }


class EvidenceRegistry:
    """Participant citation IDs and capture metadata, including uninterpreted files."""

    def __init__(
        self,
        *,
        documents: Iterable[EvidenceDocument] = (),
        activities: Iterable[Activity] = (),
        identity_changes: Iterable[IdentityChange] = (),
        observations: Iterable[Observation] = (),
    ) -> None:
        """Register manifest and CSV citations, including deferred files with no observations."""
        self.entries: dict[str, EvidenceEntry] = {}
        for document in documents:
            manifest = document.manifest
            self._register(
                EvidenceEntry(
                    evidence_id=manifest.file_id,
                    file_path=manifest.file_path,
                    origin=manifest.origin,
                    captured_at=manifest.captured_at,
                    parsing_status=document.status,
                )
            )
        for rows, filename, key in (
            (activities, "system_activity.csv", "activity_id"),
            (identity_changes, "user_audit_log.csv", "audit_id"),
        ):
            for row in rows:
                self._register(
                    EvidenceEntry(
                        evidence_id=getattr(row, key),
                        file_path=filename,
                        origin=filename,
                        captured_at=row.event_time,
                        parsing_status="parsed",
                    )
                )
        # Compatibility for existing callers that supply only an observation index.
        # Such callers cannot register files with no observations; ingestion supplies
        # the complete manifest registry explicitly.
        for item in observations:
            source = item.provenance
            if item.kind == "identity" and source.file_path != "user_audit_log.csv":
                continue
            if source.evidence_id not in self.entries:
                self._register(
                    EvidenceEntry(
                        evidence_id=source.evidence_id,
                        file_path=source.file_path,
                        origin=source.origin,
                        captured_at=source.captured_at,
                        parsing_status="parsed",
                    )
                )

    def _register(self, entry: EvidenceEntry) -> None:
        if entry.evidence_id in self.entries:
            raise ValueError(f"duplicate evidence identifier: {entry.evidence_id}")
        self.entries[entry.evidence_id] = entry

    def get(self, evidence_id: str) -> EvidenceEntry | None:
        """Return citation metadata, including deferred files, or None when unregistered."""
        return self.entries.get(evidence_id)


class EvidenceIndex:
    """Index extracted values once; lookups and caches belong to this dataset instance."""

    @staticmethod
    def trace_key(item: Observation) -> tuple[str, object, str | None]:
        # A collector can report several target systems within one service trace.
        """Scope trace reuse by source file and reporting service to prevent cross-user joins."""
        service = item.payload.get("service") or tuple(item.system_ids)
        return item.provenance.file_path, service, item.trace_id

    def __init__(
        self, observations: Iterable[Observation], registry: EvidenceRegistry | None = None
    ) -> None:
        """Build in-memory lookup indexes and reuse the supplied citation registry."""
        self.observations = tuple(observations)
        self.registry = (
            registry if registry is not None else EvidenceRegistry(observations=self.observations)
        )
        self.by_identifier = defaultdict(set)
        self.by_resource = defaultdict(set)
        self.by_system = defaultdict(set)
        self.by_evidence = defaultdict(set)
        self.by_trace = defaultdict(set)
        for index, item in enumerate(self.observations):
            for value in identifier_values(item.payload) | identifier_values(item.raw_text):
                self.by_identifier[value].add(index)
            for resource in item.resources:
                self.by_resource[resource.resource_id].add(index)
            for system in item.system_ids:
                self.by_system[system].add(index)
            self.by_evidence[item.provenance.evidence_id].add(index)
            if item.trace_id:
                # Trace IDs can collide between files or services.
                self.by_trace[self.trace_key(item)].add(index)

    @cached_property
    def submission_listings(self) -> Inventory:
        """Cache immutable inventory interpretation for this index's lifetime."""
        return snapshot_listings(self.observations)

    @cached_property
    def coverage_listings(self) -> dict[tuple[str | None, str | None], list[CoverageListing]]:
        """Keep incomplete surfaces too, so uncertainty diagnostics retain their cause."""
        return coverage_surfaces(self.observations, include_incomplete=True)

    def lookup(
        self,
        *,
        identifiers: Iterable[str] = (),
        resource_id: str | None = None,
        system_id: str | None = None,
        evidence_id: str | None = None,
        audit_at: str | datetime | None = None,
        expand_traces: bool = False,
    ) -> list[Observation]:
        """Union identifiers, intersect other filters; untimeable data is excluded at a cutoff."""
        candidates = None
        identifiers = tuple(identifiers)
        if identifiers:
            candidates = set().union(
                *(self.by_identifier.get(normalize_identifier(v), set()) for v in identifiers)
            )
        for value, mapping in (
            (resource_id, self.by_resource),
            (system_id, self.by_system),
            (evidence_id, self.by_evidence),
        ):
            if value is not None:
                matches = mapping.get(value, set())
                candidates = set(matches) if candidates is None else candidates & matches
        if candidates is None:
            candidates = set(range(len(self.observations)))
        cutoff = parse_timestamp(audit_at) if audit_at is not None else None

        def visible(index: int) -> bool:
            time = self.observations[index].available_at
            return cutoff is None or (time is not None and time <= cutoff)

        candidates = {index for index in candidates if visible(index)}
        if expand_traces:
            for index in sorted(candidates):
                item = self.observations[index]
                if item.trace_id:
                    key = self.trace_key(item)
                    candidates.update(i for i in self.by_trace[key] if visible(i))
        return [self.observations[index] for index in sorted(candidates)]
