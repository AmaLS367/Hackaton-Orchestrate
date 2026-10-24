from dataclasses import replace

from ghost_audit.correlation import EvidenceCorrelator
from ghost_audit.extraction import ExtractionContext, parse_json, parse_text
from ghost_audit.identity import IdentityResolver
from ghost_audit.index import EvidenceIndex, EvidenceRegistry
from ghost_audit.models import EvidenceDocument, EvidenceFile, ResourceRef
from ghost_audit.sql import parse_sql
from ghost_audit.time import parse_timestamp

from test_identity import T1, T2, T3, T4, change, snapshot


def correlate(items, *, identities=None, changes=(), cutoff=T4):
    resolver = IdentityResolver(identities if identities is not None else [snapshot(at=T1)], changes)
    identity = resolver.resolve('new@example.invalid', cutoff)
    result = EvidenceCorrelator(EvidenceIndex(items), resolver).correlate(identity, parse_timestamp(cutoff))
    return result


def confirmed(items):
    return [x for x in items if x.association == 'CONFIRMED']


def test_direct_id_and_historical_email_and_phone_hash(context):
    items = parse_json([
        {'resource_id': 'record_a', 'user_id': 'user_one'},
        {'resource_id': 'record_b', 'email': 'OLD@example.invalid'},
        {'resource_id': 'record_c', 'phone': '+44 (20) 1234-5678'},
        {'resource_id': 'record_d', 'email_hash': 'OLD_HASH'},
    ], context)
    changes = [change('a', 'old@example.invalid', 'new@example.invalid', at=T1),
               change('b', '+442012345678', '+1 (202) 555-0100', 'phone', at=T1),
               change('c', 'old_hash', 'HASH_SUPPLIED', 'email_hash', at=T1)]
    result, resources, issues = correlate(items, changes=changes)
    assert len(confirmed(result)) == 4
    assert len(resources) == 4
    assert issues == ['resource_system_unknown']
    link = next(x.links[0] for x in result if x.observation.payload.get('email'))
    assert link.method == 'DIRECT_IDENTIFIER'
    assert link.alias_origins[0].audit_id == 'a'
    assert link.supporting_observations[0].locator == '$[1]'


def test_trace_start_and_result_keep_both_locators(context):
    items = parse_text(
        '2026-01-02T10:00:00Z service=store trace_id=abc event=start email=new@example.invalid\n'
        '2026-01-02T10:01:00Z service=store trace_id=abc event=result resource_id=record_a rows=0', context)
    result, resources, _ = correlate(items)
    assert len(confirmed(result)) == 2
    trace_link = next(link for link in result[1].links if link.method == 'SCOPED_TRACE')
    assert [ref.locator for ref in trace_link.supporting_observations] == ['line:1', 'line:2']
    assert resources[0].reference.system_id == 'store'
    # rows=0 is a claim and never turned into an absence/deletion verdict.
    assert result[1].observation.payload['rows'] == '0'


def test_trace_is_scoped_to_file_and_service(context):
    first = parse_text('2026-01-02T10:00:00Z service=store trace_id=same email=new@example.invalid', context)
    wrong_service = parse_text('2026-01-02T10:00:00Z service=other trace_id=same resource_id=other_a', context)
    other_context = replace(context, manifest=context.manifest.model_copy(update={
        'file_id': 'other_file', 'file_path': 'evidence/logs/other.log'}))
    wrong_file = parse_text('2026-01-02T10:00:00Z service=store trace_id=same resource_id=other_b', other_context)
    result, resources, _ = correlate([*first, *wrong_service, *wrong_file])
    assert len(result) == 1
    assert resources == []


def test_trace_reuse_across_users_is_potential(context):
    items = parse_text(
        '2026-01-02T10:00:00Z service=store trace_id=same email=new@example.invalid\n'
        '2026-01-02T10:00:00Z service=store trace_id=same email=other@example.invalid\n'
        '2026-01-02T10:01:00Z service=store trace_id=same resource_id=unproven', context)
    identities = [snapshot(at=T1), snapshot('user_two', 'other@example.invalid', T1,
                                           phone='+22222222222', email_hash='other_hash')]
    result, resources, issues = correlate(items, identities=identities)
    assert len(confirmed(result)) == 1
    assert result[-1].association == 'POTENTIAL'
    assert 'ambiguous_trace_scope' in issues
    assert not resources


def test_json_rows_are_separate_no_file_wide_matching(context):
    items = parse_json({'system': 'store', 'records': [
        {'resource_id': 'mine', 'email': 'new@example.invalid'},
        {'resource_id': 'other', 'email': 'other@example.invalid'},
        {'resource_id': 'similar', 'email': 'newish@example.invalid'},
        {'resource_id': 'prefix', 'user_id': 'user_one_more'},
    ]}, context)
    result, resources, _ = correlate(items)
    assert [r.reference.resource_id for r in resources] == ['mine']
    assert len(result) == 1


def test_email_substring_is_not_a_match(context):
    items = parse_text('Contact anew@example.invalid or new@example.invalid.other for help.', context)
    assert correlate(items)[0] == []


def test_mixed_subject_record_is_potential_and_never_seeds_resources(context):
    items = parse_json([
        {'resource_id': 'shared', 'people': [{'email': 'new@example.invalid'}, {'user_id': 'unknown_user'}]},
        {'resource_id': 'shared', 'note': 'no identity'},
    ], replace(context, system='store'))
    result, resources, issues = correlate(items)
    assert len(result) == 1
    assert result[0].association == 'POTENTIAL'
    assert not resources
    assert issues == ['unsupported_subject_reference']


def test_unknown_second_email_prevents_document_cooccurrence_proof(context):
    items = parse_json({'resource_id': 'mixed', 'email': 'new@example.invalid',
                        'other_person': {'email': 'unknown@example.invalid'}}, context)
    result, resources, _ = correlate(items)
    assert result[0].association == 'POTENTIAL'
    assert not resources


def test_shared_phone_cannot_merge_users(context):
    items = parse_json({'resource_id': 'ambiguous', 'phone': '+12025550100'}, context)
    result, resources, _ = correlate(items, identities=[snapshot(at=T1), snapshot('user_two', 'other@example.invalid', T1)])
    assert result[0].association == 'POTENTIAL'
    assert not resources


def test_name_only_and_system_only_are_unrelated(context):
    items = parse_json({'system': 'store', 'records': [
        {'resource_id': 'a', 'name': 'Fictional Person'},
        {'resource_id': 'b', 'result': 'gone'},
    ]}, context)
    assert correlate(items)[0] == []


def test_future_manifest_and_nested_record_and_unknown_time_excluded(context):
    future = replace(context, manifest=context.manifest.model_copy(update={'captured_at': parse_timestamp(T4)}))
    items = parse_json({'resource_id': 'a', 'user_id': 'user_one'}, future)
    items += parse_json({'resource_id': 'b', 'user_id': 'user_one', 'updated_at': T4}, context)
    item = parse_json({'resource_id': 'c', 'user_id': 'user_one'}, context)[0]
    items.append(item.model_copy(update={'provenance': item.provenance.model_copy(update={'captured_at': None})}))
    assert correlate(items, cutoff=T3)[0] == []


def test_future_trace_anchor_cannot_link_earlier_result(context):
    items = parse_text(
        '2026-01-04T00:00:00Z service=store trace_id=same email=new@example.invalid\n'
        '2026-01-02T00:00:00Z service=store trace_id=same resource_id=record_a', context)
    assert correlate(items, cutoff=T3)[0] == []


def test_resource_versions_replicas_and_metadata_preserved(context):
    scoped = replace(context, system='store', collection='profiles', physical_table='primary_replica')
    first = parse_json({'resource_id': 'record_a', 'email': 'new@example.invalid'}, scoped)
    second = parse_json({'resource_id': 'record_a', 'email': None},
                        replace(scoped, physical_table='failover_replica'), '$.replica')
    result, resources, _ = correlate([*first, *second])
    assert len(confirmed(result)) == 2
    assert len({(r.observation.provenance.evidence_id, r.observation.provenance.locator) for r in result}) == 2
    assert {r.reference.physical_table for r in resources} == {'primary_replica', 'failover_replica'}
    assert all(r.reference.collection == 'profiles' for r in resources)
    assert all(r.observation.provenance.sha256 == context.sha256 for r in result)
    assert any(link.method == 'RESOURCE' for link in result[1].links)


def test_resource_id_collision_across_systems_is_excluded(context):
    first = parse_json({'resource_id': 'same', 'user_id': 'user_one'}, replace(context, system='store'))
    other = parse_json({'resource_id': 'same', 'result': 'exists'}, replace(context, system='other'), '$.other')
    assert len(correlate([*first, *other])[0]) == 1


def test_unknown_resource_system_is_only_potential(context):
    first = parse_json({'resource_id': 'same', 'user_id': 'user_one'}, replace(context, system='store'))
    other = parse_json({'resource_id': 'same', 'result': 'exists'}, context, '$.unknown')
    result, _, _ = correlate([*first, *other])
    assert result[-1].association == 'POTENTIAL'


def test_resource_with_foreign_subject_does_not_merge(context):
    items = parse_json([
        {'resource_id': 'same', 'email': 'new@example.invalid'},
        {'resource_id': 'same', 'user_id': 'user_foreign'},
    ], replace(context, system='store'))
    result, _, _ = correlate(items)
    assert len(confirmed(result)) == 1
    assert result[-1].association == 'POTENTIAL'


def test_explicit_references_are_one_hop_and_resource_expansion_is_terminal(context):
    items = parse_json([
        {'resource_id': 'a', 'user_id': 'user_one', 'target_resource_id': 'b'},
        {'resource_id': 'b', 'target_resource_id': 'c'},
        {'resource_id': 'c', 'target_resource_id': 'd'},
        {'resource_id': 'd'},
    ], replace(context, system='store'))
    result, resources, _ = correlate(items)
    assert {r.reference.resource_id for r in resources} == {'a', 'b'}
    assert any(link.method == 'EXPLICIT_RESOURCE_REFERENCE' for link in result[1].links)
    assert len(result) == 2


def test_sql_decoded_records_and_replica_provenance(context):
    sql = '''CREATE TABLE replica(resource_id TEXT, origin_system TEXT, collection_name TEXT, record_json TEXT);
    INSERT INTO replica VALUES ('record_a','store','profiles','{"email":"new@example.invalid"}');'''
    result, resources, _ = correlate(parse_sql(sql, context))
    assert len(confirmed(result)) == 1
    assert resources[0].reference == ResourceRef(resource_id='record_a', system_id='store', collection='profiles', physical_table='replica')
    assert result[0].observation.payload['decoded_record']['email'] == 'new@example.invalid'


def test_ambiguous_identity_has_no_confirmed_links(context):
    items = parse_json({'resource_id': 'record_a', 'email': 'new@example.invalid'}, context)
    result, resources, issues = correlate(items, identities=[snapshot(at=T1), snapshot('user_two', at=T1)])
    assert result == resources == []
    assert issues == ['identity_not_uniquely_resolved']


def test_registry_keeps_deferred_images_without_interpreted_facts():
    manifest = EvidenceFile(file_id='image', file_path='evidence/images/image.png',
                            origin='screen', captured_at=T1)
    registry = EvidenceRegistry(documents=[EvidenceDocument(manifest=manifest, sha256='a' * 64,
                                                           status='deferred', observations=[])])
    index = EvidenceIndex([], registry=registry)
    resolver = IdentityResolver([snapshot(at=T1)], [])
    assert EvidenceCorrelator(index, resolver).correlate(resolver.resolve('new@example.invalid', T3), parse_timestamp(T3))[0] == []
    assert registry.get('image').parsing_status == 'deferred'
