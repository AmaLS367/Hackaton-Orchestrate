"""Synthetic integrations use the real correlation, temporal, policy, and output paths."""

import json
from pathlib import Path
from random import Random

import pytest

from ghost_audit.csvio import load_models
from ghost_audit.extraction import ExtractionContext, parse_json
from ghost_audit.index import EvidenceIndex
from ghost_audit.ingestion import Dataset
from ghost_audit.models import DeletionRequest, DeletionRule, EvidenceDocument, EvidenceFile, Identity, IdentityChange
from ghost_audit.output import OPERATION_ORDER, read_output, validate_output
from ghost_audit.phase2 import Phase2Analyzer
from ghost_audit.planning import plan_case
from ghost_audit.policy import PolicyEvaluator
from ghost_audit.prediction import PredictionBlocked, diagnostics, predict, publish
from ghost_audit.temporal import TemporalStateEngine

EARLY = '2026-01-01T10:00:00Z'
LATE = '2026-01-02T10:00:00Z'
CUTOFF = '2026-01-03T10:00:00Z'
FUTURE = '2026-01-04T10:00:00Z'


@pytest.fixture(scope='module')
def rules():
    return load_models(Path(__file__).resolve().parents[2] / 'dataset/deletion_rules.csv', DeletionRule, 'rule_id')


def observation(resource='arbitrary-key', category='USER_PROFILE', *, file='fixture', at=EARLY,
                system='account_service', collection='customer_profiles', **fields):
    ctx = ExtractionContext(EvidenceFile(file_id=file, file_path=f'evidence/{file}.json',
                            origin=system, captured_at=at), 'b' * 64)
    return parse_json({'captured_at': at, 'system': system, 'collection': collection,
        'records': [{'resource_id': resource, 'user_id': 'subject_x', 'record_type': category, **fields}]}, ctx)[-1]


def dataset(rules, *observations, text='Please delete my account and all personal data.', email='subject@example.test'):
    request = DeletionRequest(case_id='synthetic', email=email, requested_at=EARLY,
        reported_status='COMPLETE', reported_at=EARLY, audit_at=CUTOFF, request_text=text)
    identity = Identity(user_id='subject_x', name='Synthetic Subject', email='subject@example.test',
        phone='+10000000001', email_hash='synthetic_hash', updated_at='2025-12-01T00:00:00Z')
    sources = {o.provenance.evidence_id: o for o in observations}
    documents = [EvidenceDocument(manifest=EvidenceFile(file_id=o.provenance.evidence_id,
        file_path=o.provenance.file_path, origin=o.provenance.origin, captured_at=o.provenance.captured_at),
        sha256=o.provenance.sha256, status='parsed', observations=[
            item for item in observations if item.provenance.evidence_id == o.provenance.evidence_id])
        for o in sources.values()]
    return Dataset([request], [identity], [], [], rules, documents, list(observations))


def decision(rules, *observations, **kwargs):
    return predict(dataset(rules, *observations, **kwargs)).cases[0]


def operations(result, phase=None):
    assert result.prediction is not None, result.blockers
    return [s.operation for s in result.prediction.steps if phase is None or s.phase == phase]


def absent(**kwargs):
    return observation(result='NOT_FOUND', observed_at=EARLY, **kwargs)


def test_fully_completed_deletion(rules):
    result = decision(rules, absent())
    assert result.decision == 'COMPLETE'
    assert operations(result) == ['VERIFY_RECORD_ABSENT']
    assert result.prediction.steps[0].evidence_id == 'fixture'


@pytest.mark.parametrize('category,system,collection', [
    ('USER_PROFILE', 'account_service', 'customer_profiles'),
    ('SECONDARY_IDENTIFIER', 'identity_service', 'secondary_identifiers'),
    ('SEARCH_INDEX_ENTRY', 'search_service', 'customer_search_documents'),
    ('CACHE_ENTRY', 'cache_service', 'cache'),
    ('USER_EXPORT', 'export_service', 'customer_exports'),
    ('MARKETING_PROFILE', 'marketing_service', 'contacts'),
])
def test_delete_categories_and_remaining_search_record(rules, category, system, collection):
    result = decision(rules, observation(category=category, system=system, collection=collection))
    assert result.decision == 'INCOMPLETE'
    assert operations(result) == ['REPORT_REMAINING_RECORD', 'DELETE_RECORD', 'VERIFY_RECORD_ABSENT']


def test_shared_support_message_redacts_instead_of_deleting(rules):
    result = decision(rules, observation(category='SUPPORT_MESSAGE', system='support_platform',
        collection='support_conversations', shared_context=True, email='subject@example.test'))
    assert operations(result) == ['REPORT_EXPOSED_PII', 'REDACT_RECORD', 'VERIFY_RECORD_REDACTED']


def test_subject_only_attachment_and_unknown_condition(rules):
    row = observation(category='SUPPORT_ATTACHMENT', system='support_platform', collection='ticket_attachments',
                      subject_only=True)
    assert 'DELETE_RECORD' in operations(decision(rules, row))
    # Association does not establish exclusive ownership of an attachment.
    unflagged = decision(rules, observation(category='SUPPORT_ATTACHMENT', system='support_platform',
                                            collection='ticket_attachments'))
    assert unflagged.prediction is None
    assert 'policy_condition_unestablished_or_ambiguous' in unflagged.assessments[0].reasons
    shared = observation(category='SUPPORT_ATTACHMENT', system='support_platform', collection='ticket_attachments',
                         subject_only=False)
    result = decision(rules, shared)
    assert result.prediction is None
    assert 'policy_condition_unestablished_or_ambiguous' in result.unresolved


@pytest.mark.parametrize('category', ['ANALYTICS_PROFILE', 'PRODUCT_TELEMETRY'])
def test_attributable_analytics_and_telemetry_anonymized(rules, category):
    result = decision(rules, observation(category=category, system='analytics_platform',
        collection='customer_analytics_profiles' if category == 'ANALYTICS_PROFILE' else 'telemetry',
        email='subject@example.test'))
    assert operations(result) == ['REPORT_EXPOSED_PII', 'ANONYMIZE_RECORD', 'VERIFY_RECORD_ANONYMIZED']


def test_compliant_analytics_requires_sufficient_field_coverage(rules):
    anchor = observation(category='ANALYTICS_PROFILE', system='analytics_platform',
                         collection='customer_analytics_profiles', email='subject@example.test')
    clean = observation(category='ANALYTICS_PROFILE', system='analytics_platform', file='clean', at=LATE,
        collection='customer_analytics_profiles', user_id=None, email=None, phone=None, email_hash=None)
    result = decision(rules, anchor, clean)
    assert result.decision == 'COMPLETE'
    assert operations(result) == ['VERIFY_RECORD_ANONYMIZED']
    assert result.prediction.steps[0].evidence_id == 'clean'
    # Omitted identifier slots cannot be assumed clean.
    partial = observation(category='ANALYTICS_PROFILE', system='analytics_platform', file='clean', at=LATE,
        collection='customer_analytics_profiles', user_id=None, email=None)
    assert decision(rules, anchor, partial).prediction is None
    # Any remaining identifier value keeps it attributable.
    linked = observation(category='ANALYTICS_PROFILE', system='analytics_platform', file='clean', at=LATE,
        collection='customer_analytics_profiles', email=None, phone=None, email_hash=None)
    assert operations(decision(rules, anchor, linked), 'FINDING') == ['REPORT_EXPOSED_PII']
    # A read showing no identifier slot at all proves nothing.
    bare = observation(category='ANALYTICS_PROFILE', system='analytics_platform', file='clean', at=LATE,
        collection='customer_analytics_profiles').model_copy(update={'payload': {'audience_cohort': 'x'}})
    assert decision(rules, anchor, bare).prediction is None


def test_retained_security_user_reference_is_not_a_violation(rules):
    result = decision(rules, absent(resource='baseline', file='baseline'),
        observation(category='SECURITY_AUDIT_LOG', system='security_service',
        collection='security_audit_records', retention_until='2030-01-01T00:00:00Z'))
    assert result.decision == 'COMPLETE'
    assert operations(result) == ['VERIFY_RECORD_ABSENT', 'VERIFY_RECORD_PRESENT']


def test_retention_condition_uses_cutoff_and_missing_deadline_is_unknown(rules):
    for deadline in [None, '2025-01-01T00:00:00Z', CUTOFF]:
        result = decision(rules, observation(category='SECURITY_AUDIT_LOG', system='security_service',
            collection='security_audit_records', retention_until=deadline))
        assert result.prediction is None
        assert not any(a.compliance == 'VIOLATION' for a in result.assessments)


def test_active_legal_hold_preserved_and_inactive_hold_not_deleted(rules):
    for active in (True, False):
        result = decision(rules, absent(resource='baseline', file='baseline'),
            observation(category='LEGAL_HOLD_RECORD', system='legal_service',
            collection='retained_order_records', hold_active=active))
        if active:
            assert operations(result) == ['VERIFY_RECORD_ABSENT', 'VERIFY_RECORD_PRESENT']
        else:
            assert result.prediction is None


def test_email_delivery_redaction(rules):
    result = decision(rules, observation(category='EMAIL_DELIVERY_LOG', system='mail_service',
        collection='deliveries', email='subject@example.test'))
    assert operations(result) == ['REPORT_EXPOSED_PII', 'REDACT_RECORD', 'VERIFY_RECORD_REDACTED']


@pytest.mark.parametrize('email,status', [('subject@example.test', 'INCOMPLETE'), (None, 'COMPLETE')])
def test_account_tombstone_preserves_stable_reference(rules, email, status):
    result = decision(rules, observation(category='ACCOUNT_TOMBSTONE', collection='deleted_customer_references',
        account_status='DELETED', name=None, email=email, phone=None, email_hash=None))
    assert result.decision == status
    assert 'DELETE_RECORD' not in operations(result)
    assert operations(result, 'VERIFICATION') == ['VERIFY_RECORD_REDACTED']


@pytest.mark.parametrize('enabled,status', [(True, 'INCOMPLETE'), (False, 'COMPLETE')])
def test_active_and_disabled_data_flow(rules, enabled, status):
    result = decision(rules, absent(resource='baseline', file='baseline'),
        observation(category='DATA_FLOW', system='integration_service',
        collection='connector_configurations', enabled=enabled))
    assert result.decision == status
    assert operations(result, 'VERIFICATION') == ['VERIFY_RECORD_ABSENT', 'VERIFY_DATA_FLOW_DISABLED']
    assert ('DISABLE_DATA_FLOW' in operations(result)) == enabled


@pytest.mark.parametrize('allowed,status', [(True, 'INCOMPLETE'), (False, 'COMPLETE')])
def test_backup_retained_and_restore_blocked(rules, allowed, status):
    result = decision(rules, absent(resource='baseline', file='baseline'),
        observation(category='BACKUP_ARCHIVE', system='backup_service',
        collection='backup_catalog', restore_allowed=allowed, archive_present=True))
    assert result.decision == status
    assert 'DELETE_RECORD' not in operations(result)
    # The archive itself is retained (rule 14); its obligation is the restore path only.
    assert operations(result, 'VERIFICATION') == ['VERIFY_RECORD_ABSENT', 'VERIFY_RESTORE_BLOCKED']
    assert ('BLOCK_RESTORE' in operations(result)) == allowed


def test_replica_survival_proves_violation_but_findings_deduplicate(rules):
    primary = absent(replica_scope='primary')
    replica = observation(file='survivor', replica_scope='read_replica')
    replica2 = observation(file='survivor2', replica_scope='failover_replica')
    result = decision(rules, primary, replica, replica2)
    assert result.decision == 'INCOMPLETE'
    assert len(result.prediction.steps) == 3
    assert result.prediction.steps[0].evidence_id == 'survivor'


def test_conflicting_same_replica_observations_abstain(rules):
    result = decision(rules, absent(), observation(file='contradiction', result='FOUND', observed_at=EARLY))
    assert result.prediction is None
    assert not any(a.compliance == 'VIOLATION' for a in result.assessments)


def test_unknown_and_successful_delete_claim_cannot_prove_absence(rules):
    row = observation(event='delete_completed', reported_result='SUCCESS')
    result = decision(rules, row)
    assert result.prediction is None
    assert not any(a.compliance == 'VIOLATION' for a in result.assessments)


def test_potential_association_cannot_establish_compliance_or_violation(rules):
    d = dataset(rules, observation())
    analyzer = Phase2Analyzer(d)
    b = analyzer.analyze(d.requests[0])
    b = b.model_copy(update={'observations': [o.model_copy(update={'association': 'POTENTIAL'}) for o in b.observations]})
    state = TemporalStateEngine(analyzer.index).analyze(b)
    result = plan_case(state, PolicyEvaluator(rules).evaluate(state))
    assert result.prediction is None
    assert not any(a.compliance != 'UNKNOWN' for a in result.assessments)


def test_negative_and_uncertain_intent_never_remediate(rules):
    negative = decision(rules, observation(), text='Please export a copy of my account data.')
    assert negative.decision == 'NOT_APPLICABLE' and negative.prediction.steps == []
    uncertain = decision(rules, observation(), text='Perhaps something about my account.')
    assert uncertain.prediction is None
    assert 'unresolved_deletion_authorization' in uncertain.blockers


def test_historical_email_and_multiple_resources(rules):
    d = dataset(rules, observation(), observation(resource='another-key', file='search', category='SEARCH_INDEX_ENTRY',
        system='search_service', collection='customer_search_documents'), email='old@example.test')
    d.identity_changes.append(IdentityChange(audit_id='change_x', user_id='subject_x', event_time=EARLY,
        field_name='email', old_value='old@example.test', new_value='subject@example.test'))
    result = predict(d).cases[0]
    assert result.decision == 'INCOMPLETE'
    assert len(operations(result, 'FINDING')) == 2


def test_known_violation_despite_unknown_state(rules):
    result = decision(rules, observation(), observation(resource='other', file='claim',
        event='delete_completed', reported_result='SUCCESS'))
    assert result.decision == 'INCOMPLETE' and result.unresolved
    # The claim-only record is never reported or remediated, only checked afterwards.
    assert all(s.resource_id == 'arbitrary-key' for s in result.prediction.steps if s.phase != 'VERIFICATION')
    assert [(s.operation, s.evidence_id) for s in result.prediction.steps if s.resource_id == 'other'] == [
        ('VERIFY_RECORD_ABSENT', '')]


def test_plan_disables_flow_and_restore_before_cleanup_and_keeps_retained_checks(rules):
    result = decision(rules, observation(),
        observation('flow', 'DATA_FLOW', system='integration_service', collection='connector_configurations',
                    file='flow', enabled=True),
        observation('archive', 'BACKUP_ARCHIVE', system='backup_service', collection='backup_catalog',
                    file='archive', restore_allowed=True),
        observation('audit', 'SECURITY_AUDIT_LOG', system='security_service', collection='security_audit_records',
                    file='audit', retention_until=FUTURE))
    assert operations(result, 'REMEDIATION') == ['DISABLE_DATA_FLOW', 'BLOCK_RESTORE', 'DELETE_RECORD']
    assert operations(result, 'VERIFICATION') == ['VERIFY_RECORD_ABSENT', 'VERIFY_RECORD_PRESENT',
                                                 'VERIFY_DATA_FLOW_DISABLED', 'VERIFY_RESTORE_BLOCKED']
    assert all(s.evidence_id == '' for s in result.prediction.steps if s.phase != 'FINDING')


def test_exact_canonical_order_and_consecutive_numbers(rules):
    rows = [observation(resource='z-resource'), observation(resource='a-resource', file='second'),
            observation('flow', 'DATA_FLOW', file='flow', system='integration_service',
                        collection='connector_configurations', enabled=True)]
    result = decision(rules, *reversed(rows))
    steps = result.prediction.steps
    assert [s.step_no for s in steps] == list(range(1, len(steps) + 1))
    assert [(OPERATION_ORDER[s.operation], s.system_id, s.resource_id) for s in steps] == sorted(
            (OPERATION_ORDER[s.operation], s.system_id, s.resource_id) for s in steps)


def test_explicit_downstream_dependency_and_unrepresentable_order(rules):
    source = observation('z-source')
    downstream = observation('a-downstream', file='copy', source_resource_id='z-source',
                             source_system_id='account_service')
    assert operations(decision(rules, source, downstream), 'REMEDIATION') == ['DELETE_RECORD', 'DELETE_RECORD']
    source = observation('a-source')
    downstream = observation('z-downstream', file='copy', source_resource_id='a-source',
                             source_system_id='account_service')
    result = decision(rules, source, downstream)
    # An unrepresentable dependency cannot be published as a safe ordered plan.
    assert result.prediction is None
    assert any('cleanup_dependency_conflicts_with_official_order' in u for u in result.blockers)


def test_cleanup_dependency_without_system_uses_only_unambiguous_planned_resource(rules):
    result = decision(rules, observation('a-source'), observation('z-downstream', file='copy',
                      source_resource_id='a-source'))
    assert result.prediction is None
    assert any('cleanup_dependency_conflicts_with_official_order' in u for u in result.blockers)


def test_valid_evidence_cutoff_and_no_future_state_override(rules):
    row = observation()
    future = absent(file='late', at=FUTURE)
    d = dataset(rules, row, future)
    run = predict(d)
    index = EvidenceIndex(d.observations, registry=d.registry)
    checks = validate_output(run.predictions, d.requests, index)
    assert checks and all(c.resource_support == 'linked' for c in checks)
    assert run.cases[0].decision == 'INCOMPLETE'
    assert {s.evidence_id for s in run.predictions[0].steps} == {'fixture', ''}


def test_all_518_rows_serialize_and_validate_when_grounded(rules, tmp_path):
    d = dataset(rules, observation())
    request = d.requests[0]
    d.requests = [request.model_copy(update={'case_id': f'custom_{i:03}'}) for i in range(518)]
    run = predict(d)
    path = tmp_path / 'output.csv'
    publish(path, run, d, EvidenceIndex(d.observations, registry=d.registry))
    rows = read_output(path)
    assert len(rows) == 518
    validate_output(rows, d.requests, EvidenceIndex(d.observations, registry=d.registry))
    assert path.read_text(encoding='utf-8').count('\n') == 519


def test_blocked_publish_preserves_existing_file_and_creates_no_placeholder(rules, tmp_path):
    d = dataset(rules)
    run = predict(d)
    path = tmp_path / 'output.csv'
    with pytest.raises(PredictionBlocked):
        publish(path, run, d, EvidenceIndex(d.observations, registry=d.registry))
    assert not path.exists()
    path.write_text('previous output', encoding='utf-8')
    with pytest.raises(PredictionBlocked):
        publish(path, run, d, EvidenceIndex(d.observations, registry=d.registry))
    assert path.read_text(encoding='utf-8') == 'previous output'


def test_input_order_independence(rules):
    rows = [observation(), observation(resource='search', file='search', category='SEARCH_INDEX_ENTRY',
            system='search_service', collection='customer_search_documents')]
    original = decision(rules, *rows)
    for seed in range(3):
        Random(seed).shuffle(rows)
        assert decision(rules, *rows) == original


def test_schema_mapping_never_uses_resource_prefixes(rules):
    mapped = observation(resource='not-an-account-prefix').model_copy(update={
        'payload': {'user_id': 'subject_x', 'email': 'subject@example.test'}})
    assert 'DELETE_RECORD' in operations(decision(rules, mapped))
    # A resource-ID prefix never types a record: an unmapped system stays unknown.
    unknown = observation(resource='account_123', category='UNRECOGNIZED', system='unmapped_store',
                          collection='unknown')
    assert decision(rules, unknown).prediction is None


def test_rules_are_data_driven_and_unknown_conditions_abstain(rules):
    changed = [r.model_copy(update={'condition': 'Undocumented condition'}) if r.data_category == 'USER_PROFILE'
               else r for r in rules]
    assert decision(changed, observation()).prediction is None
    changed = [r.model_copy(update={'required_action': 'ANONYMIZE'}) if r.data_category == 'USER_PROFILE'
               else r for r in rules]
    assert 'ANONYMIZE_RECORD' in operations(decision(changed, observation()))


def test_unassigned_deferred_pool_does_not_block_otherwise_complete_case(rules):
    d = dataset(rules, absent())
    analyzer = Phase2Analyzer(d)
    state = TemporalStateEngine(analyzer.index).analyze(analyzer.analyze(d.requests[0]))
    from ghost_audit.temporal_models import UnresolvedState
    state = state.model_copy(update={'unresolved_states': [UnresolvedState(
        reason='unassigned_deferred_evidence_requires_interpretation')]})
    assert plan_case(state, PolicyEvaluator(rules).evaluate(state)).decision == 'COMPLETE'


def test_default_and_strict_cli_block_without_writing_and_preserve_inspect(rules, tmp_path, monkeypatch, capsys):
    import main
    d = dataset(rules)
    monkeypatch.setattr(main, 'load_dataset', lambda *a, **k: d)
    out = tmp_path / 'output.csv'
    diagnostic = tmp_path / 'diagnostics.json'
    # The strict engine abstains; the submission pathway has no evidence to cite either,
    # so neither writes a partial or fabricated submission.
    assert main.main(['--strict', '--predictions', str(out), '--diagnostics', str(diagnostic)]) == 2
    assert json.loads(capsys.readouterr().out)['output_written'] is False
    assert json.loads(diagnostic.read_text(encoding='utf-8'))['summary']['cases_processed'] == 1
    assert main.main(['--predictions', str(out), '--diagnostics', str(diagnostic)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report['output_written'] is False and 'synthetic' in report['error']
    assert not out.exists()
    assert main.main(['inspect']) == 0
    assert json.loads(capsys.readouterr().out)['requests'] == 1


def test_complete_cli_publishes_and_validates(rules, tmp_path, monkeypatch, capsys):
    import main
    d = dataset(rules, absent())
    monkeypatch.setattr(main, 'load_dataset', lambda *a, **k: d)
    out = tmp_path / 'predictions.csv'
    assert main.main(['predict', '--samples', '--predictions', str(out),
                      '--diagnostics', str(tmp_path / 'diagnostics.json')]) == 0
    assert json.loads(capsys.readouterr().out)['output_written'] is True
    assert read_output(out)[0].deletion_status == 'COMPLETE'


def test_diagnostics_are_counts_and_abstentions_not_a_fourth_submission_label(rules):
    report = diagnostics(predict(dataset(rules)))
    assert report['status_counts'] == {'COMPLETE': 0, 'INCOMPLETE': 0, 'NOT_APPLICABLE': 0}
    assert report['undecidable_count'] == 1
    assert report['runtime_model_usage']['calls'] == report['runtime_model_usage']['total_tokens'] == 0


def test_shared_context_obligation_survives_later_field_redaction(rules):
    old = observation(category='SUPPORT_MESSAGE', system='support_platform', collection='support_records',
                      shared_context=True, email='subject@example.test')
    clean = observation(category='SUPPORT_MESSAGE', system='support_platform', collection='support_records',
                        file='clean', at=LATE, email=None, phone=None, email_hash=None)
    result = decision(rules, old, clean)
    assert result.decision == 'COMPLETE'
    assessment = result.assessments[0]
    assert {link.evidence_id for link in assessment.condition_evidence} == {'fixture'}
    assert result.prediction.steps[0].evidence_id == 'clean'


def test_simultaneous_identifier_disagreement_does_not_create_a_pii_finding(rules):
    a = observation(category='SUPPORT_MESSAGE', system='support_platform', collection='support_records',
                    shared_context=True, email=None, phone=None, email_hash=None)
    b = observation(category='SUPPORT_MESSAGE', system='support_platform', collection='support_records',
                    file='disagree', shared_context=True, email='subject@example.test', phone=None, email_hash=None)
    result = decision(rules, a, b)
    assert result.prediction is None
    assert not any(a.compliance == 'VIOLATION' for a in result.assessments)


def test_extra_linkable_identifier_prevents_null_only_analytics_compliance(rules):
    row = observation(category='ANALYTICS_PROFILE', system='analytics_platform',
        collection='customer_analytics_profiles', email=None, phone=None, email_hash=None,
        device_id='linkable_device', user_id='subject_x')
    assert 'ANONYMIZE_RECORD' in operations(decision(rules, row))


def test_released_legal_hold_is_not_reactivated_by_future_deadline(rules):
    row = observation(category='LEGAL_HOLD_RECORD', system='legal_service', collection='retained_order_records',
                      hold_active=False, retained_until=FUTURE)
    assert decision(rules, row).prediction is None


def test_identity_service_tombstone_schema(rules):
    row = observation(category='ACCOUNT_TOMBSTONE', system='identity_service', collection='deleted_customer_references',
                      account_status='DELETED', email='subject@example.test')
    assert operations(decision(rules, row), 'REMEDIATION') == ['REDACT_RECORD']


def test_profile_transition_to_explicit_tombstone_changes_treatment(rules):
    profile = observation(email='subject@example.test')
    tombstone = observation(category='ACCOUNT_TOMBSTONE', file='tombstone', at=LATE,
                           account_status='DELETED', email='subject@example.test')
    result = decision(rules, profile, tombstone)
    assert operations(result, 'REMEDIATION') == ['REDACT_RECORD']


def test_event_contact_with_marketing_preferences_uses_delete_rule(rules):
    row = observation(category='UNSPECIFIED', system='analytics_platform', collection=None,
                      event='contact_lookup_completed', rows=1, email_opt_in=False)
    assert operations(decision(rules, row), 'REMEDIATION') == ['DELETE_RECORD']


def test_service_export_schema_names_classify_without_inventing_collection_links(rules):
    ctx = ExtractionContext(EvidenceFile(file_id='export', file_path='evidence/export.json',
        origin='service_resource_export', captured_at=EARLY), 'c' * 64)
    row = parse_json({'captured_at': EARLY, 'service_exports': {'export_service': {'exports': [
        {'resource_id': 'untyped', 'observed_at': EARLY, 'owner_email': 'subject@example.test',
         'object_key': 'export.zip'}]}}}, ctx)[-1]
    result = decision(rules, row)
    assert operations(result, 'REMEDIATION') == ['DELETE_RECORD']
    assert result.assessments[0].scope.collection is None


def test_retained_missing_record_blocks_instead_of_fabricating_restore_operation(rules):
    row = absent(category='SECURITY_AUDIT_LOG', system='security_service', collection='security_audit_records',
                 retention_until=FUTURE)
    result = decision(rules, row)
    assert result.prediction is None
    assert 'required_retained_record_missing_no_supported_recreation_operation' in result.unresolved


@pytest.mark.parametrize('category,system,collection,fields', [
    ('SECURITY_AUDIT_LOG', 'security_service', 'security_audit_records', {'retention_until': FUTURE}),
    ('DATA_FLOW', 'integration_service', 'connector_configurations', {'enabled': False}),
    ('BACKUP_ARCHIVE', 'backup_service', 'backup_catalog', {'restore_allowed': False}),
])
def test_only_retention_or_process_safety_cannot_prove_deleted_user(rules, category, system, collection, fields):
    result = decision(rules, observation(category=category, system=system, collection=collection, **fields))
    assert result.prediction is None
    assert 'no_verified_deletion_treatment' in result.blockers


def test_cli_rejects_artifacts_inside_dataset(rules, tmp_path, monkeypatch):
    import main
    monkeypatch.setattr(main, 'load_dataset', lambda *a, **k: dataset(rules, observation()))
    with pytest.raises(SystemExit):
        main.main(['--dataset', str(tmp_path), '--predictions', str(tmp_path / 'input.csv')])
    assert not (tmp_path / 'input.csv').exists()


def test_pipeline_never_reads_sample_answers_or_existing_output(rules, tmp_path, monkeypatch):
    original = Path.open

    def guarded(path, *args, **kwargs):
        assert path.name not in {'sample_output.csv', 'output.csv'}
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', guarded)
    assert predict(dataset(rules, observation())).cases[0].decision == 'INCOMPLETE'


@pytest.fixture(scope='module')
def participant_run():
    from ghost_audit.ingestion import load_dataset
    d = load_dataset(Path(__file__).resolve().parents[2] / 'dataset')
    index = EvidenceIndex(d.observations, registry=d.registry)
    return d, index, predict(d, index)


def test_real_518_case_run_validates_grounded_rows_and_exposes_abstentions(participant_run, tmp_path):
    d, index, run = participant_run
    assert len(run.cases) == 518
    assert [c.case_id for c in run.cases] == sorted(r.case_id for r in d.requests)
    requests = [r for r in d.requests if r.case_id in {p.case_id for p in run.predictions}]
    assert validate_output(run.predictions, requests, index)
    assert not run.validation_errors
    # Coverage is an observed result, never a fixed label count or acceptance target.
    assert all(c.prediction is not None or c.blockers for c in run.cases)
    for row in run.predictions:
        cutoff = next(r.audit_at for r in d.requests if r.case_id == row.case_id)
        assert all(not s.evidence_id or index.registry.get(s.evidence_id).captured_at <= cutoff for s in row.steps)
    if not run.publishable:
        with pytest.raises(PredictionBlocked):
            publish(tmp_path / 'output.csv', run, d, index)
        assert not (tmp_path / 'output.csv').exists()
