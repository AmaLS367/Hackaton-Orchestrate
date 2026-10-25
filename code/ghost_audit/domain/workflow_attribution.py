"""Search for candidate deletion-worker events near a request's reported workflow.

The workflow processes a request's resources shortly before it reports the request's
status in this dataset. These are retrieval heuristics, not a supplied contract:

- an event belongs to a request only when exactly one authorized request's batch window
  contains it after exact-identity exclusions visible at that request's audit time;
- a primary-profile deletion must also report a result consistent with the request's
  reported status, and each request has at most one primary profile, so unique
  assignments eliminate that profile from competing requests;
- requests from both participant request files compete, because they share the stream.

Timing and result consistency establish neither subject ownership nor state.
The correlator keeps these candidates POTENTIAL until an independent link exists.
"""

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta

from ghost_audit.domain.correlation import EvidenceCorrelator
from ghost_audit.domain.evidence_index import EvidenceIndex
from ghost_audit.domain.identity import IdentityResolver
from ghost_audit.domain.intent import IntentClassifier
from ghost_audit.domain.models import DeletionRequest
from ghost_audit.domain.observation_clocks import known_at, observation_time

WORKER = "deletion_worker"
# Primary profiles are submitted well before the report (or within minutes of it);
# per-resource policy actions run in the final half hour before the report.
PRIMARY_WINDOWS = (
    (timedelta(minutes=-80), timedelta(minutes=-40)),
    (timedelta(minutes=-5), timedelta(minutes=10)),
)
ACTION_WINDOWS = ((timedelta(minutes=-35), timedelta(minutes=10)),)
# A batch reports its status from the primary-profile result. When the profile is
# submitted early, other actions follow and the result alone sets the status; a
# profile finished at report time may share the report with failed later actions.
EARLY_STATUS = {
    "SUCCESS": {"COMPLETE"},
    "PARTIAL": {"PARTIALLY_COMPLETE"},
    "FAILED": {"NOT_STARTED"},
}
LATE_STATUS = {
    "SUCCESS": {"COMPLETE", "PARTIALLY_COMPLETE"},
    "PARTIAL": {"PARTIALLY_COMPLETE"},
    "FAILED": {"NOT_STARTED", "PARTIALLY_COMPLETE"},
}


def within(
    windows: tuple[tuple[timedelta, timedelta], ...], reported_at: datetime, at: datetime
) -> bool:
    return any(reported_at + low <= at <= reported_at + high for low, high in windows)


class WorkflowAttribution:
    """Retrieve timing candidates that still require independent ownership proof."""

    def __init__(
        self,
        requests: Iterable[DeletionRequest],
        index: EvidenceIndex,
        resolver: IdentityResolver,
        correlator: EvidenceCorrelator,
        classifier: IntentClassifier,
    ) -> None:
        self.index, self.resolver = index, resolver
        self.requests = [
            r
            for r in sorted(requests, key=lambda r: r.case_id)
            if classifier.classify(r).decision == "DELETE_INTENT"
        ]
        self.users = {r.case_id: resolver.resolve(r).user_id for r in self.requests}
        observations = index.observations
        # Exact-identity owners per scoped resource, with the time each became visible.
        self.owners = defaultdict(list)
        for i, o in enumerate(observations):
            if (
                o.kind == "identity"
                or o.kind == "activity_claim"
                and o.payload.get("event_type") != "LINK_RESOURCE_IDENTITY"
            ):
                continue
            at = known_at(o)
            if at is None:
                continue
            tokens = correlator.tokens[i] | correlator.subjects[i]
            for r in o.resources:
                if r.system_id:
                    self.owners[(r.system_id, r.resource_id)].append((at, tokens))
        self.events = []
        primary_times = []
        for i, o in enumerate(observations):
            p = o.payload
            if o.kind != "activity_claim" or p.get("source_system") != WORKER or not o.resources:
                continue
            at = observation_time(o)
            assert at is not None, "Workflow activities require a source clock"
            primary = (
                p.get("target_system") == "account_service"
                and p.get("event_type") == "DELETE_RECORD"
            )
            if primary:
                primary_times.append(at)
            windows = PRIMARY_WINDOWS if primary else ACTION_WINDOWS
            candidates = [r for r in self.requests if within(windows, r.reported_at, at)]
            if primary:
                result = str(p.get("reported_result", "")).upper()
                candidates = [
                    r
                    for r in candidates
                    if r.reported_status
                    in (
                        EARLY_STATUS
                        if within(PRIMARY_WINDOWS[:1], r.reported_at, at)
                        else LATE_STATUS
                    ).get(result, set())
                ]
            if candidates:
                system, resource_id = p["target_system"], p["resource_id"]
                assert isinstance(system, str) and isinstance(resource_id, str)
                self.events.append((i, (system, resource_id), at, primary, candidates))
        # More primary profiles near a report time than known requests reporting then
        # means a batch of a request outside both files overlaps it: per-resource
        # actions in that window cannot be attributed by elimination.
        reported: defaultdict[datetime, int] = defaultdict(int)
        for request in self.requests:
            reported[request.reported_at] += 1
        self.crowded = {
            at
            for at, count in reported.items()
            if sum(within(PRIMARY_WINDOWS, at, t) for t in primary_times) > count
        }

    def pins(self, resource: tuple[str, str], cutoff: datetime) -> set[str]:
        """Users exactly identified with a resource by evidence observed by the cutoff."""
        users = set()
        for at, tokens in self.owners.get(resource, ()):
            if at <= cutoff:
                owners = (
                    set().union(*(self.resolver.owners(t, cutoff) for t in tokens))
                    if tokens
                    else set()
                )
                if len(owners) == 1:
                    users |= owners
        return users

    def attributed(self, request: DeletionRequest) -> list[int]:
        """Observation indices of worker events uniquely attributable to this request."""
        return self.resolve(request)[0]

    def primary_candidates(self, request: DeletionRequest) -> list[int]:
        """Primary-profile events still possible for this request when none is unique."""
        unique, options = self.resolve(request)
        return [] if any(i in unique for i in options) else sorted(options)

    def resolve(self, request: DeletionRequest) -> tuple[list[int], set[int]]:
        if request.case_id not in self.users:
            return [], set()
        cutoff = request.audit_at
        result = []
        primaries = {}
        # Only this request's events and those of directly competing requests matter.
        own = [e for e in self.events if any(r.case_id == request.case_id for r in e[4])]
        rivals = {r.case_id for e in own for r in e[4]}
        local = [e for e in self.events if any(r.case_id in rivals for r in e[4])]
        for i, resource, at, primary, candidates in local:
            if at > cutoff:
                continue
            pinned = self.pins(resource, cutoff)
            allowed = [r for r in candidates if not pinned or self.users[r.case_id] in pinned]
            if primary:
                primaries[i] = (allowed, pinned)
            elif [r.case_id for r in allowed] == [
                request.case_id
            ] and request.reported_at not in self.crowded:
                result.append(i)
        options = defaultdict(set)
        forced = defaultdict(set)
        for i, (allowed, pinned) in primaries.items():
            for r in allowed:
                options[r.case_id].add(i)
                if self.users[r.case_id] in pinned:
                    forced[r.case_id].add(i)
        for case_id, events in forced.items():
            options[case_id] = set(events)
        changed = True
        while changed:
            changed = False
            for case_id, events in sorted(options.items()):
                if len(events) == 1:
                    event = next(iter(events))
                    for other, values in options.items():
                        if other != case_id and event in values:
                            values.discard(event)
                            changed = True
        mine = options.get(request.case_id, set())
        if len(mine) == 1:
            result.extend(mine)
        return sorted(result), set(mine)
