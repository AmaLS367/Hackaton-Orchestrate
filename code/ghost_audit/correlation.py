"""Bounded identity -> scoped trace -> explicit resource -> resource observations.

Never expand by file, system alone, name, or a newly encountered person's alias.
"""

import re
from collections import defaultdict

from .extraction import REPLICA_TABLE
from .identity import IdentityResolver
from .index import EvidenceIndex, identifier_values, normalize_identifier
from .models import Observation, ResourceRef
from .phase2_models import (
    AssociatedObservation, AssociatedResource, CorrelationLink, ObservationLink,
    ResolvedIdentity,
)
from .temporal_adapters import linkage_time
from .time import parse_timestamp

RESOURCE_FIELDS = {'source_resource_id', 'target_resource_id', 'related_resource_id'}
SUBJECT_FIELDS = {'user_id', 'customer_reference', 'subject_reference', 'subject_ref',
                  'subject_key', 'owner_key', 'subject_selector'}
LOOKUP_FIELDS = {'lookup_key', 'match_key'}
PII_FIELDS = {'email', 'phone', 'email_hash', 'customer_email', 'requester_email',
              'owner_email', 'customer_phone', 'requester_phone', 'owner_phone'}
SUBJECT_TOKEN = re.compile(
    r"[\w.+%'-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\w)\+\d[\d ()-]{6,}\d(?!\w)|\buser_[\w]+\b(?!\\?[\"']?\s*[:=])",
    re.IGNORECASE,
)
EMPTY_SELECTORS = {'null', 'none', 'redacted', '[redacted]', 'anonymous', 'anonymized', 'no direct identifier'}


def same_collection(left: str | None, right: str | None) -> bool:
    return not left or not right or REPLICA_TABLE.sub('', left) == REPLICA_TABLE.sub('', right)


def reference_key(resource: ResourceRef) -> tuple:
    return (resource.system_id or '', resource.resource_id,
            resource.collection or '', resource.physical_table or '')


class EvidenceCorrelator:
    def __init__(self, index: EvidenceIndex, resolver: IdentityResolver):
        self.index, self.resolver = index, resolver
        self.tokens = [identifier_values(o.payload) | identifier_values(o.raw_text)
                       for o in index.observations]
        self.subjects = [self._subject_identifiers(o) for o in index.observations]
        # Ownership facts are visible from the time they were observed. A late export
        # can carry an earlier scoped snapshot; its later capture limits citation, not linkage.
        self.times = [linkage_time(o) for o in index.observations]
        self.by_scoped_resource = defaultdict(set)
        for i, item in enumerate(index.observations):
            for r in item.resources:
                self.by_scoped_resource[(r.system_id, r.resource_id)].add(i)

    def correlate(self, identity: ResolvedIdentity, audit_at, *, workflow_seeds=(), prior_audit=None):
        """workflow_seeds: worker events attributed to this request's batch.
        prior_audit: the latest earlier audit of the same subject; evidence observed by
        then was already attributable to that earlier request, not this one."""
        audit_at = parse_timestamp(audit_at)
        if identity.status != 'RESOLVED':
            return [], [], ['identity_not_uniquely_resolved']
        user = identity.user_id
        alias_map = defaultdict(list)
        for alias in identity.aliases:
            if alias.field_name != 'name':
                alias_map[alias.normalized_value].append(alias)
        observations = self.index.observations
        accepted: dict[int, AssociatedObservation] = {}
        issues = set()
        owner_cache = {}
        conflict_cache = {}
        grounded_links = defaultdict(list)

        def ordered(indices):
            return sorted(indices, key=lambda i: (
                observations[i].provenance.file_path, observations[i].provenance.evidence_id,
                observations[i].provenance.locator, observations[i].model_dump_json()))

        def visible(i):
            time = self.times[i]
            return observations[i].kind != 'identity' and time is not None and time <= audit_at

        def owners(value):
            if value not in owner_cache:
                owner_cache[value] = self.resolver.owners(value, audit_at)
            return owner_cache[value]

        def conflict(i):
            if i in conflict_cache:
                return conflict_cache[i]
            # Co-occurrence is not proof that every resource belongs to the subject.
            if any(owners(t) - {user} for t in self.tokens[i]):
                reason = 'multiple_or_foreign_subjects'
            elif any(owners(t) != {user} for t in self.subjects[i]):
                reason = 'unsupported_subject_reference'
            else:
                reason = None
            conflict_cache[i] = reason
            return reason

        def event_time(i):
            # Capture time gates availability; source time orders ownership facts.
            return max((t.value for t in observations[i].provenance.timestamps
                        if t.role == 'source'), default=observations[i].available_at)

        def ownership_safe(parent, candidate, resource):
            low, high = sorted((event_time(parent), event_time(candidate)))
            latest_time, latest_conflicts = None, []
            for k in self.by_scoped_resource.get((resource.system_id, resource.resource_id), ()):
                if not visible(k):
                    continue
                if observations[k].payload.get('ocr_identity_unverified'):
                    # An OCR candidate cannot establish a historical ownership
                    # transition that vetoes an independently linked extraction.
                    continue
                if any(r.collection == resource.collection or not r.collection or not resource.collection
                       for r in observations[k].resources
                       if r.system_id == resource.system_id and r.resource_id == resource.resource_id):
                    at, reason = event_time(k), conflict(k)
                    if low <= at <= high and reason:
                        return False
                    if at <= event_time(candidate) and (
                            reason or self.subjects[k] or self.tokens[k] & alias_map.keys()):
                        if latest_time is None or at > latest_time:
                            latest_time, latest_conflicts = at, [bool(reason)]
                        elif at == latest_time:
                            latest_conflicts.append(bool(reason))
            # Do not backfill an anonymous row between a foreign owner's last
            # claim and the subject's later independently established ownership.
            return not any(latest_conflicts)

        def add(i, method, parents=(), matched=(), resource=None, forced_reason=None):
            if not visible(i):
                return
            reason = forced_reason or conflict(i)
            status = 'POTENTIAL' if reason else 'CONFIRMED'
            refs = []
            for parent in parents:
                for link in grounded_links[parent]:
                    for ref in link.supporting_observations:
                        if ref not in refs:
                            refs.append(ref)
            ref = ObservationLink.of(observations[i])
            if ref not in refs:
                refs.append(ref)
            link = CorrelationLink(
                method=method, supporting_observations=refs,
                matched_identifiers=sorted(matched),
                alias_origins=[a for value in sorted(matched) for a in alias_map[value]],
                resource=resource,
            )
            if i in accepted:
                existing = accepted[i]
                # An independently confirmed link can promote a mere candidate.
                if status == 'CONFIRMED' and existing.association == 'POTENTIAL':
                    existing = existing.model_copy(update={'association': status, 'reason': 'grounded_link'})
                if link not in existing.links:
                    accepted[i] = existing.model_copy(update={'links': [*existing.links, link]})
                else:
                    accepted[i] = existing
            else:
                accepted[i] = AssociatedObservation(observation=observations[i], association=status,
                                                     links=[link], reason=reason or 'grounded_link')
            if status == 'CONFIRMED' and link not in grounded_links[i]:
                grounded_links[i].append(link)
            if reason:
                issues.add(reason)

        candidates = set().union(*(self.index.by_identifier.get(value, set()) for value in alias_map))
        for i in ordered(candidates):
            if visible(i):
                earlier = prior_audit is not None and event_time(i) <= prior_audit
                add(i, 'DIRECT_IDENTIFIER', matched=self.tokens[i] & alias_map.keys(),
                    forced_reason=('attributed_to_earlier_request_of_subject' if earlier else
                                   'ocr_identity_requires_independent_link' if
                                   observations[i].payload.get('ocr_identity_unverified') else None))
        for i in ordered(workflow_seeds):
            if visible(i):
                # Timing/result consistency produces search candidates, not ownership.
                # Independent identity anchors may promote the same resource later.
                add(i, 'WORKFLOW_BATCH', forced_reason='workflow_batch_ownership_unproven')

        # Only direct anchors may seed a trace. Detect conflicting subjects over
        # the entire visible scoped trace before accepting any trace-only result.
        anchors = [i for i in ordered(accepted) if accepted[i].association == 'CONFIRMED']
        trace_seeds = defaultdict(list)
        for i in anchors:
            if observations[i].trace_id:
                trace_seeds[self.index.trace_key(observations[i])].append(i)
        for key, parents in trace_seeds.items():
            scoped = ordered(i for i in self.index.by_trace[key] if visible(i))
            contaminated = any(conflict(i) for i in scoped)
            for i in scoped:
                if i not in parents:
                    add(i, 'SCOPED_TRACE', parents=parents,
                        forced_reason='ambiguous_trace_scope' if contaminated else None)

        # One hop through explicit, typed resource reference fields. Never recurse.
        seeds = [i for i in ordered(accepted) if accepted[i].association == 'CONFIRMED']
        for i in seeds:
            item = observations[i]
            for resource in self._explicit_references(item):
                if resource.system_id is None:
                    issues.add('unscoped_explicit_resource_reference')
                candidates = [j for j in self.index.by_resource.get(resource.resource_id, ())
                              if j != i and visible(j) and any(
                                  r.resource_id == resource.resource_id
                                  and (resource.system_id is None or r.system_id == resource.system_id)
                                  for r in observations[j].resources)]
                scopes = {r.collection for j in candidates for r in observations[j].resources
                          if r.resource_id == resource.resource_id and r.system_id == resource.system_id}
                scopes.update(r.collection for r in item.resources
                              if r.resource_id == resource.resource_id and r.system_id == resource.system_id)
                for j in ordered(candidates):
                    reason = None
                    refs = [r for r in observations[j].resources if r.resource_id == resource.resource_id
                            and (resource.system_id is None or r.system_id == resource.system_id)]
                    if resource.system_id is None:
                        reason = 'unscoped_explicit_resource_reference'
                    elif resource.collection:
                        if not any(r.collection == resource.collection for r in refs):
                            reason = 'incompatible_resource_collection'
                    elif len(scopes) > 1:
                        reason = 'ambiguous_explicit_resource_collection'
                    if not reason and not ownership_safe(i, j, resource):
                        reason = 'resource_ownership_boundary'
                    add(j, 'EXPLICIT_RESOURCE_REFERENCE', parents=[i], resource=resource,
                        forced_reason=reason)

        # Collect all visible versions/replicas of established resources. New
        # resources/identities encountered here cannot trigger further expansion.
        resource_seeds = defaultdict(list)
        for i in ordered(accepted):
            if accepted[i].association == 'CONFIRMED':
                for r in observations[i].resources:
                    resource_seeds[(r.system_id, r.resource_id, r.collection)].append(i)
        for (system, resource_id, collection), parents in sorted(
                resource_seeds.items(), key=lambda p: tuple(v or '' for v in p[0])):
            resource = ResourceRef(resource_id=resource_id, system_id=system, collection=collection)
            for j in ordered(self.index.by_resource[resource_id]):
                if j in parents or not visible(j):
                    continue
                refs = [r for r in observations[j].resources if r.resource_id == resource_id]
                if any(r.system_id == system and system is not None for r in refs):
                    # One system's resource ID names one record. Only an explicitly
                    # different logical collection makes the rows incompatible.
                    compatible = any(r.system_id == system and same_collection(r.collection, collection)
                                     for r in refs)
                    safe_parents = [p for p in parents if ownership_safe(p, j, resource)] if compatible else []
                    reason = ('incompatible_resource_collection' if not compatible
                              else 'resource_ownership_boundary' if not safe_parents else None)
                    add(j, 'RESOURCE', parents=safe_parents or parents,
                        resource=resource, forced_reason=reason)
                elif system is None or any(r.system_id is None for r in refs):
                    add(j, 'RESOURCE', parents=parents, forced_reason='unscoped_resource_match')
        resources = {}
        for i in ordered(accepted):
            if accepted[i].association != 'CONFIRMED':
                continue
            for r in observations[i].resources:
                if r.system_id is None:
                    issues.add('resource_system_unknown')
                key = reference_key(r)
                refs = resources.setdefault(key, (r, []))[1]
                ref = ObservationLink.of(observations[i])
                if ref not in refs:
                    refs.append(ref)
        return ([accepted[i] for i in ordered(accepted)],
                [AssociatedResource(reference=r, supporting_observations=refs)
                 for _, (r, refs) in sorted(resources.items())], sorted(issues))

    def _subject_identifiers(self, item):
        """Extract each subject separately, including unknown subjects in prose.

        Lookup selectors can also be resource IDs or null markers; those alone
        do not assert ownership. Known aliases are checked separately in conflict.
        """
        result = set()
        metadata = {normalize_identifier(value) for key, value in item.payload.items()
                    if key in {'record_type', 'data_category', 'collection', 'collection_name'}
                    and isinstance(value, str)}
        metadata.update(normalize_identifier(r.resource_id) for r in item.resources)

        def walk(value):
            if isinstance(value, str):
                result.update(normalize_identifier(t) for t in SUBJECT_TOKEN.findall(value)
                              if normalize_identifier(t) not in metadata)
            elif isinstance(value, dict):
                for key, child in value.items():
                    walk(child)
                    field = key.casefold()
                    if field in SUBJECT_FIELDS | PII_FIELDS | LOOKUP_FIELDS and isinstance(child, str):
                        normalized = normalize_identifier(child)
                        if not normalized or normalized in EMPTY_SELECTORS:
                            continue
                        atoms = {normalize_identifier(t) for t in SUBJECT_TOKEN.findall(child)}
                        if field in LOOKUP_FIELDS and any(
                                normalize_identifier(r.resource_id) == normalized for r in item.resources):
                            continue
                        result.update(atoms or {normalized})
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(item.payload)
        walk(item.raw_text)
        return result

    @staticmethod
    def _explicit_references(item: Observation):
        # An explicit target system is preferred for a target reference. Unknown
        # systems are not guessed from a resource prefix or a manifest origin.
        result = []
        def walk(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in RESOURCE_FIELDS and isinstance(child, str) and child:
                        prefix = key.removesuffix('_resource_id')
                        system = value.get(prefix + '_system')
                        if prefix == 'related' and not system:
                            # Direction is relative to the reporting relationship:
                            # upstream -> source; downstream -> target. No guess
                            # is made for absent or unrecognized direction values.
                            direction = value.get('relationship_direction') or value.get('direction')
                            side = {'upstream': 'source_system', 'downstream': 'target_system'}.get(direction)
                            system = value.get(side) if side else None
                        if prefix != 'related':
                            system = system or value.get('system_id')
                        if prefix != 'related' and not system and len(item.system_ids) == 1:
                            system = item.system_ids[0]
                        collection = value.get(prefix + '_collection') or value.get(prefix + '_collection_name')
                        result.append(ResourceRef(resource_id=child, system_id=system, collection=collection))
                    elif isinstance(child, (dict, list)):
                        walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(item.payload)
        return sorted(result, key=reference_key)
