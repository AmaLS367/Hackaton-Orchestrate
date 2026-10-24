"""Phase 2 contracts: associations are evidence links, never deletion verdicts."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from .models import EvidenceEntry, Observation, ResourceRef, StrictModel
from .time import Timestamp


class IntentResult(StrictModel):
    decision: Literal['DELETE_INTENT', 'NO_DELETE_INTENT', 'UNCERTAIN']
    reason_id: str
    confidence: Literal['HIGH', 'LOW']
    fallback_recommended: bool


class IdentityAlias(StrictModel):
    field_name: Literal['user_id', 'email', 'phone', 'email_hash', 'name']
    normalized_value: str
    original_value: str
    source: Literal['identity_snapshot', 'audit_log']
    audit_id: str | None = None
    event_time: Timestamp
    value_role: Literal['snapshot', 'old_value', 'new_value']
    valid_from: Timestamp | None = None
    valid_until: Timestamp | None = None
    active_at_cutoff: bool | None


class ResolvedIdentity(StrictModel):
    status: Literal['RESOLVED', 'AMBIGUOUS', 'UNRESOLVED']
    user_id: str | None = None
    candidates: list[str] = Field(default_factory=list)
    aliases: list[IdentityAlias] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)


class ObservationLink(StrictModel):
    evidence_id: str
    file_path: str
    locator: str

    @classmethod
    def of(cls, observation: Observation) -> 'ObservationLink':
        p = observation.provenance
        return cls(evidence_id=p.evidence_id, file_path=p.file_path, locator=p.locator)


class CorrelationLink(StrictModel):
    method: Literal['DIRECT_IDENTIFIER', 'SCOPED_TRACE', 'RESOURCE', 'EXPLICIT_RESOURCE_REFERENCE',
                    'WORKFLOW_BATCH']
    supporting_observations: list[ObservationLink]
    matched_identifiers: list[str] = Field(default_factory=list)
    alias_origins: list[IdentityAlias] = Field(default_factory=list)
    resource: ResourceRef | None = None


class AssociatedObservation(StrictModel):
    observation: Observation
    association: Literal['CONFIRMED', 'POTENTIAL', 'UNRELATED']
    links: list[CorrelationLink] = Field(default_factory=list)
    reason: str


class AssociatedResource(StrictModel):
    reference: ResourceRef
    supporting_observations: list[ObservationLink]


class CaseEvidenceBundle(StrictModel):
    case_id: str
    audit_at: Timestamp
    intent: IntentResult
    identity: ResolvedIdentity
    user_id: str | None
    aliases: list[IdentityAlias]
    observations: list[AssociatedObservation]
    resources: list[AssociatedResource]
    supporting_evidence_ids: list[str]
    deferred_evidence: list[EvidenceEntry]
    ambiguities: list[str]
    limitations: list[str]
    # Unrelated corpus rows are omitted rather than copied into every case bundle.
    unrelated_observation_count: int
    # Primary profiles the workflow may have targeted when no single one is attributable.
    # They are not associations: none is the subject's record until proven otherwise.
    primary_profile_candidates: list[ResourceRef] = Field(default_factory=list)

    @property
    def observation_timestamps(self) -> list[datetime]:
        return sorted({item.observation.available_at for item in self.observations
                       if item.observation.available_at is not None})
