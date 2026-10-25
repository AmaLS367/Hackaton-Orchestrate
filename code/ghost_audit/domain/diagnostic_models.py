"""Identifier-only uncertainty records, separate from official predictions."""

from pydantic import Field
from ghost_audit.domain.models import StrictModel


class Obligation(StrictModel):
    resource: str
    scope: str
    category: str | None
    required_action: str | None
    observed_state: str
    causes: list[str]


class AbstentionDiagnostic(StrictModel):
    case_id: str
    intent: str
    identity: str
    confirmed_resources: list[str]
    potential_resources: list[str]
    primary_profile_candidates: list[str]
    proven_states: dict[str, list[str]]
    unknown_states: dict[str, list[str]]
    verified_deletion_treatment: list[str]
    violations: list[str]
    missing_policy_conditions: list[str]
    account_attribution: str
    listing_coverage: dict[str, str]
    candidate_evidence_ids: list[str]
    unlinked_readbacks: dict[str, list[str]]
    late_evidence_ids: list[str]
    unresolved_obligations: list[Obligation]
    blockers: list[str]
    root_causes: list[str]
    earliest_failure_stage: str | None
    stage_counts: dict[str, int] = Field(default_factory=dict)
