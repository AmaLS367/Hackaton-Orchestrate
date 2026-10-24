import pytest

from ghost_audit.identity import IdentityResolver
from ghost_audit.models import Identity, IdentityChange
from ghost_audit.time import parse_timestamp

T1 = '2026-01-01T00:00:00Z'
T2 = '2026-01-02T00:00:00Z'
T3 = '2026-01-03T00:00:00Z'
T4 = '2026-01-04T00:00:00Z'


def snapshot(user='user_one', email='new@example.invalid', at=T3, **kwargs):
    return Identity(user_id=user, name='Fictional Person', email=email,
                    phone=kwargs.get('phone', '+1 (202) 555-0100'),
                    email_hash=kwargs.get('email_hash', 'HASH_SUPPLIED'), updated_at=at)


def change(audit, old, new, field='email', at=T2, user='user_one'):
    return IdentityChange(audit_id=audit, user_id=user, event_time=at,
                          field_name=field, old_value=old, new_value=new)


def test_current_email_casefold_and_unknown():
    resolver = IdentityResolver([snapshot()], [])
    assert resolver.resolve(' NEW@EXAMPLE.INVALID ', T4).user_id == 'user_one'
    unknown = resolver.resolve('nobody@example.invalid', T4)
    assert unknown.status == 'UNRESOLVED'
    assert unknown.user_id is None
    assert not unknown.candidates


def test_multiple_email_changes_keep_origins_and_chronology():
    changes = [change('audit_b', 'middle@example.invalid', 'new@example.invalid', at=T2),
               change('audit_a', 'old@example.invalid', 'middle@example.invalid', at=T1)]
    resolver = IdentityResolver([snapshot()], changes)
    result = resolver.resolve('OLD@example.invalid', T4)
    assert result.status == 'RESOLVED'
    emails = [a for a in result.aliases if a.field_name == 'email']
    assert {a.normalized_value for a in emails} == {'old@example.invalid', 'middle@example.invalid', 'new@example.invalid'}
    assert [a.event_time for a in emails] == sorted(a.event_time for a in emails)
    old = next(a for a in emails if a.original_value == 'old@example.invalid')
    assert old.audit_id == 'audit_a'
    assert old.event_time == parse_timestamp(T1)
    assert old.source == 'audit_log'
    assert old.value_role == 'old_value'
    assert not old.active_at_cutoff
    assert old.valid_until == parse_timestamp(T1)
    middle = next(a for a in emails if a.value_role == 'new_value' and a.audit_id == 'audit_a')
    assert middle.valid_from == parse_timestamp(T1)
    assert middle.valid_until == parse_timestamp(T2)
    assert all(a.active_at_cutoff for a in emails if a.normalized_value == 'new@example.invalid')


def test_historical_phone_and_hash_are_exact_and_not_derived():
    resolver = IdentityResolver([snapshot()], [
        change('phone_event', '+44 (20) 1234-5678', '+1 (202) 555-0100', 'phone'),
        change('hash_event', ' OLD_HASH ', 'HASH_SUPPLIED', 'email_hash'),
    ])
    result = resolver.resolve('new@example.invalid', T4)
    assert resolver.owners('+442012345678', T4) == {'user_one'}
    assert resolver.owners('old_hash', T4) == {'user_one'}
    alias = next(a for a in result.aliases if a.audit_id == 'hash_event' and a.value_role == 'old_value')
    assert alias.original_value == ' OLD_HASH '
    assert alias.normalized_value == 'old_hash'
    assert {a.normalized_value for a in result.aliases if a.field_name == 'email_hash'} == {'old_hash', 'hash_supplied'}


def test_future_snapshot_and_changes_never_establish_earlier_aliases():
    resolver = IdentityResolver([snapshot(at=T4)], [
        change('earlier', 'old@example.invalid', 'middle@example.invalid', at=T1),
        change('future', 'middle@example.invalid', 'new@example.invalid', at=T3),
    ])
    result = resolver.resolve('old@example.invalid', T2)
    assert result.status == 'RESOLVED'
    assert not any(a.audit_id == 'future' or a.source == 'identity_snapshot' for a in result.aliases)
    assert not any(a.normalized_value == 'new@example.invalid' for a in result.aliases)
    assert resolver.resolve('new@example.invalid', T2).status == 'UNRESOLVED'
    assert resolver.owners('new@example.invalid', T2) == set()
    assert {a.normalized_value for a in result.aliases if a.field_name == 'email' and a.active_at_cutoff} == {'middle@example.invalid'}


def test_future_old_value_is_not_backdated():
    resolver = IdentityResolver([snapshot(at=T4)], [change('future', 'old@example.invalid', 'new@example.invalid', at=T3)])
    assert resolver.resolve('old@example.invalid', T2).status == 'UNRESOLVED'


def test_colliding_email_returns_all_candidates_without_merging():
    resolver = IdentityResolver([snapshot(), snapshot('user_two', 'NEW@example.invalid')], [])
    result = resolver.resolve('new@example.invalid', T4)
    assert result.status == 'AMBIGUOUS'
    assert result.candidates == ['user_one', 'user_two']
    assert result.user_id is None
    assert result.aliases == []


def test_shared_phone_warns_but_unique_email_still_resolves():
    resolver = IdentityResolver([snapshot(), snapshot('user_two', 'other@example.invalid')], [])
    result = resolver.resolve('new@example.invalid', T4)
    assert result.status == 'RESOLVED'
    assert 'shared_alias:phone' in result.ambiguities
    assert 'shared_alias:email_hash' in result.ambiguities


def test_names_are_not_authoritative():
    resolver = IdentityResolver([snapshot()], [])
    assert resolver.owners('Fictional Person', T4) == set()
    assert resolver.resolve('Fictional Person', T4).status == 'UNRESOLVED'


def test_equal_timestamp_conflict_and_discontinuous_history():
    resolver = IdentityResolver([], [
        change('a', 'old@example.invalid', 'middle@example.invalid', at=T1),
        change('b', 'different@example.invalid', 'second@example.invalid', at=T2),
        change('c', 'different@example.invalid', 'third@example.invalid', at=T2),
    ])
    result = resolver.resolve('old@example.invalid', T3)
    assert 'conflicting_latest_values:email' in result.ambiguities
    assert 'discontinuous_history:email' in result.ambiguities
    assert all(a.active_at_cutoff is None for a in result.aliases if a.field_name == 'email')


def test_email_string_requires_cutoff():
    with pytest.raises(ValueError, match='audit_at'):
        IdentityResolver([snapshot()], []).resolve('new@example.invalid')
