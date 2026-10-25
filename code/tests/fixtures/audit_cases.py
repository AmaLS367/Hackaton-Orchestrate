"""Independent synthetic audit cases builders; never sample answers."""

from ghost_audit.application.strict_audit import predict
from ghost_audit.domain.dataset import Dataset
from ghost_audit.domain.models import (
    DeletionRequest,
    DeletionRule,
    EvidenceDocument,
    EvidenceFile,
    Identity,
    Observation,
)
from ghost_audit.domain.policy_models import CaseDecision
from ghost_audit.infrastructure.parsers.structured import ExtractionContext, parse_json
from pydantic import JsonValue

EARLY = "2026-01-01T10:00:00Z"


LATE = "2026-01-02T10:00:00Z"


CUTOFF = "2026-01-03T10:00:00Z"


FUTURE = "2026-01-04T10:00:00Z"


def observation(
    resource: str = "arbitrary-key",
    category: str = "USER_PROFILE",
    *,
    file: str = "fixture",
    at: str = EARLY,
    system: str = "account_service",
    collection: str | None = "customer_profiles",
    **fields: JsonValue,
) -> Observation:
    ctx = ExtractionContext(
        EvidenceFile.model_validate(
            {
                "file_id": file,
                "file_path": f"evidence/{file}.json",
                "origin": system,
                "captured_at": at,
            }
        ),
        "b" * 64,
    )
    return parse_json(
        {
            "captured_at": at,
            "system": system,
            "collection": collection,
            "records": [
                {"resource_id": resource, "user_id": "subject_x", "record_type": category, **fields}
            ],
        },
        ctx,
    )[-1]


def dataset(
    rules: list[DeletionRule],
    *observations: Observation,
    text: str = "Please delete my account and all personal data.",
    email: str = "subject@example.test",
) -> Dataset:
    request = DeletionRequest.model_validate(
        {
            "case_id": "synthetic",
            "email": email,
            "requested_at": EARLY,
            "reported_status": "COMPLETE",
            "reported_at": EARLY,
            "audit_at": CUTOFF,
            "request_text": text,
        }
    )
    identity = Identity.model_validate(
        {
            "user_id": "subject_x",
            "name": "Synthetic Subject",
            "email": "subject@example.test",
            "phone": "+10000000001",
            "email_hash": "synthetic_hash",
            "updated_at": "2025-12-01T00:00:00Z",
        }
    )
    sources = {o.provenance.evidence_id: o for o in observations}
    documents = [
        EvidenceDocument(
            manifest=EvidenceFile.model_validate(
                {
                    "file_id": o.provenance.evidence_id,
                    "file_path": o.provenance.file_path,
                    "origin": o.provenance.origin,
                    "captured_at": o.provenance.captured_at,
                }
            ),
            sha256=o.provenance.sha256,
            status="parsed",
            observations=[
                item
                for item in observations
                if item.provenance.evidence_id == o.provenance.evidence_id
            ],
        )
        for o in sources.values()
    ]
    return Dataset([request], [identity], [], [], rules, documents, list(observations))


def decision(
    rules: list[DeletionRule],
    *observations: Observation,
    text: str = "Please delete my account and all personal data.",
    email: str = "subject@example.test",
) -> CaseDecision:
    return predict(dataset(rules, *observations, text=text, email=email)).cases[0]


def operations(result: CaseDecision, phase: str | None = None) -> list[str]:
    assert result.prediction is not None, result.blockers
    assert result.prediction is not None
    return [s.operation for s in result.prediction.steps if phase is None or s.phase == phase]


def absent(
    resource: str = "arbitrary-key",
    category: str = "USER_PROFILE",
    *,
    file: str = "fixture",
    at: str = EARLY,
    system: str = "account_service",
    collection: str | None = "customer_profiles",
    **fields: JsonValue,
) -> Observation:
    return observation(
        resource,
        category,
        file=file,
        at=at,
        system=system,
        collection=collection,
        result="NOT_FOUND",
        observed_at=EARLY,
        **fields,
    )
