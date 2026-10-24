from dataclasses import replace
import csv

import pytest
from pypdf import PdfWriter

from ghost_audit.index import EvidenceIndex
from ghost_audit.ingestion import parse_document
from ghost_audit.output import OutputRow, validate_output, write_output
from test_output import request, step


@pytest.mark.parametrize('suffix', ['png', 'pdf'])
def test_deferred_citation_uses_manifest_availability(tmp_path, context, suffix):
    from ghost_audit.index import EvidenceRegistry

    manifest = context.manifest.model_copy(update={'file_path': f'evidence/fixture.{suffix}'})
    path = tmp_path / manifest.file_path
    path.parent.mkdir(parents=True)
    if suffix == 'pdf':
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.write(path)
    else:
        path.write_bytes(b'image placeholder')
    document = parse_document(tmp_path, manifest)
    assert document.status == 'deferred'
    assert not document.observations
    registry = EvidenceRegistry(documents=[document])
    entry = registry.get('fixture_file')
    assert entry.file_path == manifest.file_path
    assert entry.origin == manifest.origin
    assert entry.captured_at == manifest.captured_at
    assert entry.parsing_status == 'deferred'
    index = EvidenceIndex([], registry=registry)
    row = OutputRow(case_id='fixture_case', deletion_status='COMPLETE', steps=[step()])
    checks = validate_output([row], [request(audit_at='2026-01-02T12:00:00Z')], index)
    assert checks[0].resource_support == 'unknown'
    assert checks[0].state_support == 'unverified'
    with pytest.raises(ValueError, match='future evidence'):
        validate_output([row], [request(audit_at='2026-01-02T11:59:59Z')], index)
    unknown = row.model_copy(update={'steps': [step(evidence_id='missing_file')]})
    with pytest.raises(ValueError, match='unknown evidence'):
        validate_output([unknown], [request()], index)
    output = tmp_path / 'output.csv'
    write_output(output, [row], [request()], index)
    assert output.exists()


def test_audit_and_activity_registered_without_observations():
    from ghost_audit.index import EvidenceRegistry
    from ghost_audit.models import Activity, IdentityChange

    activity = Activity(activity_id='activity_x', event_time='2026-01-02T00:00:00Z',
                        event_type='lookup', source_system='', target_system='account_service',
                        resource_id='record_x', reported_result='COMPLETE', details='Claim only')
    audit = IdentityChange(audit_id='audit_x', user_id='user_x', event_time='2026-01-02T00:00:00Z',
                           field_name='email', old_value='old@example.invalid', new_value='new@example.invalid')
    registry = EvidenceRegistry(activities=[activity], identity_changes=[audit])
    index = EvidenceIndex([], registry=registry)
    for evidence_id, source in [('activity_x', 'system_activity.csv'), ('audit_x', 'user_audit_log.csv')]:
        assert registry.get(evidence_id).file_path == source
        row = OutputRow(case_id='fixture_case', deletion_status='COMPLETE',
                        steps=[step(evidence_id=evidence_id)])
        checks = validate_output([row], [request()], index)
        assert checks[0].resource_support == 'unknown'
        assert checks[0].state_support == 'unverified'
        with pytest.raises(ValueError, match='future evidence'):
            validate_output([row], [request(audit_at='2026-01-01T12:00:00Z')], index)


def test_current_identity_id_is_not_a_citation(context):
    from ghost_audit.extraction import parse_json

    context = replace(context, manifest=context.manifest.model_copy(
        update={'file_path': 'user_identities.csv', 'file_id': 'user_x'}))
    items = [item.model_copy(update={'kind': 'identity'})
             for item in parse_json({'user_id': 'user_x'}, context)]
    row = OutputRow(case_id='fixture_case', deletion_status='COMPLETE',
                    steps=[step(evidence_id='user_x')])
    with pytest.raises(ValueError, match='unknown evidence'):
        validate_output([row], [request()], EvidenceIndex(items))


def test_cli_validates_manifest_only_citation_offline(tmp_path, capsys):
    from main import main

    dataset = tmp_path / 'dataset'
    dataset.mkdir()
    empty_csvs = {
        'user_identities.csv': 'user_id,name,email,phone,email_hash,updated_at',
        'user_audit_log.csv': 'audit_id,user_id,event_time,field_name,old_value,new_value',
        'system_activity.csv': 'activity_id,event_time,event_type,source_system,target_system,resource_id,reported_result,details',
        'deletion_rules.csv': 'rule_id,data_category,condition,required_action',
    }
    for name, header in empty_csvs.items():
        (dataset / name).write_text(header + '\n', encoding='utf-8')
    with (dataset / 'deletion_requests.csv').open('w', newline='', encoding='utf-8') as stream:
        values = request().model_dump(mode='json')
        writer = csv.DictWriter(stream, fieldnames=list(values))
        writer.writeheader()
        writer.writerow(values)
    (dataset / 'evidence_files.csv').write_text(
        'file_id,file_path,origin,captured_at\n'
        'fixture_file,evidence/fixture.png,fixture_store,2026-01-02T00:00:00Z\n', encoding='utf-8')
    (dataset / 'evidence').mkdir()
    (dataset / 'evidence/fixture.png').write_bytes(b'image placeholder')
    predictions = tmp_path / 'predictions.csv'
    row = OutputRow(case_id='fixture_case', deletion_status='COMPLETE', steps=[step()])
    write_output(predictions, [row], [request()])
    assert main(['validate-output', '--dataset', str(dataset), '--predictions', str(predictions)]) == 0
    output = capsys.readouterr().out
    assert 'Validated 1 rows.' in output
    assert '1 citations have unknown resource support' in output
    assert 'All cited state claims remain unverified' in output
