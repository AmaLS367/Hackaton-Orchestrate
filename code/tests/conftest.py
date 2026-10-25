from pathlib import Path

import pytest
from ghost_audit.application.strict_audit import predict
from ghost_audit.application.submission_service import predict_submission
from ghost_audit.domain.dataset import Dataset
from ghost_audit.domain.evidence_index import EvidenceIndex
from ghost_audit.domain.models import DeletionRule, EvidenceFile
from ghost_audit.domain.policy_models import PredictionRun
from ghost_audit.domain.submission_models import CasePrediction
from ghost_audit.infrastructure.ingestion.dataset_loader import load_dataset
from ghost_audit.infrastructure.parsers.structured import ExtractionContext
from ghost_audit.infrastructure.serialization.csv_records import load_models

from tests.fixtures.paths import DATASET_ROOT


@pytest.fixture
def dataset_path() -> Path:
    return DATASET_ROOT


@pytest.fixture
def context() -> ExtractionContext:
    return ExtractionContext(
        EvidenceFile.model_validate(
            {
                "file_id": "fixture_file",
                "file_path": "evidence/records/fixture.json",
                "origin": "fixture_store",
                "captured_at": "2026-01-02T12:00:00Z",
            }
        ),
        "a" * 64,
    )


@pytest.fixture(scope="module")
def rules() -> list[DeletionRule]:
    """Fresh policy models per module; synthetic cases never alter participant inputs."""
    return load_models(DATASET_ROOT / "deletion_rules.csv", DeletionRule, "rule_id")


@pytest.fixture(scope="session")
def participant_dataset() -> Dataset:
    return load_dataset(DATASET_ROOT)


@pytest.fixture(scope="session")
def sample_dataset() -> Dataset:
    return load_dataset(DATASET_ROOT, samples=True)


@pytest.fixture(scope="session")
def submission_cases(participant_dataset: Dataset) -> list[CasePrediction]:
    return predict_submission(participant_dataset)


@pytest.fixture(scope="session")
def strict_result(participant_dataset: Dataset) -> tuple[Dataset, EvidenceIndex, PredictionRun]:
    index = EvidenceIndex(participant_dataset.observations, registry=participant_dataset.registry)
    return participant_dataset, index, predict(participant_dataset, index)
