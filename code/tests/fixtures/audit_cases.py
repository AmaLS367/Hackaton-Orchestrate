"""Independent synthetic audit cases builders; never sample answers."""

from ghost_audit.application.strict_audit import predict
from ghost_audit.domain.dataset import Dataset
from ghost_audit.domain.models import DeletionRequest, EvidenceDocument, EvidenceFile, Identity
from ghost_audit.infrastructure.parsers.structured import ExtractionContext, parse_json

EARLY = "2026-01-01T10:00:00Z"


LATE = "2026-01-02T10:00:00Z"


CUTOFF = "2026-01-03T10:00:00Z"


FUTURE = "2026-01-04T10:00:00Z"


def observation(
    resource="arbitrary-key",
    category="USER_PROFILE",
    *,
    file="fixture",
    at=EARLY,
    system="account_service",
    collection="customer_profiles",
    **fields,
):
    ctx = ExtractionContext(
        EvidenceFile(
            file_id=file, file_path=f"evidence/{file}.json", origin=system, captured_at=at
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
    rules,
    *observations,
    text="Please delete my account and all personal data.",
    email="subject@example.test",
):
    request = DeletionRequest(
        case_id="synthetic",
        email=email,
        requested_at=EARLY,
        reported_status="COMPLETE",
        reported_at=EARLY,
        audit_at=CUTOFF,
        request_text=text,
    )
    identity = Identity(
        user_id="subject_x",
        name="Synthetic Subject",
        email="subject@example.test",
        phone="+10000000001",
        email_hash="synthetic_hash",
        updated_at="2025-12-01T00:00:00Z",
    )
    sources = {o.provenance.evidence_id: o for o in observations}
    documents = [
        EvidenceDocument(
            manifest=EvidenceFile(
                file_id=o.provenance.evidence_id,
                file_path=o.provenance.file_path,
                origin=o.provenance.origin,
                captured_at=o.provenance.captured_at,
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


def decision(rules, *observations, **kwargs):
    return predict(dataset(rules, *observations, **kwargs)).cases[0]


def operations(result, phase=None):
    assert result.prediction is not None, result.blockers
    return [s.operation for s in result.prediction.steps if phase is None or s.phase == phase]


def absent(**kwargs):
    return observation(result="NOT_FOUND", observed_at=EARLY, **kwargs)
