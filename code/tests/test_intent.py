import pytest

from ghost_audit.domain.intent import IntentClassifier


@pytest.mark.parametrize('text', [
    'Please delete my account.',
    'Delete personal data.',
    'Permanently erase an account.',
    'Remove an account and associated identifying information.',
    'Remove remaining personal data after an incomplete deletion.',
    'Permanently erase my account and personal data.',
    'Remove my account and associated identifying information.',
    'I already requested deletion; verify that it completed.',
    'Complete a previously requested deletion.',
    'Verify that my account was deleted.',
    'Please remove my remaining personal data.',
    'Solicito la eliminación permanente de mi cuenta.',
    'Por favor, eliminar mi cuenta y mis datos personales.',
    'Je demande la suppression définitive de mon compte.',
    'Veuillez supprimer mon compte et mes données personnelles.',
    'Supprimez mon compte.',
    'Elimina mi cuenta.',
    'Solicito a exclusão permanente da conta associada a este e-mail.',
    'このメールアドレスに関連するアカウントの完全な削除を依頼します。',
    '이 이메일 주소에 연결된 계정의 영구 삭제를 요청합니다.',
])
def test_authorized_deletion(text):
    result = IntentClassifier().classify(text)
    assert result.decision == 'DELETE_INTENT'
    assert result.confidence == 'HIGH'
    assert not result.fallback_recommended
    assert result.reason_id


@pytest.mark.parametrize('text', [
    'Do not delete my account.',
    'Do not permanently delete my account.',
    'Do not remove remaining personal data.',
    'I am not requesting deletion of my account.',
    'Please do not process a permanent account-deletion request.',
    'I no longer want to delete my account.',
    'I do not want you to delete my account.',
    "I don't need you to delete my account.",
    'Please cancel my deletion request.',
    'I withdraw my erasure request.',
    "Je demande d'annuler la suppression définitive du compte.",
    'Je demande la suppression de mon abonnement marketing mais gardez mon compte.',
    "Please don't delete my account.",
    'I only want a copy of my data.',
    'Delete my marketing subscription but keep my account.',
    'Please remove my personal information from your marketing lists.',
    'No quiero eliminar mi cuenta.',
    'Je ne souhaite pas supprimer mon compte.',
    'Não solicito a exclusão permanente da conta.',
    'Please unsubscribe me from marketing emails.',
    'Please export my data.',
    'I want to access my personal data.',
    'Please correct my personal information.',
    'I need help logging in.',
    'No elimines mi cuenta.',
    'Ne supprimez pas mon compte.',
    'Ne pas supprimer mon compte.',
    'Je veux une copie de mes données.',
    'Quiero una copia de mis datos.',
    "This is an information request, not a request to erase it.",
])
def test_no_deletion(text):
    assert IntentClassifier().classify(text).decision == 'NO_DELETE_INTENT'


@pytest.mark.parametrize('text', [
    'Please handle this.',
    'My account has a problem.',
    'What happens if I delete my account?',
    'Do you delete my account when I unsubscribe?',
    'I want to know how to delete my account.',
    'Is it possible to delete my account?',
    'Please delete my account? I am not sure.',
    'Should I delete my account?',
    'I might want to delete my account.',
    'The button says "delete my account".',
    'Do not delete my account. Please delete my account.',
    'Delete the old attachment.',
])
def test_uncertain_is_preserved(text):
    result = IntentClassifier().classify(text)
    assert result.decision == 'UNCERTAIN'
    assert result.fallback_recommended
    assert result.confidence == 'LOW'


def test_reported_status_does_not_authorize_deletion():
    from ghost_audit.domain.models import DeletionRequest
    request = DeletionRequest(case_id='x', email='p@example.invalid',
                              requested_at='2026-01-01T00:00:00Z',
                              reported_at='2026-01-02T00:00:00Z',
                              audit_at='2026-01-03T00:00:00Z',
                              reported_status='COMPLETE', request_text='Export my data please.')
    assert IntentClassifier().classify(request).decision == 'NO_DELETE_INTENT'


@pytest.mark.parametrize('text, expected', [
    ("I didn't ask you to delete my account.", 'NO_DELETE_INTENT'),
    ('I did not request deletion of my account.', 'NO_DELETE_INTENT'),
    ('Je ne veux plus supprimer mon compte.', 'NO_DELETE_INTENT'),
    ('Je ne souhaite plus la suppression de mon compte.', 'NO_DELETE_INTENT'),
    ('No pedi eliminar mi cuenta.', 'NO_DELETE_INTENT'),
    ('Please delete my account only after I approve it.', 'UNCERTAIN'),
    ('Delete my account if I give approval.', 'UNCERTAIN'),
    ('Please delete my account once I confirm.', 'UNCERTAIN'),
    ('Do not delete my account and please delete my account.', 'UNCERTAIN'),
    ("I didn't ask you to delete my account, but please delete my account now.", 'UNCERTAIN'),
    ('Je ne veux plus supprimer mon compte. Supprimez mon compte.', 'UNCERTAIN'),
    ('Please delete my account after exporting my records.', 'DELETE_INTENT'),
    ('Please delete my account. I approve this deletion.', 'DELETE_INTENT'),
    ('Please delete my account, not my marketing subscription.', 'DELETE_INTENT'),
    ('I did not ask for marketing emails. Please delete my account.', 'DELETE_INTENT'),
])
def test_negation_and_future_authorization(text, expected):
    assert IntentClassifier().classify(text).decision == expected


@pytest.mark.parametrize('residual', [
    'leftover backups', 'remaining replicas', 'residual archives',
    'leftover search indexes', 'restored records containing my personal information',
])
@pytest.mark.parametrize('history', [
    'My account was deleted last month.',
    'My personal data has already been erased.',
])
def test_historical_deletion_verification(history, residual):
    assert IntentClassifier().classify(f'{history} Please check for {residual}.').decision == 'DELETE_INTENT'


@pytest.mark.parametrize('text', [
    'What is your deletion policy for backups?',
    'Please check your account deletion policy for archives.',
    'My account was deleted last month. What is your backup retention policy?',
    'Please check for leftover backups.',
    'My account was deleted last month. Please check the invoice total.',
    'A customer account was deleted last month. Please check for leftover backups.',
    'My account was deleted last month. Do not check for leftover backups.',
])
def test_generic_or_unauthorized_history_does_not_authorize_audit(text):
    assert IntentClassifier().classify(text).decision != 'DELETE_INTENT'


@pytest.mark.parametrize('text, expected', [
    ('My account was deleted last month. Please check your backup deletion policy.', 'UNCERTAIN'),
    ('My account was deleted last month. Check for leftover backups.', 'DELETE_INTENT'),
    ('Please check for leftover backups. My account was deleted last month.', 'DELETE_INTENT'),
    ('My account was deleted last month. Please check for leftover backups under your deletion policy.', 'DELETE_INTENT'),
])
def test_personal_residual_audit_is_distinct_from_policy_verification(text, expected):
    assert IntentClassifier().classify(text).decision == expected
