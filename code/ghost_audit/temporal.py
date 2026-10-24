"""Deterministic reconstruction over Phase 2 associations, without policy decisions."""

from collections import defaultdict
from itertools import combinations

from .index import EvidenceIndex
from .models import ResourceRef
from .phase2_models import CaseEvidenceBundle, ObservationLink
from .temporal_adapters import REPLICA_SUFFIX, interpret, logical_collection, observation_time
from .temporal_models import (
    CaseStateBundle, ReplicaDrift, ResourceHistory, ResourceScope, StateSelection,
    TemporalObservation, UnresolvedState,
)
from .sql import TABLE_SYSTEMS


def scope_key(scope: ResourceScope) -> tuple[str, ...]:
    return (scope.system_id or '', scope.collection or '', scope.resource_id, scope.replica_scope)


def links_sorted(links) -> list[ObservationLink]:
    return sorted(set(links), key=lambda link: (link.evidence_id, link.file_path, link.locator))


def observation_key(o: TemporalObservation):
    return o.observed_at, o.available_at, o.provenance.evidence_id, o.provenance.locator, o.model_dump_json()


def select_state(observations: list[TemporalObservation], dimension: str) -> StateSelection:
    field = dimension + '_state'
    direct = [o for o in observations if o.association == 'CONFIRMED'
              and o.support in {'PROVEN', 'CONFLICTED'} and getattr(o, field) != 'UNKNOWN']
    # Full contents and precise independent reads outrank summary readback labels.
    precise = [o for o in direct if o.category in {'RESOURCE_READBACK', 'SNAPSHOT'}]
    pool = precise or direct
    if not pool:
        claims = [o for o in observations if o.association == 'CONFIRMED' and o.support == 'CLAIM_ONLY'
                  and getattr(o, field) != 'UNKNOWN']
        return StateSelection(dimension=dimension, state='UNKNOWN',
                              support='CLAIM_ONLY' if claims else 'UNKNOWN', observed_at=None,
                              supporting_evidence=links_sorted(o.link for o in claims), conflicting_evidence=[],
                              reason='claims_cannot_establish_state' if claims else 'no_supported_observation')
    latest_at = max(o.observed_at for o in pool)
    latest = [o for o in pool if o.observed_at == latest_at]
    states = {getattr(o, field) for o in latest}
    conflicted = len(states) > 1 or any(o.support == 'CONFLICTED' and
        (not o.conflict_dimensions or dimension in o.conflict_dimensions) for o in latest)
    selected = 'UNKNOWN' if conflicted else next(iter(states))
    contrary = [o for o in observations if o not in latest and o.observed_at >= latest_at
                and o.association == 'CONFIRMED' and getattr(o, field) not in {'UNKNOWN', selected}
                and o.support in {'CLAIM_ONLY', 'PROVEN', 'CONFLICTED'}]
    conflicts = [*latest, *contrary] if conflicted else contrary
    return StateSelection(
        dimension=dimension, state=selected, support='CONFLICTED' if conflicted else 'PROVEN',
        observed_at=latest_at, supporting_evidence=links_sorted(o.link for o in latest),
        conflicting_evidence=links_sorted(o.link for o in conflicts),
        reason=('incompatible_direct_observations_at_same_time' if conflicted else
                'latest_precise_observation_in_same_scope; contradictory_claims_or_summaries_preserved'
                if contrary else 'latest_supported_observation_in_same_scope'),
    )


def historical_conflicts(observations: list[TemporalObservation]):
    """A later resolution must not discard an earlier contradictory readback pair."""
    links, reasons = [], []
    for o in observations:
        if o.association == 'CONFIRMED' and o.support == 'CONFLICTED':
            links.append(o.link)
            reasons.extend(o.conflicts)
    for dimension in ('record', 'flow', 'restore'):
        groups = defaultdict(list)
        for o in observations:
            if o.association == 'CONFIRMED' and o.support in {'PROVEN', 'CONFLICTED'}:
                if getattr(o, dimension + '_state') != 'UNKNOWN':
                    groups[o.observed_at].append(o)
        for values in groups.values():
            if len({getattr(o, dimension + '_state') for o in values}) > 1:
                links.extend(o.link for o in values)
                reasons.append('simultaneous_' + dimension + '_observations_disagree')
            if dimension == 'record':
                for left, right in combinations(values, 2):
                    a, b = field_signatures(left), field_signatures(right)
                    if any(a[k] != b[k] for k in a.keys() & b.keys()):
                        links.extend([left.link, right.link])
                        reasons.append('simultaneous_field_observations_disagree')
    return links_sorted(links), sorted(set(reasons))


def field_signatures(observation: TemporalObservation):
    return {f.path: (f.representation, f.value if f.representation == 'VALUE' else None)
            for f in observation.fields}


class TemporalStateEngine:
    """Reuse the shared index/registry when available; never reparse or expand ownership.

    Without an index, the Phase 2 bundle is the provenance boundary. Passing the
    existing index additionally verifies citation registration and link availability.
    """

    def __init__(self, index: EvidenceIndex | None = None):
        self.index = index
        self.by_link = ({ObservationLink.of(o): o for o in index.observations}
                        if index is not None else {})
        self.schemas = defaultdict(list)
        if index is not None:
            for o in index.observations:
                if o.provenance.locator.endswith(':schema') and 'table' in o.payload:
                    self.schemas[o.provenance.evidence_id].append(o)

    def _visible(self, observation, cutoff) -> bool:
        available = observation.available_at
        if available is None or available > cutoff:
            return False
        if self.index is not None:
            entry = self.index.registry.get(observation.provenance.evidence_id)
            if entry is None or entry.parsing_status != 'parsed':
                return False
            if entry.captured_at is not None and entry.captured_at > cutoff:
                return False
        return True

    def analyze(self, case_bundle: CaseEvidenceBundle) -> CaseStateBundle:
        bundle = case_bundle
        histories = defaultdict(list)
        unresolved = []
        local = {ObservationLink.of(i.observation): i.observation for i in bundle.observations}
        if bundle.intent.decision != 'DELETE_INTENT':
            unresolved.append(UnresolvedState(reason='deletion_not_authorized_or_intent_uncertain'))
        else:
            for item in sorted(bundle.observations, key=lambda i: i.observation.model_dump_json()):
                o = item.observation
                if item.association == 'UNRELATED':
                    continue
                if not self._visible(o, bundle.audit_at):
                    unresolved.append(UnresolvedState(evidence=ObservationLink.of(o),
                                                       reason='evidence_unavailable_at_audit_cutoff'))
                    continue
                # A later/missing correlation anchor cannot prove earlier ownership.
                chain_ok = bool(item.links) and all(chain.supporting_observations for chain in item.links) and all(
                    (source := local.get(link) or self.by_link.get(link)) is not None
                    and self._visible(source, bundle.audit_at)
                    for chain in item.links for link in chain.supporting_observations)
                safe = (chain_ok and bundle.identity.status == 'RESOLVED')
                if not safe:
                    item = item.model_copy(update={'association': 'POTENTIAL'})
                if not o.resources:
                    unresolved.append(UnresolvedState(evidence=ObservationLink.of(o),
                                                       reason='associated_evidence_without_resource_scope'))
                for ref in sorted(o.resources, key=lambda r: r.model_dump_json()):
                    fact = interpret(item, ref)
                    if fact.observed_at > bundle.audit_at:
                        unresolved.append(UnresolvedState(evidence=fact.link, reason='future_observation'))
                        continue
                    if fact.scope.system_id is None:
                        fact = fact.model_copy(update={'support': 'UNKNOWN',
                                                       'reason': 'resource_system_unknown; ' + fact.reason})
                    # Unknown collections do not establish equivalence between files.
                    # Preserve a source-local history rather than cross-collection joins.
                    if fact.scope.collection is None:
                        fact = fact.model_copy(update={'scope': fact.scope.model_copy(update={
                            'replica_scope': fact.scope.replica_scope + ':unscoped:' +
                                             fact.provenance.file_path + ':' + fact.provenance.locator})})
                    key = scope_key(fact.scope)
                    if fact not in histories[key]:
                        histories[key].append(fact)
            self._snapshot_gaps(histories, bundle.audit_at)

        results = []
        for key in sorted(histories):
            observations = sorted(histories[key], key=observation_key)
            conflicts, reasons = historical_conflicts(observations)
            history = ResourceHistory(scope=observations[0].scope, observations=observations,
                                      record=select_state(observations, 'record'),
                                      flow=select_state(observations, 'flow'),
                                      restore=select_state(observations, 'restore'),
                                      conflicting_evidence=conflicts, conflict_reasons=reasons)
            results.append(history)
            for o in observations:
                if o.support == 'UNKNOWN' or o.conflicts:
                    unresolved.append(UnresolvedState(scope=o.scope, evidence=o.link, reason=o.reason))
            if history.record.state == 'UNKNOWN':
                unresolved.append(UnresolvedState(scope=history.scope, reason=history.record.reason))
        known = {(h.scope.system_id, h.scope.collection, h.scope.resource_id) for h in results}
        if bundle.intent.decision == 'DELETE_INTENT':
            for resource in bundle.resources:
                r = resource.reference
                if (r.system_id, logical_collection(r), r.resource_id) not in known:
                    unresolved.append(UnresolvedState(reason='associated_resource_has_no_visible_state',
                        scope=ResourceScope(resource_id=r.resource_id, system_id=r.system_id,
                                            collection=logical_collection(r), replica_scope='unknown')))
        supporting = links_sorted(link for h in results for o in h.observations
                                  if o.support != 'UNKNOWN'
                                  for link in [o.link, *(ref for chain in o.association_links
                                                        for ref in chain.supporting_observations)])
        conflicting = links_sorted(link for h in results for link in [*h.conflicting_evidence,
            *(ref for selection in (h.record, h.flow, h.restore) for ref in selection.conflicting_evidence)])
        limitations = sorted(set([*bundle.limitations,
            'Last observed states do not prove continuous state between observations or complete discovery.',
            'Null identifiers and category names do not establish redaction, anonymization, or policy compliance.',
            'Replica comparisons with different observation times may reflect temporal skew.',
            'Potential associations, unscoped negatives, deferred files, and missing rows remain unresolved.']))
        if bundle.deferred_evidence:
            unresolved.append(UnresolvedState(reason='unassigned_deferred_evidence_requires_interpretation'))
        if bundle.ambiguities:
            unresolved.append(UnresolvedState(reason='phase2_correlation_or_identity_ambiguities'))
        if bundle.intent.decision == 'DELETE_INTENT' and not results:
            unresolved.append(UnresolvedState(reason='no_resource_observations'))
        return CaseStateBundle(
            case_id=bundle.case_id, audit_at=bundle.audit_at, intent=bundle.intent, identity=bundle.identity,
            resource_histories=results, replica_drift=compare_replicas(results), supporting_evidence=supporting,
            conflicting_evidence=conflicting,
            unresolved_states=sorted(set(unresolved), key=lambda u: u.model_dump_json()), limitations=limitations,
        )

    def _snapshot_gaps(self, histories, cutoff):
        """Expose missing coverage in known sibling SQL tables, never infer absence.

        A schema and grounded sibling row establish the comparison surface only.
        They cannot establish that an incomplete export contains every resource.
        """
        additions = []
        for observations in list(histories.values()):
            for fact in observations:
                if fact.category != 'SNAPSHOT' or fact.support != 'PROVEN' or not fact.physical_table:
                    continue
                family = REPLICA_SUFFIX.sub('', fact.physical_table)
                if family not in TABLE_SYSTEMS or fact.scope.collection != family:
                    continue
                for schema in self.schemas.get(fact.provenance.evidence_id, ()):
                    table = schema.payload['table']
                    if REPLICA_SUFFIX.sub('', table) != family or table == fact.physical_table:
                        continue
                    if not self._visible(schema, cutoff):
                        continue
                    ref = ResourceRef(resource_id=fact.scope.resource_id, system_id=fact.scope.system_id,
                                      collection=family, physical_table=table)
                    match = REPLICA_SUFFIX.search(table)
                    scope = ResourceScope(resource_id=ref.resource_id, system_id=ref.system_id,
                                          collection=family, replica_scope=match[1] if match else 'table:' + table)
                    key = scope_key(scope)
                    if any(o.provenance.evidence_id == fact.provenance.evidence_id
                           for o in histories.get(key, ())):
                        continue
                    gap = TemporalObservation(scope=scope, physical_table=table,
                        observed_at=observation_time(schema), available_at=schema.available_at,
                        provenance=schema.provenance, association='CONFIRMED',
                        association_links=fact.association_links, category='SNAPSHOT_GAP',
                        support='UNKNOWN', reason='no_confirmed_counterpart_row; snapshot_has_no_completeness_guarantee')
                    additions.append((key, gap))
        for key, gap in additions:
            if gap not in histories[key]:
                histories[key].append(gap)


def compare_replicas(histories: list[ResourceHistory]) -> list[ReplicaDrift]:
    groups = defaultdict(list)
    for h in histories:
        if h.scope.system_id and h.scope.collection:
            groups[(h.scope.system_id, h.scope.collection, h.scope.resource_id)].append(h)
    drift = []
    for (system, collection, resource), values in sorted(groups.items()):
        for left, right in combinations(values, 2):
            if left.scope.replica_scope == right.scope.replica_scope:
                continue
            kind = None
            if any(o.category == 'SNAPSHOT_GAP' and
                   (h.record.observed_at is None or o.observed_at >= h.record.observed_at)
                   for h in (left, right) for o in h.observations):
                kind = 'COVERAGE_GAP'
            if left.record.support == right.record.support == 'PROVEN':
                if left.record.state != right.record.state:
                    kind = 'STATE_DISAGREEMENT'
                else:
                    def fields(h):
                        return {path: value for o in h.observations if o.link in h.record.supporting_evidence
                                for path, value in field_signatures(o).items()}
                    a, b = fields(left), fields(right)
                    if any(a[k] != b[k] for k in a.keys() & b.keys()):
                        kind = 'FIELD_DISAGREEMENT'
            # Connector and restore disagreements matter independently of existence.
            if any(getattr(left, d).support == getattr(right, d).support == 'PROVEN'
                   and getattr(left, d).state != getattr(right, d).state for d in ('flow', 'restore')):
                kind = 'STATE_DISAGREEMENT'
            if kind:
                evidence = links_sorted(o.link for h in (left, right) for o in h.observations
                                        if o.support == 'PROVEN' or o.category == 'SNAPSHOT_GAP')
                times = [h.record.observed_at or max(o.observed_at for o in h.observations)
                         for h in (left, right)]
                drift.append(ReplicaDrift(system_id=system, collection=collection, resource_id=resource,
                    scopes=sorted([left.scope.replica_scope, right.scope.replica_scope]), kind=kind,
                    contemporaneous=times[0] == times[1],
                    evidence=evidence, reason='compare_only_established_system_resource_and_logical_collection; '
                                             'missing_coverage_is_not_absence'))
    return sorted(drift, key=lambda d: d.model_dump_json())
