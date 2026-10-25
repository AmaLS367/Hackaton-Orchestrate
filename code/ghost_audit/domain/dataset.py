"""In-memory participant inputs shared by the two prediction use cases."""

from dataclasses import dataclass, field

from ghost_audit.domain.evidence_index import EvidenceRegistry
from ghost_audit.domain.models import (
    Activity,
    DeletionRequest,
    DeletionRule,
    EvidenceDocument,
    Identity,
    IdentityChange,
    Observation,
)


@dataclass
class Dataset:
    """In-memory participant inputs and their citation registry; no file access occurs here."""

    requests: list[DeletionRequest]
    identities: list[Identity]
    identity_changes: list[IdentityChange]
    activities: list[Activity]
    rules: list[DeletionRule]
    documents: list[EvidenceDocument]
    observations: list[Observation]
    # Every participant request (both request files): the deletion workflow's
    # activity stream is shared, so batch attribution must see all of them.
    workflow_requests: list[DeletionRequest] = field(default_factory=list)
    registry: EvidenceRegistry = field(init=False)

    def __post_init__(self) -> None:
        self.registry = EvidenceRegistry(
            documents=self.documents,
            activities=self.activities,
            identity_changes=self.identity_changes,
        )
