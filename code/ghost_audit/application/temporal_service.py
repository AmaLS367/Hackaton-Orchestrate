"""Coordinate interpretation and temporal reconstruction for one attributed case."""

from collections import defaultdict
from datetime import datetime

from ghost_audit.application.observation_interpretation import interpret
from ghost_audit.domain.association_models import (
    AssociatedObservation,
    CaseEvidenceBundle,
    CorrelationLink,
    ObservationLink,
)
from ghost_audit.domain.catalog import REPLICA_SUFFIX, TABLE_SYSTEMS
from ghost_audit.domain.evidence_index import EvidenceIndex
from ghost_audit.domain.models import Observation, ResourceRef
from ghost_audit.domain.observation_clocks import known_at, logical_collection, observation_time
from ghost_audit.domain.snapshot_coverage import Listing, coverage_surfaces, known_collections
from ghost_audit.domain.state_selection import (
    compare_replicas,
    historical_conflicts,
    links_sorted,
    observation_key,
    scope_key,
    select_state,
)
from ghost_audit.domain.temporal_models import (
    CaseStateBundle,
    ResourceHistory,
    ResourceScope,
    TemporalObservation,
    UnresolvedState,
)


class TemporalStateEngine:
    """Reuse the shared index/registry when available; never reparse or expand ownership.

    Without an index, the Phase 2 bundle is the provenance boundary. Passing the
    existing index additionally verifies citation registration and link availability.
    """

    def __init__(self, index: EvidenceIndex | None = None) -> None:
        self.index = index
        self.by_link = (
            {ObservationLink.of(o): o for o in index.observations} if index is not None else {}
        )
        self.schemas = defaultdict(list)
        if index is not None:
            for o in index.observations:
                if o.provenance.locator.endswith(":schema") and "table" in o.payload:
                    self.schemas[o.provenance.evidence_id].append(o)
        self.surfaces = coverage_surfaces(index.observations) if index is not None else {}

    def _linkable(self, observation: Observation, cutoff: datetime) -> bool:
        """An ownership fact counts only once known by the cutoff, like a citation."""
        at = known_at(observation)
        if at is None or at > cutoff:
            return False
        if self.index is not None:
            entry = self.index.registry.get(observation.provenance.evidence_id)
            if entry is None or entry.parsing_status != "parsed":
                return False
        return True

    def _visible(self, observation: Observation, cutoff: datetime) -> bool:
        available = observation.available_at
        if available is None or available > cutoff:
            return False
        if self.index is not None:
            entry = self.index.registry.get(observation.provenance.evidence_id)
            if entry is None or entry.parsing_status != "parsed":
                return False
            if entry.captured_at is not None and entry.captured_at > cutoff:
                return False
        return True

    def analyze(self, case_bundle: CaseEvidenceBundle) -> CaseStateBundle:
        """Reconstruct each physical scope before assembling case-level diagnostics."""
        unresolved: list[UnresolvedState] = []
        histories = self._collect_observations(case_bundle, unresolved)
        results = self._build_histories(histories, unresolved)
        return self._assemble_bundle(case_bundle, results, unresolved)

    def _collect_observations(
        self, bundle: CaseEvidenceBundle, unresolved: list[UnresolvedState]
    ) -> defaultdict[tuple[str, ...], list[TemporalObservation]]:
        histories: defaultdict[tuple[str, ...], list[TemporalObservation]] = defaultdict(list)
        local = {ObservationLink.of(i.observation): i.observation for i in bundle.observations}
        if bundle.intent.decision != "DELETE_INTENT":
            unresolved.append(UnresolvedState(reason="deletion_not_authorized_or_intent_uncertain"))
        else:
            known = known_collections(bundle)
            for item in sorted(bundle.observations, key=lambda i: i.observation.model_dump_json()):
                o = item.observation
                if item.association == "UNRELATED":
                    continue
                if not (self._visible(o, bundle.audit_at) and self._linkable(o, bundle.audit_at)):
                    # Later evidence must not change the answer: it neither links nor
                    # supplies state, however early its own source clock reads.
                    unresolved.append(
                        UnresolvedState(
                            evidence=ObservationLink.of(o),
                            reason="evidence_unavailable_at_audit_cutoff",
                        )
                    )
                    continue
                # A later/missing correlation anchor cannot prove earlier ownership.
                chain_ok = (
                    bool(item.links)
                    and all(chain.supporting_observations for chain in item.links)
                    and all(
                        (source := local.get(link) or self.by_link.get(link)) is not None
                        and self._linkable(source, bundle.audit_at)
                        for chain in item.links
                        for link in chain.supporting_observations
                    )
                )
                safe = chain_ok and bundle.identity.status == "RESOLVED"
                if not safe:
                    item = item.model_copy(update={"association": "POTENTIAL"})
                if not o.resources:
                    unresolved.append(
                        UnresolvedState(
                            evidence=ObservationLink.of(o),
                            reason="associated_evidence_without_resource_scope",
                        )
                    )
                for ref in sorted(o.resources, key=lambda r: r.model_dump_json()):
                    fact = interpret(item, ref)
                    if fact.observed_at > bundle.audit_at:
                        unresolved.append(
                            UnresolvedState(evidence=fact.link, reason="future_observation")
                        )
                        continue
                    if fact.scope.system_id is None:
                        fact = fact.model_copy(
                            update={
                                "support": "UNKNOWN",
                                "reason": "resource_system_unknown; " + fact.reason,
                            }
                        )
                    # A row without its own collection joins the resource's single known
                    # logical collection; otherwise it stays in its own source scope.
                    if fact.scope.collection is None:
                        collection = known.get((fact.scope.system_id, fact.scope.resource_id))
                        if collection:
                            fact = fact.model_copy(
                                update={
                                    "scope": fact.scope.model_copy(
                                        update={"collection": collection}
                                    )
                                }
                            )
                    key = scope_key(fact.scope)
                    if fact not in histories[key]:
                        histories[key].append(fact)
            self._snapshot_gaps(histories, bundle.audit_at)
            self._coverage_absence(histories, bundle.audit_at)

        return histories

    def _build_histories(
        self,
        histories: dict[tuple[str, ...], list[TemporalObservation]],
        unresolved: list[UnresolvedState],
    ) -> list[ResourceHistory]:
        results = []
        for key in sorted(histories):
            observations = sorted(histories[key], key=observation_key)
            conflicts, reasons = historical_conflicts(observations)
            history = ResourceHistory(
                scope=observations[0].scope,
                observations=observations,
                record=select_state(observations, "record"),
                flow=select_state(observations, "flow"),
                restore=select_state(observations, "restore"),
                conflicting_evidence=conflicts,
                conflict_reasons=reasons,
            )
            results.append(history)
            for o in observations:
                if o.support == "UNKNOWN" or o.conflicts:
                    unresolved.append(
                        UnresolvedState(scope=o.scope, evidence=o.link, reason=o.reason)
                    )
            if history.record.state == "UNKNOWN":
                unresolved.append(
                    UnresolvedState(scope=history.scope, reason=history.record.reason)
                )
        return results

    def _assemble_bundle(
        self,
        bundle: CaseEvidenceBundle,
        results: list[ResourceHistory],
        unresolved: list[UnresolvedState],
    ) -> CaseStateBundle:
        known = {(h.scope.system_id, h.scope.collection, h.scope.resource_id) for h in results}
        if bundle.intent.decision == "DELETE_INTENT":
            for resource in bundle.resources:
                r = resource.reference
                if (r.system_id, logical_collection(r), r.resource_id) not in known:
                    unresolved.append(
                        UnresolvedState(
                            reason="associated_resource_has_no_visible_state",
                            scope=ResourceScope(
                                resource_id=r.resource_id,
                                system_id=r.system_id,
                                collection=logical_collection(r),
                                replica_scope="unknown",
                            ),
                        )
                    )
        supporting = links_sorted(
            link
            for h in results
            for o in h.observations
            if o.support != "UNKNOWN"
            for link in [
                o.link,
                *(ref for chain in o.association_links for ref in chain.supporting_observations),
            ]
        )
        conflicting = links_sorted(
            link
            for h in results
            for link in [
                *h.conflicting_evidence,
                *(
                    ref
                    for selection in (h.record, h.flow, h.restore)
                    for ref in selection.conflicting_evidence
                ),
            ]
        )
        limitations = sorted(
            {
                *bundle.limitations,
                "Last observed states do not prove continuous state between observations or complete discovery.",
                "Null identifiers and category names do not establish redaction, anonymization, or policy compliance.",
                "Replica comparisons with different observation times may reflect temporal skew.",
                "Potential associations, unscoped negatives, deferred files, and missing rows remain unresolved.",
            }
        )
        if bundle.deferred_evidence:
            unresolved.append(
                UnresolvedState(reason="unassigned_deferred_evidence_requires_interpretation")
            )
        if bundle.ambiguities:
            unresolved.append(UnresolvedState(reason="phase2_correlation_or_identity_ambiguities"))
        if bundle.intent.decision == "DELETE_INTENT" and not results:
            unresolved.append(UnresolvedState(reason="no_resource_observations"))
        absence = []
        if bundle.intent.decision == "DELETE_INTENT" and bundle.primary_profile_candidates:
            absence = [
                self._candidate_absence(r, bundle.audit_at)
                for r in bundle.primary_profile_candidates
            ]
            absence = absence if all(absence) else []
            unresolved.append(
                UnresolvedState(
                    reason="primary_profile_ambiguous_all_candidates_absent"
                    if absence
                    else "primary_profile_ambiguous"
                )
            )
        return CaseStateBundle(
            case_id=bundle.case_id,
            audit_at=bundle.audit_at,
            intent=bundle.intent,
            identity=bundle.identity,
            resource_histories=results,
            replica_drift=compare_replicas(results),
            supporting_evidence=supporting,
            conflicting_evidence=conflicting,
            unresolved_states=sorted(set(unresolved), key=lambda u: u.model_dump_json()),
            limitations=limitations,
            primary_profile_absence=links_sorted(link for link in absence if link is not None),
        )

    def _candidate_absence(self, ref: ResourceRef, cutoff: datetime) -> ObservationLink | None:
        """Citation proving a candidate record absent at the cutoff, from its own latest
        citable read or else the latest complete listing omitting it; None otherwise."""
        if self.index is None:
            return None
        facts = []
        for i in sorted(self.index.by_resource.get(ref.resource_id, ())):
            o = self.index.observations[i]
            if o.kind != "evidence" or not self._visible(o, cutoff):
                continue
            for r in o.resources:
                if r.resource_id == ref.resource_id and r.system_id == ref.system_id:
                    item = AssociatedObservation(
                        observation=o,
                        association="CONFIRMED",
                        reason="state_only",
                        links=[
                            CorrelationLink(
                                method="RESOURCE", supporting_observations=[ObservationLink.of(o)]
                            )
                        ],
                    )
                    fact = interpret(item, r)
                    if (
                        fact.support == "PROVEN"
                        and fact.record_state != "UNKNOWN"
                        and fact.observed_at <= cutoff
                    ):
                        facts.append(fact)
        if facts:
            scopes = defaultdict(list)
            for fact in facts:
                scopes[scope_key(fact.scope)].append(fact)
            selections = [select_state(values, "record") for values in scopes.values()]
            return (
                min(
                    (link for state in selections for link in state.supporting_evidence),
                    key=lambda link: (link.evidence_id, link.locator),
                )
                if all(
                    state.state == "ABSENT" and state.support == "PROVEN" for state in selections
                )
                else None
            )
        best = self._latest_listing(ref.system_id, logical_collection(ref), cutoff)
        return (
            ObservationLink.of(best.surface)
            if best and ref.resource_id not in best.resource_ids
            else None
        )

    def _latest_listing(
        self, system: str | None, collection: str | None, cutoff: datetime
    ) -> Listing | None:
        """The newest complete listing of one system collection known by the cutoff."""
        best: Listing | None = None
        for item in self.surfaces.get((system, collection), ()):
            if (
                item.observed_at is not None
                and item.observed_at <= cutoff
                and self._visible(item.surface, cutoff)
                and (
                    best is None or best.observed_at is None or item.observed_at > best.observed_at
                )
            ):
                best = item
        return best

    def _snapshot_gaps(
        self, histories: defaultdict[tuple[str, ...], list[TemporalObservation]], cutoff: datetime
    ) -> None:
        """Expose missing coverage in known sibling SQL tables, never infer absence.

        A schema and grounded sibling row establish the comparison surface only.
        They cannot establish that an incomplete export contains every resource.
        """
        additions = []
        for observations in list(histories.values()):
            for fact in observations:
                if (
                    fact.category != "SNAPSHOT"
                    or fact.support != "PROVEN"
                    or not fact.physical_table
                ):
                    continue
                family = REPLICA_SUFFIX.sub("", fact.physical_table)
                if family not in TABLE_SYSTEMS or fact.scope.collection != family:
                    continue
                for schema in self.schemas.get(fact.provenance.evidence_id, ()):
                    table = schema.payload["table"]
                    assert isinstance(table, str), "SQL schema table must be a name"
                    if REPLICA_SUFFIX.sub("", table) != family or table == fact.physical_table:
                        continue
                    if not self._visible(schema, cutoff):
                        continue
                    ref = ResourceRef(
                        resource_id=fact.scope.resource_id,
                        system_id=fact.scope.system_id,
                        collection=family,
                        physical_table=table,
                    )
                    match = REPLICA_SUFFIX.search(table)
                    scope = ResourceScope(
                        resource_id=ref.resource_id,
                        system_id=ref.system_id,
                        collection=family,
                        replica_scope=match[1] if match else "table:" + table,
                    )
                    key = scope_key(scope)
                    if any(
                        o.provenance.evidence_id == fact.provenance.evidence_id
                        for o in histories.get(key, ())
                    ):
                        continue
                    observed_at, available_at = observation_time(schema), schema.available_at
                    assert observed_at is not None and available_at is not None
                    gap = TemporalObservation(
                        scope=scope,
                        physical_table=table,
                        observed_at=observed_at,
                        available_at=available_at,
                        provenance=schema.provenance,
                        association="CONFIRMED",
                        association_links=fact.association_links,
                        category="SNAPSHOT_GAP",
                        support="UNKNOWN",
                        reason="no_confirmed_counterpart_row; snapshot_has_no_completeness_guarantee",
                    )
                    additions.append((key, gap))
        for key, gap in additions:
            if gap not in histories[key]:
                histories[key].append(gap)

    def _coverage_absence(
        self, histories: defaultdict[tuple[str, ...], list[TemporalObservation]], cutoff: datetime
    ) -> None:
        """A confirmed resource never read in a supported state is ABSENT when the latest
        complete listing of its system's collection, available by the cutoff, omits it.

        Any supported read of the resource takes precedence, so a listing never overrides
        an explicit presence or absence observation of the same record.
        """
        groups = defaultdict(list)
        for observations in histories.values():
            for fact in observations:
                groups[(fact.scope.system_id, fact.scope.resource_id)].append(fact)
        for (system, resource), facts in sorted(
            groups.items(), key=lambda g: (g[0][0] or "", g[0][1])
        ):
            confirmed = [f for f in facts if f.association == "CONFIRMED" and f.association_links]
            if (
                system is None
                or not confirmed
                or any(
                    f.support == "PROVEN"
                    and (f.record_state, f.flow_state, f.restore_state) != ("UNKNOWN",) * 3
                    for f in facts
                )
            ):
                continue
            collections = {f.scope.collection for f in confirmed if f.scope.collection}
            # A listing of one collection cannot prove absence from another, or
            # resolve a resource whose collection is unknown.
            if len(collections) != 1:
                continue
            collection = next(iter(collections))
            best = self._latest_listing(system, collection, cutoff)
            if best is None or resource in best.resource_ids:
                continue
            at, surface = best.observed_at, best.surface
            assert at is not None, "_latest_listing returns only timestamped listings"
            # A linkage-only row seen present at or after the listing outranks the omission.
            if any(
                f.record_state in {"PRESENT", "REDACTED", "ANONYMIZED"} and f.observed_at >= at
                for f in facts
            ):
                continue
            scope = ResourceScope(
                resource_id=resource,
                system_id=system,
                collection=collection,
                replica_scope="coverage",
            )
            physical_table, available_at = surface.payload.get("table"), surface.available_at
            assert physical_table is None or isinstance(physical_table, str)
            assert at is not None and available_at is not None
            histories[scope_key(scope)].append(
                TemporalObservation(
                    scope=scope,
                    physical_table=physical_table,
                    observed_at=at,
                    available_at=available_at,
                    provenance=surface.provenance,
                    association="CONFIRMED",
                    association_links=confirmed[0].association_links,
                    category="SNAPSHOT_COVERAGE",
                    record_state="ABSENT",
                    support="PROVEN",
                    reason="absent_from_latest_complete_listing_of_collection",
                )
            )
