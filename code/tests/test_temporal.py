"""Constructed temporal cases use the same parsed structures as participant files."""

import json
from pathlib import Path
from random import Random

import pytest

from ghost_audit.extraction import ExtractionContext, parse_json, parse_text
from ghost_audit.index import EvidenceIndex
from ghost_audit.ingestion import load_dataset
from ghost_audit.models import EvidenceFile, ResourceRef
from ghost_audit.phase2 import Phase2Analyzer
from ghost_audit.phase2_models import (
    AssociatedObservation, CaseEvidenceBundle, CorrelationLink, IntentResult,
    ObservationLink, ResolvedIdentity,
)
from ghost_audit.phase3 import diagnostics
from ghost_audit.sql import parse_sql
from ghost_audit.temporal import TemporalStateEngine
from ghost_audit.temporal_models import CaseStateBundle

EARLY = '2026-01-01T10:00:00Z'
LATE = '2026-01-02T10:00:00Z'
CUTOFF = '2026-01-03T10:00:00Z'
FUTURE = '2026-01-04T10:00:00Z'


def context(file='a', time=EARLY, suffix='json'):
    return ExtractionContext(EvidenceFile(file_id=file, file_path=f'evidence/{file}.{suffix}',
                                         origin='fixture_service', captured_at=time), 'a' * 64)


def record(file='a', time=EARLY, collection='profiles', **fields):
    return parse_json({'system': 'account_service', 'collection': collection,
                       'captured_at': time, 'records': [
                           {'resource_id': 'resource_x', 'user_id': 'subject_x', **fields}]},
                      context(file, time))[-1]


def readback(file='a', time=EARLY, collection='profiles', event='profile_lookup_completed', **fields):
    return parse_text(f'{time} level=INFO service=account_service event={event} '
                      f'resource_id=resource_x collection={collection} ' +
                      ' '.join(f'{key}={str(value).lower()}' for key, value in fields.items()),
                      context(file, time, 'log'))[0]


def bundle(observations, *, potential=(), cutoff=CUTOFF, intent='DELETE_INTENT'):
    items = [AssociatedObservation(observation=o, association='POTENTIAL' if i in potential else 'CONFIRMED',
               links=[CorrelationLink(method='DIRECT_IDENTIFIER', supporting_observations=[ObservationLink.of(o)])],
               reason='synthetic_grounded_link') for i, o in enumerate(observations)]
    return CaseEvidenceBundle(case_id='synthetic', audit_at=cutoff,
        intent=IntentResult(decision=intent, reason_id='fixture', confidence='HIGH', fallback_recommended=False),
        identity=ResolvedIdentity(status='RESOLVED', user_id='subject_x'), user_id='subject_x', aliases=[],
        observations=items, resources=[], supporting_evidence_ids=sorted({o.provenance.evidence_id for o in observations}),
        deferred_evidence=[], ambiguities=[], limitations=[], unrelated_observation_count=0)


def analyze(*observations, potential=(), cutoff=CUTOFF):
    return TemporalStateEngine(EvidenceIndex(observations)).analyze(bundle(observations, potential=potential, cutoff=cutoff))


def only(result):
    assert len(result.resource_histories) == 1
    return result.resource_histories[0]


def test_present_record_with_grounded_evidence_and_serializable_result():
    result = analyze(record(email='fictional@example.test'))
    h = only(result)
    assert (h.record.state, h.record.support) == ('PRESENT', 'PROVEN')
    assert h.record.supporting_evidence == [h.observations[0].link]
    assert h.observations[0].association_links
    assert CaseStateBundle.model_validate_json(result.model_dump_json()) == result
    assert 'deletion_status' not in CaseStateBundle.model_fields


def test_deleted_then_recreated_preserves_chronology():
    a = record()
    b = readback('b', LATE, rows=0, http_status=404)
    deleted = only(analyze(a, b))
    assert deleted.record.state == 'ABSENT'
    c = record('c', CUTOFF, email='fictional@example.test')
    h = only(analyze(c, a, b))
    assert h.record.state == 'PRESENT'
    assert [o.record_state for o in h.observations] == ['PRESENT', 'ABSENT', 'PRESENT']


@pytest.mark.parametrize('event_time,capture_time', [(FUTURE, EARLY), (FUTURE, FUTURE)])
def test_future_observation_excluded(event_time, capture_time):
    o = record('future', event_time).model_copy(update={
        'provenance': record('future', event_time).provenance.model_copy(update={
            'captured_at': context(time=capture_time).manifest.captured_at})})
    result = analyze(o)
    assert not result.resource_histories
    assert result.unresolved_states


def test_late_packaged_earlier_observation_is_unavailable():
    # Observed before the cutoff but exported after it: later evidence neither
    # identifies the record nor supplies its state at the cutoff.
    o = record('future', EARLY).model_copy(update={
        'provenance': record('future', EARLY).provenance.model_copy(update={
            'captured_at': context(time=FUTURE).manifest.captured_at})})
    result = analyze(o)
    assert not result.resource_histories
    assert {u.reason for u in result.unresolved_states} >= {'evidence_unavailable_at_audit_cutoff'}


def test_observation_time_differs_from_export_and_updated_time():
    observations = parse_json({'exported_at': CUTOFF, 'snapshots': [
        {'captured_at': EARLY, 'system': 'account_service', 'collection': 'profiles',
         'records': [{'resource_id': 'resource_x', 'updated_at': '2025-01-01T00:00:00Z'}]}]},
        context('snapshot', CUTOFF))
    o = next(o for o in observations if o.resources)
    later = readback('read', LATE, rows=0, http_status=404)
    h = only(analyze(o, later))
    assert h.observations[0].observed_at.isoformat().startswith('2026-01-01T10:00:00')
    assert h.observations[0].available_at.isoformat().startswith('2026-01-03T10:00:00')
    assert h.record.state == 'ABSENT'


def test_success_is_a_claim_and_cannot_override_record():
    claim = readback('claim', LATE, event='delete_completed', reported_result='SUCCESS')
    h = only(analyze(record(), claim))
    assert (h.record.state, h.record.support) == ('PRESENT', 'PROVEN')
    assert h.record.conflicting_evidence == [ObservationLink.of(claim)]
    assert h.observations[-1].support == 'CLAIM_ONLY'
    claim = claim.model_copy(update={'kind': 'activity_claim'})
    h = only(analyze(claim))
    assert (h.record.state, h.record.support) == ('UNKNOWN', 'CLAIM_ONLY')


@pytest.mark.parametrize('fields', [{'rows': 0}, {'http_status': 404}, {'rows': 0, 'http_status': 404},
                                  {'rows': 0, 'http_status': 200}])
def test_explicit_negative_resource_readback(fields):
    h = only(analyze(readback(**fields)))
    assert (h.record.state, h.record.support) == ('ABSENT', 'PROVEN')


@pytest.mark.parametrize('fields', [{'result': 'miss'}, {'total_hits': 0}, {'rows': 0}])
def test_unscoped_search_miss_cannot_establish_absence(fields):
    h = only(analyze(readback(event='index_query_completed', **fields)))
    assert h.record.state == 'UNKNOWN'


def test_exact_resource_scoped_search_negative_and_hit():
    assert only(analyze(readback(event='index_query_completed', total_hits=0,
                                query_resource_id='resource_x'))).record.state == 'ABSENT'
    assert only(analyze(readback(event='index_query_completed', result='hit'))).record.state == 'PRESENT'


def test_cache_miss_and_failed_lookup_do_not_prove_absence():
    assert only(analyze(readback(event='cache_lookup', result='miss'))).record.state == 'UNKNOWN'
    assert only(analyze(readback(event='delete_completed', result='SUCCESS'))).record.state == 'UNKNOWN'


def sql_observations(replica='read_replica', *, empty_primary=False, collection=None):
    if collection:
        schema = 'resource_id TEXT, origin_system TEXT, collection_name TEXT, record_json TEXT'
        row = "'resource_x', 'account_service', 'profiles', '{\"user_id\":\"subject_x\",\"email\":null}'"
        base = 'customer_data'
    else:
        schema = 'resource_id TEXT, user_id TEXT, email TEXT'
        row = "'resource_x', 'subject_x', 'fictional@example.test'"
        base = 'customer_profiles'
    return parse_sql(f'-- Captured at: {EARLY}\n'
        f'CREATE TABLE {base}_primary ({schema});\n'
        + ('' if empty_primary else f'INSERT INTO {base}_primary VALUES ({row});\n')
        + f'CREATE TABLE {base}_{replica} ({schema});\n'
          f'INSERT INTO {base}_{replica} VALUES ({row});', context('sql', EARLY, 'sql'))


@pytest.mark.parametrize('replica', ['read_replica', 'regional_replica', 'reporting_replica', 'failover_replica'])
def test_sql_replica_tables_preserve_physical_and_logical_identity(replica):
    observations = [o for o in sql_observations(replica) if o.resources]
    result = analyze(*observations)
    assert len(result.resource_histories) == 2
    assert {h.scope.replica_scope for h in result.resource_histories} == {'primary', replica}
    assert {h.scope.collection for h in result.resource_histories} == {'customer_profiles'}
    assert {o.physical_table for h in result.resource_histories for o in h.observations} == {
        'customer_profiles_primary', 'customer_profiles_' + replica}
    assert not result.replica_drift


def test_explicit_logical_collection_across_generic_replica_tables():
    result = analyze(*(o for o in sql_observations(collection='profiles') if o.resources))
    assert {h.scope.collection for h in result.resource_histories} == {'profiles'}


def test_missing_row_in_incomplete_sql_snapshot_remains_unknown():
    observations = sql_observations('failover_replica', empty_primary=True)
    index = EvidenceIndex(observations)
    result = TemporalStateEngine(index).analyze(bundle([o for o in observations if o.resources]))
    primary = next(h for h in result.resource_histories if h.scope.replica_scope == 'primary')
    assert (primary.record.state, primary.record.support) == ('UNKNOWN', 'UNKNOWN')
    assert primary.observations[0].category == 'SNAPSHOT_GAP'
    assert [d.kind for d in result.replica_drift] == ['COVERAGE_GAP']


@pytest.mark.parametrize('replica', ['read_replica', 'failover_replica'])
def test_primary_and_replica_disagreement(replica):
    a = readback(rows=0, replica_scope='primary')
    b = readback('b', rows=1, replica_scope=replica)
    result = analyze(a, b)
    assert len(result.resource_histories) == 2
    drift, = result.replica_drift
    assert drift.kind == 'STATE_DISAGREEMENT' and drift.contemporaneous
    assert len(drift.evidence) == 2


def test_replica_field_drift_and_temporal_skew():
    a = record(replica_scope='primary', email=None)
    b = record('b', LATE, replica_scope='regional_replica', email='fictional@example.test')
    result = analyze(a, b)
    assert result.replica_drift[0].kind == 'FIELD_DISAGREEMENT'
    assert not result.replica_drift[0].contemporaneous


def test_same_resource_id_in_different_collections_cannot_join():
    result = analyze(record(collection='profiles'), readback('b', collection='contacts', rows=0))
    assert len(result.resource_histories) == 2
    assert {h.record.state for h in result.resource_histories} == {'PRESENT', 'ABSENT'}
    assert not result.replica_drift


def test_partial_redaction_tombstone_preserves_stable_reference():
    h = only(analyze(record(account_status='ACCOUNT_TOMBSTONE', user_id='subject_x',
                            full_name=None, email=None, phone=None, email_hash=None)))
    assert h.record.state == 'PRESENT'
    fact = h.observations[0]
    assert fact.record_type == 'ACCOUNT_TOMBSTONE'
    assert next(f for f in fact.fields if f.path == 'user_id').representation == 'VALUE'
    assert all(f.representation == 'NULL' for f in fact.fields if f.role == 'DIRECT_IDENTIFIER')


@pytest.mark.parametrize('email', [None, 'fictional@example.test'])
def test_analytics_nulls_and_pii_are_field_facts_not_anonymization(email):
    h = only(analyze(record(collection='analytics_reports', user_id=None, email=email,
                            phone=None, email_hash=None, metrics={'sessions': 3})))
    assert h.record.state == 'PRESENT'
    assert next(f for f in h.observations[0].fields if f.path == 'email').representation == (
        'NULL' if email is None else 'VALUE')


def test_explicit_anonymized_and_redacted_readbacks():
    for state in ('ANONYMIZED', 'REDACTED'):
        o = parse_json({'recorded_at': EARLY, 'system': 'analytics_platform', 'resource_id': 'resource_x',
                        'collection': 'analytics_reports', 'record_type': 'ANALYTICS_PROFILE',
                        'result': state}, context())[0]
        assert only(analyze(o)).record.state == state


def test_false_anonymized_label_preserves_field_contradiction():
    o = record(observed_state='ANONYMIZED', email='fictional@example.test')
    h = only(analyze(o))
    assert h.record.state == 'UNKNOWN' and h.record.support == 'CONFLICTED'
    assert h.observations[0].conflicts


def test_security_retained_reference_is_observed_not_classified():
    h = only(analyze(record(collection='security_audit_events', subject_reference='subject_x',
                            event_name='account_deletion_reviewed', retention_until='2031-01-01T00:00:00Z')))
    assert (h.record.state, h.record.support) == ('PRESENT', 'PROVEN')
    assert h.observations[0].fields[0].role == 'STABLE_REFERENCE'
    assert not h.observations[0].conflicts


@pytest.mark.parametrize('enabled,expected', [(True, 'ACTIVE'), (False, 'INACTIVE')])
def test_connector_state_independent_of_account_deletion(enabled, expected):
    a = readback(rows=0)
    b = readback('connector', LATE, collection='connectors', event='connector_config_read_completed', enabled=enabled)
    result = analyze(a, b)
    connector = next(h for h in result.resource_histories if h.scope.collection == 'connectors')
    assert (connector.flow.state, connector.flow.support) == (expected, 'PROVEN')
    assert next(h for h in result.resource_histories if h.scope.collection == 'profiles').record.state == 'ABSENT'


@pytest.mark.parametrize('allowed,expected', [(True, 'ALLOWED'), (False, 'BLOCKED')])
def test_existing_backup_and_restore_permission_separate(allowed, expected):
    h = only(analyze(record(collection='backups', archive_path='fictional/archive.tar', restore_allowed=allowed)))
    assert h.record.state == 'PRESENT'
    assert (h.restore.state, h.restore.support) == (expected, 'PROVEN')


def test_restore_authorization_does_not_establish_archive_existence():
    h = only(analyze(readback(event='restore_authorization_completed', decision='deny')))
    assert h.record.state == 'UNKNOWN'
    assert h.restore.state == 'BLOCKED'


def test_same_time_conflicts_not_broken_by_evidence_id():
    a = record()
    b = readback('b', rows=0)
    result = analyze(a, b)
    h = only(result)
    assert (h.record.state, h.record.support) == ('UNKNOWN', 'CONFLICTED')
    assert len(h.record.conflicting_evidence) == 2


def test_potential_association_never_establishes_definitive_state():
    a = record()
    h = only(analyze(a, potential=(0,)))
    assert h.observations[0].record_state == 'PRESENT'
    assert h.observations[0].support == 'UNKNOWN'
    assert (h.record.state, h.record.support) == ('UNKNOWN', 'UNKNOWN')
    # Potential contradictory content must not weaken the independently grounded fact.
    h = only(analyze(a, readback('b', LATE, rows=0), potential=(1,)))
    assert h.record.state == 'PRESENT'
    assert not h.record.conflicting_evidence


def test_missing_or_future_correlation_anchor_cannot_prove_ownership():
    a, future = record(), record('future', FUTURE)
    b = bundle([a])
    link = b.observations[0].links[0].model_copy(update={'supporting_observations': [ObservationLink.of(future)]})
    item = b.observations[0].model_copy(update={'links': [link]})
    b = b.model_copy(update={'observations': [item]})
    result = TemporalStateEngine(EvidenceIndex([a, future])).analyze(b)
    assert only(result).record.state == 'UNKNOWN'
    assert ObservationLink.of(future) not in result.supporting_evidence


def test_newer_summary_readback_supersedes_older_snapshot():
    # The newest supported read decides; the older snapshot stays in the history.
    summary = parse_json({'recorded_at': LATE, 'system': 'account_service', 'resource_id': 'resource_x',
                          'collection': 'profiles', 'record_type': 'USER_PROFILE', 'result': 'NOT_FOUND'},
                         context('summary', LATE))[0]
    h = only(analyze(record(), summary))
    assert h.record.state == 'ABSENT'
    assert h.record.supporting_evidence == [ObservationLink.of(summary)]
    assert [o.record_state for o in h.observations] == ['PRESENT', 'ABSENT']


def test_precise_snapshot_outranks_simultaneous_summary_label():
    summary = parse_json({'recorded_at': EARLY, 'system': 'account_service', 'resource_id': 'resource_x',
                          'collection': 'profiles', 'record_type': 'USER_PROFILE', 'result': 'NOT_FOUND'},
                         context('summary', EARLY))[0]
    h = only(analyze(record(), summary))
    assert h.record.state == 'PRESENT'
    assert h.record.conflicting_evidence == [ObservationLink.of(summary)]


@pytest.mark.parametrize('value,expected', [(1, 'ACTIVE'), (0, 'INACTIVE'), ('1', 'ACTIVE'), ('0', 'INACTIVE')])
def test_sql_boolean_representations(value, expected):
    h = only(analyze(record(enabled=value, restore_allowed=value)))
    assert h.flow.state == expected
    assert h.restore.state == ('ALLOWED' if expected == 'ACTIVE' else 'BLOCKED')
    assert h.observations[0].attributes['enabled'] == value


@pytest.mark.parametrize('result,restore', [('ACTIVE', 'ALLOWED'), ('BLOCKED', 'BLOCKED'), ('FOUND', 'UNKNOWN')])
def test_archive_status_label_maps_restore_path(result, restore):
    # An ACTIVE (not BLOCKED) archive remains restorable; FOUND says nothing about restore.
    o = parse_json({'recorded_at': EARLY, 'system': 'backup_service', 'resource_id': 'resource_x',
                    'record_type': 'BACKUP_ARCHIVE', 'result': result}, context())[0]
    h = only(analyze(o))
    assert h.record.state == 'PRESENT'
    assert h.restore.state == restore


def test_unavailable_download_does_not_prove_record_absent():
    h = only(analyze(readback(event='export_download_check_completed', available=False)))
    assert h.record.state == 'UNKNOWN'


@pytest.mark.parametrize('status', [403, 429, 500, 503])
def test_failed_resource_read_is_unknown(status):
    h = only(analyze(readback(rows=0, http_status=status)))
    assert h.record.state == 'UNKNOWN'


def test_same_system_resource_without_collection_shares_one_source_history():
    # One system's resource ID names one record; the newer read of the same surface decides.
    a, b = readback(rows=1), readback('b', LATE, rows=0)
    a = a.model_copy(update={'resources': [ResourceRef(resource_id='resource_x', system_id='account_service')]})
    b = b.model_copy(update={'resources': a.resources, 'provenance': b.provenance.model_copy(
        update={'file_path': a.provenance.file_path, 'locator': 'line:2'})})
    h = only(analyze(a, b))
    assert [o.record_state for o in h.observations] == ['PRESENT', 'ABSENT']
    assert h.record.state == 'ABSENT'


def test_row_without_collection_joins_single_known_collection():
    a = readback(rows=1).model_copy(update={'resources': [
        ResourceRef(resource_id='resource_x', system_id='account_service', collection='profiles')]})
    b = readback('b', LATE, rows=0).model_copy(update={'resources': [
        ResourceRef(resource_id='resource_x', system_id='account_service')]})
    assert {h.scope.collection for h in analyze(a, b).resource_histories} == {'profiles'}


def test_missing_chain_support_and_unknown_system_cannot_be_proven():
    a = record()
    b = bundle([a])
    item = b.observations[0]
    bad_link = item.links[0].model_copy(update={'supporting_observations': []})
    changed = b.model_copy(update={'observations': [item.model_copy(update={'links': [bad_link]})]})
    assert only(TemporalStateEngine().analyze(changed)).record.state == 'UNKNOWN'
    a = a.model_copy(update={'resources': [ResourceRef(resource_id='resource_x', collection='profiles')]})
    assert only(analyze(a)).record.state == 'UNKNOWN'


def test_historical_conflict_survives_later_resolution():
    a, b, c = record(), readback('b', rows=0), readback('c', LATE, rows=1)
    result = analyze(a, b, c)
    h = only(result)
    assert h.record.state == 'PRESENT' and h.record.support == 'PROVEN'
    assert h.conflict_reasons == ['simultaneous_record_observations_disagree']
    assert set(result.conflicting_evidence) == {ObservationLink.of(a), ObservationLink.of(b)}


def test_unspecified_read_sources_are_not_assumed_to_be_the_same_replica():
    a, b = record(), readback('b', LATE, rows=0)
    b = b.model_copy(update={'provenance': b.provenance.model_copy(update={'origin': 'other_replica'})})
    result = analyze(a, b)
    assert len(result.resource_histories) == 2
    assert result.replica_drift[0].kind == 'STATE_DISAGREEMENT'


def test_search_hits_for_another_resource_cannot_prove_target_presence():
    observations = parse_json({'system': 'search_service', 'collection': 'search_docs',
        'resource_id': 'resource_x', 'observed_at': EARLY, 'hits': {'total': 1,
        'documents': [{'resource_id': 'other_resource', 'email': 'fictional@example.test'}]}}, context())
    assert only(analyze(*observations)).record.state == 'UNKNOWN'


def test_restore_conflict_does_not_erase_archive_existence():
    h = only(analyze(record(archive_path='fixture/archive', restore_allowed=True, deletion_block=True)))
    assert h.record.state == 'PRESENT' and h.record.support == 'PROVEN'
    assert h.restore.state == 'UNKNOWN' and h.restore.support == 'CONFLICTED'


def test_same_time_field_conflict_preserved_when_existence_agrees():
    result = analyze(record(email=None), record('b', email='fictional@example.test'))
    h = only(result)
    assert h.record.state == 'PRESENT'
    assert h.conflict_reasons == ['simultaneous_field_observations_disagree']
    assert len(result.conflicting_evidence) == 2


def test_unregistered_evidence_cannot_prove_state():
    from ghost_audit.index import EvidenceRegistry
    a = record()
    result = TemporalStateEngine(EvidenceIndex([a], registry=EvidenceRegistry())).analyze(bundle([a]))
    assert not result.resource_histories


def test_input_order_is_irrelevant():
    observations = [record(), readback('b', LATE, rows=0), record('c', CUTOFF),
                    record('replica', LATE, replica_scope='failover_replica')]
    expected = analyze(*observations).model_dump_json()
    for seed in range(5):
        Random(seed).shuffle(observations)
        assert analyze(*observations).model_dump_json() == expected


def test_non_deletion_intent_does_not_reconstruct_records():
    assert not TemporalStateEngine().analyze(bundle([record()], intent='NO_DELETE_INTENT')).resource_histories


@pytest.fixture(scope='module')
def full_run():
    dataset = load_dataset(Path(__file__).resolve().parents[2] / 'dataset')
    analyzer = Phase2Analyzer(dataset)
    engine = TemporalStateEngine(analyzer.index)
    return dataset, analyzer, engine, [engine.analyze(analyzer.analyze(r)) for r in dataset.requests]


def test_full_dataset_coverage_and_evidence_contract(full_run):
    dataset, analyzer, _, bundles = full_run
    assert len(bundles) == 518
    for result in bundles:
        for h in result.resource_histories:
            assert all(o.observed_at <= result.audit_at for o in h.observations)
            for fact in h.observations:
                assert analyzer.index.registry.get(fact.provenance.evidence_id)
                # A later-packaged fact may identify a record but is never a supported state.
                assert fact.available_at <= result.audit_at or fact.support == 'UNKNOWN'
                if fact.support == 'PROVEN':
                    assert fact.association == 'CONFIRMED' and fact.association_links
                    entry = analyzer.index.registry.get(fact.provenance.evidence_id)
                    assert entry.captured_at <= result.audit_at
            for state in (h.record, h.flow, h.restore):
                if state.support == 'PROVEN':
                    assert state.state != 'UNKNOWN' and state.supporting_evidence
        assert CaseStateBundle.model_validate_json(result.model_dump_json()) == result
    report = diagnostics(bundles)
    assert report['cases'] == len(dataset.requests) == 518
    assert report['resources_with_established_states'] > 0
    assert report['resources_with_unknown_states'] > 0
    assert report['active_data_flows'] > 0 and report['restore_risks'] > 0
    assert sum(report['resource_states'].values()) == report['resource_scopes']
    assert '@' not in json.dumps(report)
    assert 'not measured' in report['prediction_accuracy']


def test_phase3_cli_full_sample_and_single_case(full_run, monkeypatch, capsys):
    import main
    from dataclasses import replace
    from ghost_audit.csvio import load_models
    from ghost_audit.models import DeletionRequest
    dataset, _, _, _ = full_run
    samples = load_models(Path(__file__).resolve().parents[2] / 'dataset/sample_deletion_requests.csv',
                          DeletionRequest, 'case_id')
    monkeypatch.setattr(main, 'load_dataset', lambda *args, **kwargs:
                        replace(dataset, requests=samples) if kwargs.get('samples') else dataset)
    assert main.main(['phase3']) == 0
    assert json.loads(capsys.readouterr().out)['cases'] == 518
    assert main.main(['phase3', '--samples']) == 0
    assert json.loads(capsys.readouterr().out)['cases'] == 32
    assert main.main(['phase3', '--case-id', dataset.requests[0].case_id]) == 0
    assert json.loads(capsys.readouterr().out)['case_id'] == dataset.requests[0].case_id
    with pytest.raises(SystemExit):
        main.main(['phase3', '--case-id', 'missing'])
