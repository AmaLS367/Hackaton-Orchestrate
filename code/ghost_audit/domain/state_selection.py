"""Select scoped temporal facts and compare replicas while preserving contradictions."""

from collections import defaultdict
from itertools import combinations
from ghost_audit.domain.association_models import ObservationLink
from ghost_audit.domain.temporal_models import (
    ReplicaDrift,
    ResourceHistory,
    ResourceScope,
    StateSelection,
    TemporalObservation,
)


def scope_key(scope: ResourceScope) -> tuple[str, ...]:
    return (scope.system_id or "", scope.collection or "", scope.resource_id, scope.replica_scope)


def links_sorted(links) -> list[ObservationLink]:
    return sorted(set(links), key=lambda link: (link.evidence_id, link.file_path, link.locator))


def observation_key(o: TemporalObservation):
    return (
        o.observed_at,
        o.available_at,
        o.provenance.evidence_id,
        o.provenance.locator,
        o.model_dump_json(),
    )


def select_state(observations: list[TemporalObservation], dimension: str) -> StateSelection:
    field = dimension + "_state"
    direct = [
        o
        for o in observations
        if o.association == "CONFIRMED"
        and o.support in {"PROVEN", "CONFLICTED"}
        and getattr(o, field) != "UNKNOWN"
    ]
    pool = direct
    if not pool:
        claims = [
            o
            for o in observations
            if o.association == "CONFIRMED"
            and o.support == "CLAIM_ONLY"
            and getattr(o, field) != "UNKNOWN"
        ]
        return StateSelection(
            dimension=dimension,
            state="UNKNOWN",
            support="CLAIM_ONLY" if claims else "UNKNOWN",
            observed_at=None,
            supporting_evidence=links_sorted(o.link for o in claims),
            conflicting_evidence=[],
            reason="claims_cannot_establish_state" if claims else "no_supported_observation",
        )
    # The newest supported read decides; among simultaneous reads, full contents and
    # precise independent reads outrank summary readback labels.
    latest_at = max(o.observed_at for o in pool)
    latest = [o for o in pool if o.observed_at == latest_at]
    precise = [
        o
        for o in latest
        if o.category in {"RESOURCE_READBACK", "SNAPSHOT", "DOCUMENT", "SNAPSHOT_COVERAGE"}
    ]
    latest = precise or latest
    states = {getattr(o, field) for o in latest}
    conflicted = len(states) > 1 or any(
        o.support == "CONFLICTED"
        and (not o.conflict_dimensions or dimension in o.conflict_dimensions)
        for o in latest
    )
    selected = "UNKNOWN" if conflicted else next(iter(states))
    contrary = [
        o
        for o in observations
        if o not in latest
        and o.observed_at >= latest_at
        and o.association == "CONFIRMED"
        and getattr(o, field) not in {"UNKNOWN", selected}
        and o.support in {"CLAIM_ONLY", "PROVEN", "CONFLICTED"}
    ]
    conflicts = [*latest, *contrary] if conflicted else contrary
    return StateSelection(
        dimension=dimension,
        state=selected,
        support="CONFLICTED" if conflicted else "PROVEN",
        observed_at=latest_at,
        supporting_evidence=links_sorted(o.link for o in latest),
        conflicting_evidence=links_sorted(o.link for o in conflicts),
        reason=(
            "incompatible_direct_observations_at_same_time"
            if conflicted
            else "latest_precise_observation_in_same_scope; contradictory_claims_or_summaries_preserved"
            if contrary
            else "latest_supported_observation_in_same_scope"
        ),
    )


def historical_conflicts(observations: list[TemporalObservation]):
    """A later resolution must not discard an earlier contradictory readback pair."""
    links, reasons = [], []
    for o in observations:
        if o.association == "CONFIRMED" and o.support == "CONFLICTED":
            links.append(o.link)
            reasons.extend(o.conflicts)
    for dimension in ("record", "flow", "restore"):
        groups = defaultdict(list)
        for o in observations:
            if o.association == "CONFIRMED" and o.support in {"PROVEN", "CONFLICTED"}:
                if getattr(o, dimension + "_state") != "UNKNOWN":
                    groups[o.observed_at].append(o)
        for values in groups.values():
            if len({getattr(o, dimension + "_state") for o in values}) > 1:
                links.extend(o.link for o in values)
                reasons.append("simultaneous_" + dimension + "_observations_disagree")
            if dimension == "record":
                for left, right in combinations(values, 2):
                    a, b = field_signatures(left), field_signatures(right)
                    if any(a[k] != b[k] for k in a.keys() & b.keys()):
                        links.extend([left.link, right.link])
                        reasons.append("simultaneous_field_observations_disagree")
    return links_sorted(links), sorted(set(reasons))


def field_signatures(observation: TemporalObservation):
    return {
        f.path: (f.representation, f.value if f.representation == "VALUE" else None)
        for f in observation.fields
    }


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
            if any(
                o.category == "SNAPSHOT_GAP"
                and (h.record.observed_at is None or o.observed_at >= h.record.observed_at)
                for h in (left, right)
                for o in h.observations
            ):
                kind = "COVERAGE_GAP"
            if left.record.support == right.record.support == "PROVEN":
                if left.record.state != right.record.state:
                    kind = "STATE_DISAGREEMENT"
                else:

                    def fields(h):
                        return {
                            path: value
                            for o in h.observations
                            if o.link in h.record.supporting_evidence
                            for path, value in field_signatures(o).items()
                        }

                    a, b = fields(left), fields(right)
                    if any(a[k] != b[k] for k in a.keys() & b.keys()):
                        kind = "FIELD_DISAGREEMENT"
            # Connector and restore disagreements matter independently of existence.
            if any(
                getattr(left, d).support == getattr(right, d).support == "PROVEN"
                and getattr(left, d).state != getattr(right, d).state
                for d in ("flow", "restore")
            ):
                kind = "STATE_DISAGREEMENT"
            if kind:
                evidence = links_sorted(
                    o.link
                    for h in (left, right)
                    for o in h.observations
                    if o.support == "PROVEN" or o.category == "SNAPSHOT_GAP"
                )
                times = [
                    h.record.observed_at or max(o.observed_at for o in h.observations)
                    for h in (left, right)
                ]
                drift.append(
                    ReplicaDrift(
                        system_id=system,
                        collection=collection,
                        resource_id=resource,
                        scopes=sorted([left.scope.replica_scope, right.scope.replica_scope]),
                        kind=kind,
                        contemporaneous=times[0] == times[1],
                        evidence=evidence,
                        reason="compare_only_established_system_resource_and_logical_collection; "
                        "missing_coverage_is_not_absence",
                    )
                )
    return sorted(drift, key=lambda d: d.model_dump_json())
