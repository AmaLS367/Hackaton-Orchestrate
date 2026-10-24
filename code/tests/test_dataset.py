from collections import Counter
from pathlib import Path

import pytest

from ghost_audit.csvio import load_models
from ghost_audit.index import EvidenceIndex
from ghost_audit.ingestion import load_dataset
from ghost_audit.models import DeletionRequest
from ghost_audit.output import read_output, validate_output


@pytest.fixture(scope="module")
def loaded_dataset():
    root = Path(__file__).resolve().parents[2]
    return load_dataset(root / "dataset")


def test_all_participant_formats_ingest_and_images_are_deferred(loaded_dataset):
    dataset = loaded_dataset
    assert len(dataset.requests) == 518
    assert len(dataset.documents) == 94
    assert len({doc.manifest.file_id for doc in dataset.documents}) == 94
    assert Counter(Path(doc.manifest.file_path).suffix for doc in dataset.documents) == {
        '.json': 28, '.sql': 24, '.log': 26, '.pdf': 4, '.png': 11, '.txt': 1,
    }
    assert all(doc.status == "deferred" for doc in dataset.documents
               if doc.manifest.file_path.endswith('.png'))
    assert all(doc.observations for doc in dataset.documents if doc.status == "parsed")


def test_csv_observations_preserve_ids_and_claim_classification(loaded_dataset):
    dataset = loaded_dataset
    activities = [o for o in dataset.observations if o.kind == "activity_claim"]
    assert len(activities) == len(dataset.activities)
    assert activities[0].provenance.evidence_id == dataset.activities[0].activity_id
    assert activities[0].provenance.captured_at == dataset.activities[0].event_time
    assert activities[0].provenance.file_path == "system_activity.csv"
    assert activities[0].provenance.locator == "row:2"
    changes = [o for o in dataset.observations if o.provenance.file_path == "user_audit_log.csv"]
    assert changes[0].provenance.evidence_id == dataset.identity_changes[0].audit_id


def test_index_queries_do_not_parse_or_read_files_again(loaded_dataset, monkeypatch):
    index = EvidenceIndex(loaded_dataset.observations)

    def forbidden(*args, **kwargs):
        raise AssertionError("index lookup attempted file I/O")

    monkeypatch.setattr(Path, "open", forbidden)
    for request in loaded_dataset.requests:
        index.lookup(identifiers=[request.email], audit_at=request.audit_at, expand_traces=True)


def test_public_sample_output_matches_strict_schema(dataset_path):
    references = read_output(dataset_path / "sample_output.csv")
    requests = load_models(dataset_path / "sample_deletion_requests.csv", DeletionRequest, "case_id")
    assert len(references) == 32
    validate_output(references, requests)


def test_production_loader_never_reads_sample_answers(dataset_path, monkeypatch):
    original = Path.open

    def guarded(self, *args, **kwargs):
        assert self.name not in {"sample_output.csv", "output.csv"}
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    assert len(load_dataset(dataset_path).requests) == 518
