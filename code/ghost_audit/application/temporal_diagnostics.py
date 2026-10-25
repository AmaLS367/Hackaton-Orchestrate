"""Aggregate discovery diagnostics: counts, never identifiers or prediction accuracy."""

from collections import Counter
from typing import TypedDict

from ghost_audit.domain.temporal_models import CaseStateBundle


class TemporalDiagnostics(TypedDict):
    """Serialized diagnostic fields; reporting never changes prediction state."""

    cases: int
    authorized_cases: int
    cases_with_established_resource_states: int
    resource_scopes: int
    resources_with_established_states: int
    resources_with_unknown_states: int
    resource_states: dict[str, int]
    record_state_support: dict[str, int]
    observation_support: dict[str, int]
    conflicting_observations: int
    replica_comparisons_with_drift_or_gaps: int
    replica_drift_types: dict[str, int]
    active_data_flows: int
    inactive_data_flows: int
    restore_risks: int
    blocked_restores: int
    cases_with_incomplete_evidence: int
    incomplete_evidence_cases: list[str]
    coverage: str
    prediction_accuracy: str


def diagnostics(bundles: list[CaseStateBundle]) -> TemporalDiagnostics:
    """Summarize temporal scope and conflict coverage without claiming prediction accuracy."""
    histories = [h for b in bundles for h in b.resource_histories]
    records: Counter[str] = Counter(h.record.state for h in histories)
    support: Counter[str] = Counter(h.record.support for h in histories)
    incomplete = [
        b.case_id
        for b in bundles
        if b.intent.decision == "DELETE_INTENT"
        and (b.unresolved_states or b.conflicting_evidence or b.replica_drift)
    ]
    return {
        "cases": len(bundles),
        "authorized_cases": sum(b.intent.decision == "DELETE_INTENT" for b in bundles),
        "cases_with_established_resource_states": sum(
            any(h.record.support == "PROVEN" for h in b.resource_histories) for b in bundles
        ),
        "resource_scopes": len(histories),
        "resources_with_established_states": sum(h.record.support == "PROVEN" for h in histories),
        "resources_with_unknown_states": records["UNKNOWN"],
        "resource_states": {
            s: records[s] for s in ("PRESENT", "ABSENT", "REDACTED", "ANONYMIZED", "UNKNOWN")
        },
        "record_state_support": {
            s: support[s] for s in ("PROVEN", "CLAIM_ONLY", "CONFLICTED", "UNKNOWN")
        },
        "observation_support": dict(
            sorted(Counter(o.support for h in histories for o in h.observations).items())
        ),
        "conflicting_observations": sum(len(b.conflicting_evidence) for b in bundles),
        "replica_comparisons_with_drift_or_gaps": sum(len(b.replica_drift) for b in bundles),
        "replica_drift_types": dict(
            sorted(Counter(d.kind for b in bundles for d in b.replica_drift).items())
        ),
        "active_data_flows": sum(
            h.flow.state == "ACTIVE" and h.flow.support == "PROVEN" for h in histories
        ),
        "inactive_data_flows": sum(
            h.flow.state == "INACTIVE" and h.flow.support == "PROVEN" for h in histories
        ),
        "restore_risks": sum(
            h.restore.state == "ALLOWED" and h.restore.support == "PROVEN" for h in histories
        ),
        "blocked_restores": sum(
            h.restore.state == "BLOCKED" and h.restore.support == "PROVEN" for h in histories
        ),
        "cases_with_incomplete_evidence": len(incomplete),
        "incomplete_evidence_cases": sorted(incomplete),
        "coverage": "discovered resource/source scopes only; no guarantee of exhaustive discovery",
        "prediction_accuracy": "not measured; Phase 3 does not apply deletion policy or produce predictions",
    }
