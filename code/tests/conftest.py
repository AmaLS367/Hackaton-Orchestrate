from pathlib import Path

import pytest

from ghost_audit.infrastructure.parsers.structured import ExtractionContext
from ghost_audit.domain.models import EvidenceFile


@pytest.fixture
def dataset_path():
    return Path(__file__).resolve().parents[2] / "dataset"


@pytest.fixture
def context():
    return ExtractionContext(EvidenceFile(
        file_id="fixture_file", file_path="evidence/records/fixture.json",
        origin="fixture_store", captured_at="2026-01-02T12:00:00Z",
    ), "a" * 64)
