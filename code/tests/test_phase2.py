import json
from pathlib import Path

import pytest

from ghost_audit.infrastructure.serialization.csv_records import load_models
from ghost_audit.infrastructure.ingestion.dataset_loader import load_dataset
from ghost_audit.domain.models import DeletionRequest, EvidenceDocument, EvidenceFile
from ghost_audit.application.evidence_association import EvidenceAssociationService, diagnostics
from ghost_audit.domain.association_models import CaseEvidenceBundle
from ghost_audit.domain.observation_clocks import linkage_time


@pytest.fixture(scope='module')
def analyzed():
    dataset = load_dataset(Path(__file__).resolve().parents[2] / 'dataset')
    analyzer = EvidenceAssociationService(dataset)
    bundles = [analyzer.analyze(r) for r in dataset.requests]
    return analyzer, bundles


def test_full_dataset_finishes_and_contract_is_ready_for_phase3(analyzed):
    analyzer, bundles = analyzed
    assert len(bundles) == 518
    assert {b.case_id for b in bundles} == {r.case_id for r in analyzer.dataset.requests}
    for bundle in bundles:
        assert bundle.identity.status in {'RESOLVED', 'AMBIGUOUS', 'UNRESOLVED'}
        assert 'deletion_status' not in type(bundle).model_fields
        assert all(a.event_time <= bundle.audit_at for a in bundle.aliases)
        # Ownership facts count from their own observation time; a later export of an
        # earlier snapshot can link but never be cited (Phase 3 marks it linkage-only).
        assert all(linkage_time(o.observation) <= bundle.audit_at for o in bundle.observations)
        for item in bundle.observations:
            assert item.links
            assert all(link.supporting_observations for link in item.links)
            for link in item.links:
                assert all(any(o.observation.provenance.evidence_id == ref.evidence_id
                               and o.observation.provenance.locator == ref.locator
                               and o.observation.provenance.file_path == ref.file_path
                               for o in bundle.observations)
                           for ref in link.supporting_observations)
        locators = [(o.observation.provenance.evidence_id, o.observation.provenance.locator)
                    for o in bundle.observations]
        assert len(locators) == len(set(locators))


def test_aggregate_is_an_association_report_without_raw_pii(analyzed):
    analyzer, bundles = analyzed
    report = diagnostics(bundles)
    assert report['cases'] == 518
    assert sum(report['intent'].values()) == sum(report['identity'].values()) == 518
    assert report['cases_with_confirmed_associations'] > 0
    assert report['distinct_resources'] > 0
    # Images stay deferred only when OCR is unavailable or yields no catalogued resource.
    deferred = sum(d.status == 'deferred' for d in analyzer.dataset.documents)
    assert report['deferred_files_available'] == deferred <= 11
    assert report['deferred_files_confirmed_by_content'] == 0
    assert '@' not in json.dumps(report)
    assert 'not measured' in report['prediction_accuracy']


def test_sample_requests_use_same_services_without_reference_lookup(analyzed, monkeypatch):
    analyzer, _ = analyzed
    requests = load_models(Path(__file__).resolve().parents[2] / 'dataset/sample_deletion_requests.csv',
                           DeletionRequest, 'case_id')
    def forbidden(*args, **kwargs):
        raise AssertionError('analysis reopened a file')
    monkeypatch.setattr(Path, 'open', forbidden)
    bundles = [analyzer.analyze(r) for r in requests]
    assert len(bundles) == 32
    assert all(b.user_id for b in bundles)
    assert all(b.intent.decision == 'DELETE_INTENT' for b in bundles)
    assert diagnostics(bundles)['cases'] == 32


def test_bundles_are_deterministic_serializable_and_query_unrelated(analyzed):
    analyzer, bundles = analyzed
    first = bundles[0]
    again = analyzer.analyze(analyzer.dataset.requests[0])
    assert first.model_dump_json() == again.model_dump_json()
    assert CaseEvidenceBundle.model_validate_json(first.model_dump_json()) == first
    unrelated = next(o for o in analyzer.index.observations
                     if not any(a.observation == o for a in first.observations))
    assert analyzer.association_for(first, unrelated).association == 'UNRELATED'
    if first.observations:
        assert analyzer.association_for(first, first.observations[0].observation) == first.observations[0]


def test_deferred_pool_is_time_filtered_unassigned_and_provenance_preserved(analyzed):
    analyzer, bundles = analyzed
    for bundle in bundles:
        for entry in bundle.deferred_evidence:
            assert entry.captured_at <= bundle.audit_at
            assert entry.parsing_status == 'deferred'
            assert entry == analyzer.index.registry.get(entry.evidence_id)
        assert all(o.observation.provenance.evidence_id not in {e.evidence_id for e in bundle.deferred_evidence}
                   for o in bundle.observations)


def test_phase2_cli_aggregate_and_single_case(analyzed, monkeypatch, capsys):
    from ghost_audit.interfaces import cli as main
    analyzer, _ = analyzed
    monkeypatch.setattr(main, 'load_dataset', lambda *args, **kwargs: analyzer.dataset)
    assert main.main(['phase2']) == 0
    assert json.loads(capsys.readouterr().out)['cases'] == 518
    # A one-case diagnostic is intentionally detailed; aggregate diagnostics above
    # contain only case IDs, counts, and distributions.
    assert main.main(['phase2', '--case-id', analyzer.dataset.requests[0].case_id]) == 0
    raw = json.loads(capsys.readouterr().out)
    assert raw['case_id'] == analyzer.dataset.requests[0].case_id
    assert raw['identity']['status'] == 'RESOLVED'
    with pytest.raises(SystemExit):
        main.main(['phase2', '--case-id', 'not_a_case'])


def test_synthetic_future_deferred_file_is_not_offered(analyzed):
    from dataclasses import replace
    analyzer, _ = analyzed
    future = EvidenceDocument(
        manifest=EvidenceFile(file_id='future_image', file_path='evidence/images/future.png',
                              origin='screen', captured_at='2030-01-01T00:00:00Z'),
        sha256='a' * 64, status='deferred', observations=[],
    )
    dataset = replace(analyzer.dataset, documents=[*analyzer.dataset.documents, future])
    bundle = EvidenceAssociationService(dataset).analyze(dataset.requests[0])
    assert 'future_image' not in {e.evidence_id for e in bundle.deferred_evidence}
