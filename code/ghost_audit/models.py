"""Strict input contracts and provenance-bearing observations, without verdicts."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from .time import Timestamp

Identifier = Annotated[str, Field(min_length=1, pattern=r"\S")]


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class DeletionRequest(StrictModel):
    case_id: Identifier
    email: Identifier
    requested_at: Timestamp
    reported_status: Literal["COMPLETE", "PARTIALLY_COMPLETE", "NOT_STARTED"]
    reported_at: Timestamp
    audit_at: Timestamp
    request_text: Identifier


class Identity(StrictModel):
    user_id: Identifier
    name: str
    email: str
    phone: str
    email_hash: str
    updated_at: Timestamp


class IdentityChange(StrictModel):
    audit_id: Identifier
    user_id: Identifier
    event_time: Timestamp
    field_name: Identifier
    old_value: str
    new_value: str


class Activity(StrictModel):
    activity_id: Identifier
    event_time: Timestamp
    event_type: Identifier
    source_system: str
    target_system: str
    resource_id: str
    reported_result: str
    details: str


class DeletionRule(StrictModel):
    rule_id: Identifier
    data_category: Identifier
    condition: Identifier
    required_action: Literal["DELETE", "REDACT", "ANONYMIZE", "RETAIN"]


class EvidenceFile(StrictModel):
    file_id: Identifier
    file_path: Identifier
    origin: Identifier
    captured_at: Timestamp


class SourceTimestamp(StrictModel):
    locator: Identifier
    field: Identifier
    value: Timestamp
    # Future expiration/retention deadlines describe policy, not observation time.
    role: Literal["source", "business"] = "source"


class Provenance(StrictModel):
    evidence_id: Identifier
    file_path: Identifier
    origin: Identifier
    locator: Identifier
    captured_at: Timestamp | None
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    timestamps: list[SourceTimestamp] = Field(default_factory=list)


class ResourceRef(StrictModel):
    resource_id: Identifier
    system_id: Identifier | None = None
    collection: str | None = None
    physical_table: str | None = None


class Observation(StrictModel):
    provenance: Provenance
    kind: Literal["evidence", "activity_claim", "identity"] = "evidence"
    payload: dict[str, JsonValue]
    raw_text: str = ""
    resources: list[ResourceRef] = Field(default_factory=list)
    system_ids: list[str] = Field(default_factory=list)
    trace_id: str | None = None

    @property
    def available_at(self) -> datetime | None:
        times = [t.value for t in self.provenance.timestamps if t.role == "source"]
        if self.provenance.captured_at is not None:
            times.append(self.provenance.captured_at)
        return max(times) if times else None


class EvidenceDocument(StrictModel):
    manifest: EvidenceFile
    sha256: str
    status: Literal["parsed", "deferred"]
    observations: list[Observation]
    notes: list[str] = Field(default_factory=list)


class EvidenceEntry(StrictModel):
    """Citation metadata, independent of observations or any claimed record state."""

    evidence_id: Identifier
    file_path: Identifier
    origin: Identifier
    captured_at: Timestamp | None
    parsing_status: Literal['parsed', 'deferred']
