"""Bounded identity -> scoped trace -> explicit resource -> resource observations.

Never expand by file, system alone, name, or a newly encountered person's alias.
"""

from collections import defaultdict

from .identity import IdentityResolver
from .index import EvidenceIndex, identifier_values
from .models import Observation, ResourceRef
from .phase2_models import (
    AssociatedObservation, AssociatedResource, CorrelationLink, ObservationLink,
    ResolvedIdentity,
)
from .time import parse_timestamp

RESOURCE_FIELDS = {'source_resource_id', 'target_resource_id', 'related_resource_id'}
SUBJECT_FIELDS = {'user_id', 'customer_reference', 'subject_reference', 'subject_ref',
                  'subject_key', 'owner_key', 'subject_selector'}
PII_FIELDS = {'email', 'phone', 'email_hash', 'customer_email', 'requester_email',
              'owner_email', 'customer_phone', 'requester_phone', 'owner_phone'}


def reference_key(resource: ResourceRef) -> tuple:
    return (resource.system_id or '', resource.resource_id,
            resource.collection or '', resource.physical_table or '')


class EvidenceCorrelator:
    def __init__(self, index: EvidenceIndex, resolver: IdentityResolver):
        self.index, self.resolver = index, resolver
        self.tokens = [identifier_values(o.payload) | identifier_values(o.raw_text)
                       for o in index.observations]
        self.by_scoped_resource = defaultdict(set)
        for i, item in enumerate(index.observations):
            for r in item.resources:
                self.by_scoped_resource[(r.system_id, r.resource_id)].add(i)

    def correlate(self, identity: ResolvedIdentity, audit_at):
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

        def visible(i):
            time = observations[i].available_at
            return observations[i].kind != 'identity' and time is not None and time <= audit_at

        def owners(value):
            if value not in owner_cache:
                owner_cache[value] = self.resolver.owners(value, audit_at)
            return owner_cache[value]

        def conflict(i):
            # Co-occurrence is not proof that every resource belongs to the subject.
            if any(owners(t) - {user} for t in self.tokens[i]):
                return 'multiple_or_foreign_subjects'
            def foreign_fields(value):
                if isinstance(value, dict):
                    for key, child in value.items():
                        if key in SUBJECT_FIELDS | PII_FIELDS and isinstance(child, str) and child.strip():
                            tokens = identifier_values(child)
                            if not (tokens & alias_map.keys()) and not any(owners(t) == {user} for t in tokens):
                                return True
                        if foreign_fields(child):
                            return True
                elif isinstance(value, list):
                    return any(foreign_fields(child) for child in value)
                return False
            return 'unsupported_subject_reference' if foreign_fields(observations[i].payload) else None

        def add(i, method, parents=(), matched=(), resource=None, forced_reason=None):
            if not visible(i):
                return
            reason = forced_reason or conflict(i)
            status = 'POTENTIAL' if reason else 'CONFIRMED'
            refs = []
            for parent in parents:
                for link in accepted[parent].links:
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
            if reason:
                issues.add(reason)

        candidates = set().union(*(self.index.by_identifier.get(value, set()) for value in alias_map))
        for i in sorted(candidates):
            if visible(i):
                add(i, 'DIRECT_IDENTIFIER', matched=self.tokens[i] & alias_map.keys())

        # Only direct anchors may seed a trace. Detect conflicting subjects over
        # the entire visible scoped trace before accepting any trace-only result.
        anchors = [i for i in sorted(accepted) if accepted[i].association == 'CONFIRMED']
        trace_seeds = defaultdict(list)
        for i in anchors:
            if observations[i].trace_id:
                trace_seeds[self.index.trace_key(observations[i])].append(i)
        for key, parents in trace_seeds.items():
            scoped = sorted(i for i in self.index.by_trace[key] if visible(i))
            contaminated = any(conflict(i) for i in scoped)
            for i in scoped:
                if i not in parents:
                    add(i, 'SCOPED_TRACE', parents=parents,
                        forced_reason='ambiguous_trace_scope' if contaminated else None)

        # One hop through explicit, typed resource reference fields. Never recurse.
        seeds = [i for i in sorted(accepted) if accepted[i].association == 'CONFIRMED']
        for i in seeds:
            item = observations[i]
            for resource in self._explicit_references(item):
                if resource.system_id is None:
                    issues.add('unscoped_explicit_resource_reference')
                    continue
                for j in sorted(self.by_scoped_resource.get((resource.system_id, resource.resource_id), ())):
                    if j != i:
                        add(j, 'EXPLICIT_RESOURCE_REFERENCE', parents=[i], resource=resource)

        # Collect all visible versions/replicas of established resources. New
        # resources/identities encountered here cannot trigger further expansion.
        resource_seeds = defaultdict(list)
        for i in sorted(accepted):
            if accepted[i].association == 'CONFIRMED':
                for r in observations[i].resources:
                    resource_seeds[(r.system_id, r.resource_id)].append(i)
        for (system, resource_id), parents in sorted(resource_seeds.items(), key=lambda p: (p[0][0] or '', p[0][1])):
            for j in sorted(self.index.by_resource[resource_id]):
                if j in parents or not visible(j):
                    continue
                refs = [r for r in observations[j].resources if r.resource_id == resource_id]
                if any(r.system_id == system and system is not None for r in refs):
                    add(j, 'RESOURCE', parents=parents,
                        resource=ResourceRef(resource_id=resource_id, system_id=system))
                elif system is None or any(r.system_id is None for r in refs):
                    add(j, 'RESOURCE', parents=parents, forced_reason='unscoped_resource_match')
        resources = {}
        for i in sorted(accepted):
            if accepted[i].association != 'CONFIRMED':
                continue
            for r in observations[i].resources:
                if r.system_id is None:
                    issues.add('resource_system_unknown')
                key = reference_key(r)
                resources.setdefault(key, (r, []))[1].append(ObservationLink.of(observations[i]))
        return ([accepted[i] for i in sorted(accepted)],
                [AssociatedResource(reference=r, supporting_observations=refs)
                 for _, (r, refs) in sorted(resources.items())], sorted(issues))

    @staticmethod
    def _explicit_references(item: Observation):
        # An explicit target system is preferred for a target reference. Unknown
        # systems are not guessed from a resource prefix or a manifest origin.
        result = []
        def walk(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in RESOURCE_FIELDS and isinstance(child, str) and child:
                        side = 'target_system' if key == 'target_resource_id' else 'source_system'
                        system = value.get(side) or value.get('system_id')
                        if not system and len(item.system_ids) == 1:
                            system = item.system_ids[0]
                        result.append(ResourceRef(resource_id=child, system_id=system))
                    elif isinstance(child, (dict, list)):
                        walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(item.payload)
        return sorted(result, key=reference_key)
