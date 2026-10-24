"""Phase 3 observable facts. No policy verdicts or proposed operations live here."""

from typing import Literal

from pydantic import Field, JsonValue, model_validator

from .models import Provenance, StrictModel
from .phase2_models import CorrelationLink, IntentResult, ObservationLink, ResolvedIdentity
from .time import Timestamp

RecordState = Literal['PRESENT', 'ABSENT', 'REDACTED', 'ANONYMIZED', 'UNKNOWN']
FlowState = Literal['ACTIVE', 'INACTIVE', 'UNKNOWN']
RestoreState = Literal['ALLOWED', 'BLOCKED', 'UNKNOWN']
Support = Literal['PROVEN', 'CLAIM_ONLY', 'CONFLICTED', 'UNKNOWN']


class ResourceScope(StrictModel):
    resource_id: str
    system_id: str | None
    collection: str | None
    replica_scope: str


class FieldObservation(StrictModel):
    path: str
    role: Literal['DIRECT_IDENTIFIER', 'STABLE_REFERENCE', 'CONTENT']
    representation: Literal['VALUE', 'NULL', 'REDACTED', 'ANONYMIZED']
    value: JsonValue


class TemporalObservation(StrictModel):
    scope: ResourceScope
    physical_table: str | None
    observed_at: Timestamp
    available_at: Timestamp
    provenance: Provenance
    association: Literal['CONFIRMED', 'POTENTIAL']
    association_links: list[CorrelationLink]
    category: Literal['SNAPSHOT', 'RESOURCE_READBACK', 'SERVICE_READBACK',
                      'OPERATION_CLAIM', 'UNINTERPRETED', 'SNAPSHOT_GAP',
                      'SNAPSHOT_COVERAGE', 'DOCUMENT']
    record_state: RecordState = 'UNKNOWN'
    flow_state: FlowState = 'UNKNOWN'
    restore_state: RestoreState = 'UNKNOWN'
    support: Support
    fields: list[FieldObservation] = Field(default_factory=list)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    record_type: str | None = None
    reason: str
    conflicts: list[str] = Field(default_factory=list)
    conflict_dimensions: list[Literal['record', 'flow', 'restore']] = Field(default_factory=list)

    @property
    def link(self) -> ObservationLink:
        p = self.provenance
        return ObservationLink(evidence_id=p.evidence_id, file_path=p.file_path, locator=p.locator)


class StateSelection(StrictModel):
    dimension: Literal['record', 'flow', 'restore']
    state: Literal['PRESENT', 'ABSENT', 'REDACTED', 'ANONYMIZED', 'UNKNOWN',
                   'ACTIVE', 'INACTIVE', 'ALLOWED', 'BLOCKED']
    support: Support
    observed_at: Timestamp | None
    supporting_evidence: list[ObservationLink]
    conflicting_evidence: list[ObservationLink]
    reason: str

    @model_validator(mode='after')
    def consistent_dimension(self):
        allowed = {'record': {'PRESENT', 'ABSENT', 'REDACTED', 'ANONYMIZED', 'UNKNOWN'},
                   'flow': {'ACTIVE', 'INACTIVE', 'UNKNOWN'}, 'restore': {'ALLOWED', 'BLOCKED', 'UNKNOWN'}}
        if self.state not in allowed[self.dimension]:
            raise ValueError('state does not belong to the selected dimension')
        if self.support == 'PROVEN' and (self.state == 'UNKNOWN' or not self.supporting_evidence):
            raise ValueError('proven state requires an explicit state and evidence')
        return self


class ResourceHistory(StrictModel):
    scope: ResourceScope
    observations: list[TemporalObservation]
    record: StateSelection
    flow: StateSelection
    restore: StateSelection
    conflicting_evidence: list[ObservationLink] = Field(default_factory=list)
    conflict_reasons: list[str] = Field(default_factory=list)


class ReplicaDrift(StrictModel):
    system_id: str
    collection: str
    resource_id: str
    scopes: list[str]
    kind: Literal['STATE_DISAGREEMENT', 'FIELD_DISAGREEMENT', 'COVERAGE_GAP']
    contemporaneous: bool
    evidence: list[ObservationLink]
    reason: str


class UnresolvedState(StrictModel):
    scope: ResourceScope | None = None
    evidence: ObservationLink | None = None
    reason: str


class CaseStateBundle(StrictModel):
    case_id: str
    audit_at: Timestamp
    intent: IntentResult
    identity: ResolvedIdentity
    resource_histories: list[ResourceHistory]
    replica_drift: list[ReplicaDrift]
    supporting_evidence: list[ObservationLink]
    conflicting_evidence: list[ObservationLink]
    unresolved_states: list[UnresolvedState]
    limitations: list[str]
    # Set only when every ambiguous primary-profile candidate is proven absent at the
    # cutoff: whichever one the subject's is, it is gone. One citation per candidate.
    primary_profile_absence: list[ObservationLink] = Field(default_factory=list)
