"""Bounded identity -> scoped trace -> explicit resource -> resource observations.

Never expand by file, system alone, name, or a newly encountered person's alias.
"""

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from pydantic import JsonValue

from ghost_audit.domain.association_models import (
    AssociatedObservation,
    AssociatedResource,
    CorrelationLink,
    CorrelationMethod,
    IdentityAlias,
    ObservationLink,
    ResolvedIdentity,
)
from ghost_audit.domain.catalog import REPLICA_TABLE
from ghost_audit.domain.evidence_index import EvidenceIndex, identifier_values, normalize_identifier
from ghost_audit.domain.identity import IdentityResolver
from ghost_audit.domain.models import Observation, ResourceRef
from ghost_audit.domain.observation_clocks import known_at
from ghost_audit.domain.time import parse_timestamp

RESOURCE_FIELDS = {"source_resource_id", "target_resource_id", "related_resource_id"}
SUBJECT_FIELDS = {
    "user_id",
    "customer_reference",
    "subject_reference",
    "subject_ref",
    "subject_key",
    "owner_key",
    "subject_selector",
}
LOOKUP_FIELDS = {"lookup_key", "match_key"}
PII_FIELDS = {
    "email",
    "phone",
    "email_hash",
    "customer_email",
    "requester_email",
    "owner_email",
    "customer_phone",
    "requester_phone",
    "owner_phone",
}
SUBJECT_TOKEN = re.compile(
    r"[\w.+%'-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\w)\+\d[\d ()-]{6,}\d(?!\w)|\buser_[\w]+\b(?!\\?[\"']?\s*[:=])",
    re.IGNORECASE,
)
EMPTY_SELECTORS = {
    "null",
    "none",
    "redacted",
    "[redacted]",
    "anonymous",
    "anonymized",
    "no direct identifier",
}


def same_collection(left: str | None, right: str | None) -> bool:
    """Allow unknown collection scope while rejecting explicitly incompatible families."""
    return not left or not right or REPLICA_TABLE.sub("", left) == REPLICA_TABLE.sub("", right)


def reference_key(resource: ResourceRef) -> tuple[str, str, str, str]:
    """Sort resource scope deterministically without collapsing physical copies."""
    return (
        resource.system_id or "",
        resource.resource_id,
        resource.collection or "",
        resource.physical_table or "",
    )


class EvidenceCorrelator:
    """Bound subject discovery without expanding through newly encountered identities."""

    def __init__(self, index: EvidenceIndex, resolver: IdentityResolver) -> None:
        self.index, self.resolver = index, resolver
        self.tokens = [
            identifier_values(o.payload) | identifier_values(o.raw_text) for o in index.observations
        ]
        self.subjects = [self._subject_identifiers(o) for o in index.observations]
        # Ownership facts count only once known: a late export carrying an earlier scoped
        # snapshot cannot establish that earlier ownership at an audit before its capture.
        self.times = [known_at(o) for o in index.observations]
        self.by_scoped_resource: defaultdict[tuple[str | None, str], set[int]] = defaultdict(set)
        for i, item in enumerate(index.observations):
            for r in item.resources:
                self.by_scoped_resource[(r.system_id, r.resource_id)].add(i)

    def correlate(
        self,
        identity: ResolvedIdentity,
        audit_at: str | datetime,
        *,
        workflow_seeds: Iterable[int] = (),
        prior_audit: datetime | None = None,
    ) -> tuple[list[AssociatedObservation], list[AssociatedResource], list[str]]:
        """Bound association expansion to one subject and an immutable audit cutoff."""
        cutoff = parse_timestamp(audit_at)
        if identity.status != "RESOLVED":
            return [], [], ["identity_not_uniquely_resolved"]
        return _CaseCorrelation(self, identity, cutoff, prior_audit).run(workflow_seeds)

    def _subject_identifiers(self, item: Observation) -> set[str]:
        """Extract each subject separately, including unknown subjects in prose.

        Lookup selectors can also be resource IDs or null markers; those alone
        do not assert ownership. Known aliases are checked separately in conflict.
        """
        result: set[str] = set()
        metadata = {
            normalize_identifier(value)
            for key, value in item.payload.items()
            if key in {"record_type", "data_category", "collection", "collection_name"}
            and isinstance(value, str)
        }
        metadata.update(normalize_identifier(r.resource_id) for r in item.resources)

        def walk(value: JsonValue) -> None:
            if isinstance(value, str):
                result.update(
                    normalize_identifier(t)
                    for t in SUBJECT_TOKEN.findall(value)
                    if normalize_identifier(t) not in metadata
                )
            elif isinstance(value, dict):
                for key, child in value.items():
                    walk(child)
                    field = key.casefold()
                    if field in SUBJECT_FIELDS | PII_FIELDS | LOOKUP_FIELDS and isinstance(
                        child, str
                    ):
                        normalized = normalize_identifier(child)
                        if not normalized or normalized in EMPTY_SELECTORS:
                            continue
                        atoms = {normalize_identifier(t) for t in SUBJECT_TOKEN.findall(child)}
                        if field in LOOKUP_FIELDS and any(
                            normalize_identifier(r.resource_id) == normalized
                            for r in item.resources
                        ):
                            continue
                        result.update(atoms or {normalized})
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(item.payload)
        walk(item.raw_text)
        return result

    @staticmethod
    def _explicit_references(item: Observation) -> list[ResourceRef]:
        # An explicit target system is preferred for a target reference. Unknown
        # systems are not guessed from a resource prefix or a manifest origin.
        result = []

        def walk(value: JsonValue) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in RESOURCE_FIELDS and isinstance(child, str) and child:
                        prefix = key.removesuffix("_resource_id")
                        system = value.get(prefix + "_system")
                        if prefix == "related" and not system:
                            # Direction is relative to the reporting relationship:
                            # upstream -> source; downstream -> target. No guess
                            # is made for absent or unrecognized direction values.
                            direction = value.get("relationship_direction") or value.get(
                                "direction"
                            )
                            side = (
                                {"upstream": "source_system", "downstream": "target_system"}.get(
                                    direction
                                )
                                if isinstance(direction, str)
                                else None
                            )
                            system = value.get(side) if side else None
                        if prefix != "related":
                            system = system or value.get("system_id")
                        if prefix != "related" and not system and len(item.system_ids) == 1:
                            system = item.system_ids[0]
                        collection = value.get(prefix + "_collection") or value.get(
                            prefix + "_collection_name"
                        )
                        result.append(
                            ResourceRef.model_validate(
                                {
                                    "resource_id": child,
                                    "system_id": system,
                                    "collection": collection,
                                }
                            )
                        )
                    elif isinstance(child, (dict, list)):
                        walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(item.payload)
        return sorted(result, key=reference_key)


class _CaseCorrelation:
    """Per-case ownership safeguards and bounded, ordered expansion stages.

    State belongs to one correlation call. A newly found identity never seeds a new
    search, and a foreign ownership interval prevents terminal resource expansion.
    """

    def __init__(
        self,
        correlator: EvidenceCorrelator,
        identity: ResolvedIdentity,
        cutoff: datetime,
        prior_audit: datetime | None,
    ) -> None:
        self.correlator = correlator
        self.audit_at = cutoff
        self.prior_audit = prior_audit
        self.user = identity.user_id
        self.alias_map: defaultdict[str, list[IdentityAlias]] = defaultdict(list)
        for alias in identity.aliases:
            if alias.field_name != "name":
                self.alias_map[alias.normalized_value].append(alias)
        self.observations = self.correlator.index.observations
        self.accepted: dict[int, AssociatedObservation] = {}
        self.issues: set[str] = set()
        self.owner_cache: dict[str, set[str]] = {}
        self.conflict_cache: dict[int, str | None] = {}
        self.grounded_links: defaultdict[int, list[CorrelationLink]] = defaultdict(list)

    def ordered(self, indices: Iterable[int]) -> list[int]:
        return sorted(
            indices,
            key=lambda i: (
                self.observations[i].provenance.file_path,
                self.observations[i].provenance.evidence_id,
                self.observations[i].provenance.locator,
                self.observations[i].model_dump_json(),
            ),
        )

    def visible(self, i: int) -> bool:
        time = self.correlator.times[i]
        return (
            self.observations[i].kind != "identity" and time is not None and time <= self.audit_at
        )

    def owners(self, value: str) -> set[str]:
        if value not in self.owner_cache:
            self.owner_cache[value] = self.correlator.resolver.owners(value, self.audit_at)
        return self.owner_cache[value]

    def conflict(self, i: int) -> str | None:
        if i in self.conflict_cache:
            return self.conflict_cache[i]
        # Co-occurrence is not proof that every resource belongs to the subject.
        if any(self.owners(t) - {self.user} for t in self.correlator.tokens[i]):
            reason = "multiple_or_foreign_subjects"
        elif any(self.owners(t) != {self.user} for t in self.correlator.subjects[i]):
            reason = "unsupported_subject_reference"
        else:
            reason = None
        self.conflict_cache[i] = reason
        return reason

    def event_time(self, i: int) -> datetime:
        at = max(
            (t.value for t in self.observations[i].provenance.timestamps if t.role == "source"),
            default=self.observations[i].available_at,
        )
        assert at is not None, "Only visible observations participate in ownership intervals"
        return at

    def ownership_safe(self, parent: int, candidate: int, resource: ResourceRef) -> bool:
        low, high = sorted((self.event_time(parent), self.event_time(candidate)))
        latest_time, latest_conflicts = None, []
        for k in self.correlator.by_scoped_resource.get(
            (resource.system_id, resource.resource_id), ()
        ):
            if not self.visible(k):
                continue
            if self.observations[k].payload.get("ocr_identity_unverified"):
                # An OCR candidate cannot establish a historical ownership
                # transition that vetoes an independently linked extraction.
                continue
            if any(
                r.collection == resource.collection or not r.collection or not resource.collection
                for r in self.observations[k].resources
                if r.system_id == resource.system_id and r.resource_id == resource.resource_id
            ):
                at, reason = self.event_time(k), self.conflict(k)
                if low <= at <= high and reason:
                    return False
                if at <= self.event_time(candidate) and (
                    reason
                    or self.correlator.subjects[k]
                    or self.correlator.tokens[k] & self.alias_map.keys()
                ):
                    if latest_time is None or at > latest_time:
                        latest_time, latest_conflicts = at, [bool(reason)]
                    elif at == latest_time:
                        latest_conflicts.append(bool(reason))
        # Do not backfill an anonymous row between a foreign owner's last
        # claim and the subject's later independently established ownership.
        return not any(latest_conflicts)

    def add(
        self,
        i: int,
        method: CorrelationMethod,
        parents: Iterable[int] = (),
        matched: Iterable[str] = (),
        resource: ResourceRef | None = None,
        forced_reason: str | None = None,
    ) -> None:
        if not self.visible(i):
            return
        reason = forced_reason or self.conflict(i)
        status: Literal["POTENTIAL", "CONFIRMED"] = "POTENTIAL" if reason else "CONFIRMED"
        refs = []
        for parent in parents:
            for link in self.grounded_links[parent]:
                for ref in link.supporting_observations:
                    if ref not in refs:
                        refs.append(ref)
        ref = ObservationLink.of(self.observations[i])
        if ref not in refs:
            refs.append(ref)
        link = CorrelationLink(
            method=method,
            supporting_observations=refs,
            matched_identifiers=sorted(matched),
            alias_origins=[a for value in sorted(matched) for a in self.alias_map[value]],
            resource=resource,
        )
        if i in self.accepted:
            existing = self.accepted[i]
            # An independently confirmed link can promote a mere candidate.
            if status == "CONFIRMED" and existing.association == "POTENTIAL":
                existing = existing.model_copy(
                    update={"association": status, "reason": "grounded_link"}
                )
            if link not in existing.links:
                self.accepted[i] = existing.model_copy(update={"links": [*existing.links, link]})
            else:
                self.accepted[i] = existing
        else:
            self.accepted[i] = AssociatedObservation(
                observation=self.observations[i],
                association=status,
                links=[link],
                reason=reason or "grounded_link",
            )
        if status == "CONFIRMED" and link not in self.grounded_links[i]:
            self.grounded_links[i].append(link)
        if reason:
            self.issues.add(reason)

    def run(
        self, workflow_seeds: Iterable[int]
    ) -> tuple[list[AssociatedObservation], list[AssociatedResource], list[str]]:
        self.seed_identifiers(workflow_seeds)
        self.expand_scoped_traces()
        self.follow_resource_references()
        self.collect_resource_versions()
        return self.bundle()

    def seed_identifiers(self, workflow_seeds: Iterable[int]) -> None:
        candidates = set().union(
            *(self.correlator.index.by_identifier.get(value, set()) for value in self.alias_map)
        )
        for i in self.ordered(candidates):
            if self.visible(i):
                earlier = self.prior_audit is not None and self.event_time(i) <= self.prior_audit
                self.add(
                    i,
                    "DIRECT_IDENTIFIER",
                    matched=self.correlator.tokens[i] & self.alias_map.keys(),
                    forced_reason=(
                        "attributed_to_earlier_request_of_subject"
                        if earlier
                        else "ocr_identity_requires_independent_link"
                        if self.observations[i].payload.get("ocr_identity_unverified")
                        else None
                    ),
                )
        for i in self.ordered(workflow_seeds):
            if self.visible(i):
                # Timing/result consistency produces search candidates, not ownership.
                # Independent identity anchors may promote the same resource later.
                self.add(i, "WORKFLOW_BATCH", forced_reason="workflow_batch_ownership_unproven")

        # Only direct anchors may seed a trace. Detect conflicting subjects over
        # the entire visible scoped trace before accepting any trace-only result.

    def expand_scoped_traces(self) -> None:
        anchors = [
            i for i in self.ordered(self.accepted) if self.accepted[i].association == "CONFIRMED"
        ]
        trace_seeds = defaultdict(list)
        for i in anchors:
            if self.observations[i].trace_id:
                trace_seeds[self.correlator.index.trace_key(self.observations[i])].append(i)
        for key, parents in trace_seeds.items():
            scoped = self.ordered(i for i in self.correlator.index.by_trace[key] if self.visible(i))
            contaminated = any(self.conflict(i) for i in scoped)
            for i in scoped:
                if i not in parents:
                    self.add(
                        i,
                        "SCOPED_TRACE",
                        parents=parents,
                        forced_reason="ambiguous_trace_scope" if contaminated else None,
                    )

        # One hop through explicit, typed resource reference fields. Never recurse.

    def follow_resource_references(self) -> None:
        seeds = [
            i for i in self.ordered(self.accepted) if self.accepted[i].association == "CONFIRMED"
        ]
        for i in seeds:
            item = self.observations[i]
            for resource in self.correlator._explicit_references(item):
                if resource.system_id is None:
                    self.issues.add("unscoped_explicit_resource_reference")
                candidates = [
                    j
                    for j in self.correlator.index.by_resource.get(resource.resource_id, ())
                    if j != i
                    and self.visible(j)
                    and any(
                        r.resource_id == resource.resource_id
                        and (resource.system_id is None or r.system_id == resource.system_id)
                        for r in self.observations[j].resources
                    )
                ]
                scopes = {
                    r.collection
                    for j in candidates
                    for r in self.observations[j].resources
                    if r.resource_id == resource.resource_id and r.system_id == resource.system_id
                }
                scopes.update(
                    r.collection
                    for r in item.resources
                    if r.resource_id == resource.resource_id and r.system_id == resource.system_id
                )
                for j in self.ordered(candidates):
                    reason = None
                    refs = [
                        r
                        for r in self.observations[j].resources
                        if r.resource_id == resource.resource_id
                        and (resource.system_id is None or r.system_id == resource.system_id)
                    ]
                    if resource.system_id is None:
                        reason = "unscoped_explicit_resource_reference"
                    elif resource.collection:
                        if not any(r.collection == resource.collection for r in refs):
                            reason = "incompatible_resource_collection"
                    elif len(scopes) > 1:
                        reason = "ambiguous_explicit_resource_collection"
                    if not reason and not self.ownership_safe(i, j, resource):
                        reason = "resource_ownership_boundary"
                    self.add(
                        j,
                        "EXPLICIT_RESOURCE_REFERENCE",
                        parents=[i],
                        resource=resource,
                        forced_reason=reason,
                    )

        # Collect all visible versions/replicas of established resources. New
        # resources/identities encountered here cannot trigger further expansion.

    def collect_resource_versions(self) -> None:
        resource_seeds = defaultdict(list)
        for i in self.ordered(self.accepted):
            if self.accepted[i].association == "CONFIRMED":
                for r in self.observations[i].resources:
                    resource_seeds[(r.system_id, r.resource_id, r.collection)].append(i)
        for (system, resource_id, collection), parents in sorted(
            resource_seeds.items(), key=lambda p: tuple(v or "" for v in p[0])
        ):
            resource = ResourceRef(resource_id=resource_id, system_id=system, collection=collection)
            for j in self.ordered(self.correlator.index.by_resource[resource_id]):
                if j in parents or not self.visible(j):
                    continue
                refs = [r for r in self.observations[j].resources if r.resource_id == resource_id]
                if any(r.system_id == system and system is not None for r in refs):
                    # One system's resource ID names one record. Only an explicitly
                    # different logical collection makes the rows incompatible.
                    compatible = any(
                        r.system_id == system and same_collection(r.collection, collection)
                        for r in refs
                    )
                    safe_parents = (
                        [p for p in parents if self.ownership_safe(p, j, resource)]
                        if compatible
                        else []
                    )
                    reason = (
                        "incompatible_resource_collection"
                        if not compatible
                        else "resource_ownership_boundary"
                        if not safe_parents
                        else None
                    )
                    self.add(
                        j,
                        "RESOURCE",
                        parents=safe_parents or parents,
                        resource=resource,
                        forced_reason=reason,
                    )
                elif system is None or any(r.system_id is None for r in refs):
                    self.add(
                        j, "RESOURCE", parents=parents, forced_reason="unscoped_resource_match"
                    )

    def bundle(self) -> tuple[list[AssociatedObservation], list[AssociatedResource], list[str]]:
        resources: dict[tuple[str, str, str, str], tuple[ResourceRef, list[ObservationLink]]] = {}
        for i in self.ordered(self.accepted):
            if self.accepted[i].association != "CONFIRMED":
                continue
            for r in self.observations[i].resources:
                if r.system_id is None:
                    self.issues.add("resource_system_unknown")
                key = reference_key(r)
                refs = resources.setdefault(key, (r, []))[1]
                ref = ObservationLink.of(self.observations[i])
                if ref not in refs:
                    refs.append(ref)
        return (
            [self.accepted[i] for i in self.ordered(self.accepted)],
            [
                AssociatedResource(reference=r, supporting_observations=refs)
                for _, (r, refs) in sorted(resources.items())
            ],
            sorted(self.issues),
        )
