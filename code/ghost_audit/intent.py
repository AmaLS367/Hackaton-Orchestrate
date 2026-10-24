"""Conservative offline request interpretation; unmatched language stays uncertain."""

import re
import unicodedata

from .models import DeletionRequest
from .phase2_models import IntentResult


def fold(text: str) -> str:
    text = text.casefold().replace('’', "'").replace('-', ' ')
    return unicodedata.normalize('NFC', ''.join(c for c in unicodedata.normalize('NFKD', text)
                                               if not unicodedata.combining(c)))


# Rules require an action and a personal-data/account object or an explicit
# follow-up verification context. They are deliberately independent of workflow status.
DELETE_RULES = (
    ('en_explicit', r'\b(?:delete|erase|remove|close|deleting)\s+(?:(?:permanently|completely)\s+)?(?:my|this|the|an|any remaining copy of my)\s+(?:remaining\s+)?(?:account|personal (?:data|information|details)|profile|name and contact details)\b'),
    ('en_personal_data', r'\b(?:delete|erase|remove)\s+(?:(?:all|remaining)\s+)?personal (?:data|information|details)\b'),
    ('en_passive', r'\b(?:account|personal data)\b[^.!?;]{0,90}\b(?:would like|want|to be|have its associated personal data)\b[^.!?;]{0,35}\b(?:deleted|erased|closed)\b'),
    ('en_deletion_request', r'\b(?:requesting deletion of|request for (?:permanent )?account deletion|process (?:a permanent account deletion request|the associated personal data deletion)|begin the deletion process)\b'),
    ('en_verify_deletion', r'\b(?:verify|check|confirm|audit|finish|complete|investigate)\b[^.!?;]{0,100}\b(?:deletion|(?:account|profile|data) (?:was |has been |is |were |have (?:already )?been )?(?:deleted|gone|removed)|nothing tied to the old address was left behind)\b'),
    ('en_verify_state', r'\b(?:inspect|verify|check|tell me whether)\b[^.!?;]{0,140}\b(?:account|profile|identifiable (?:analytics )?data)\b[^.!?;]{0,70}\b(?:removed|deleted|gone)\b'),
    ('en_prior_deletion', r'\b(?:already requested deletion|previously requested deletion|deleted (?:my|this) account|account had been deleted|account itself is gone)\b[^\n]{0,260}\b(?:verify|remove|handle|check|keep only)\b'),
    ('en_remaining_copies', r'\b(?:please|can you)\s+(?:remove|delete)\s+(?:that (?:search result|export file)|records (?:linked to|under) both|the rest)\b'),
    ('es_explicit', r'\b(?:solicito|quiero|por favor|deseo)\b[^.!?;]{0,45}\b(?:eliminacion|borrar|eliminar|borrado)\b[^.!?;]{0,50}\b(?:cuenta|datos personales)\b'),
    ('es_imperative', r'\b(?:elimina|elimine|borra|borre)\s+(?:mi|mis)\s+(?:cuenta|datos personales)\b'),
    ('es_followup', r'\b(?:intente eliminar mi cuenta|solicite (?:la )?eliminacion)\b[^\n]{0,250}\b(?:comprobar|verificar|completar)\b'),
    ('fr_explicit', r'\b(?:je demande|je souhaite|veuillez)\s+(?:la )?suppression\s+(?:(?:definitive|permanente)\s+)?(?:du|de mon|des|de mes)\s+(?:compte|donnees personnelles)\b'),
    ('fr_imperative', r'\b(?:supprimez|effacez|supprimer|effacer)\s+(?:mon compte|mes donnees personnelles)\b'),
    ('pt_explicit', r'\bsolicito (?:a )?exclusao permanente (?:da conta|dos dados pessoais)\b'),
    ('ja_explicit', r'アカウントの(?:完全な|永久)?削除を(?:依頼|お願い|希望)します'),
    ('ko_explicit', r'계정의 영구 삭제를 요청합니다'),
)
NEGATIVE = (
    r"\b(?:do not|don't|never|not to)\s+(?:permanently\s+)?(?:delete|erase|remove|close)\s+(?:(?:my|the|this|an)\s+)?(?:(?:remaining|all)\s+)?(?:account|personal data|data|profile|anything)\b",
    r"\b(?:do not|don't)\s+(?:want|wish|need|authorize|consent)\b[^.!?;]{0,35}\b(?:delet\w*|eras\w*|remov\w*|clos\w*)\b",
    r"\b(?:not requesting|not asking for|no longer want|do not process|don't process)\b[^.!?;]{0,50}\b(?:delet\w*|eras\w*|remov\w*|clos\w*)\b",
    r"\b(?:not a request to (?:erase|delete)|keep my account|do not authorize deletion)\b",
    r'\b(?:cancel|withdraw|revoke)\b[^.!?;]{0,35}\b(?:deletion|erasure)\b',
    r'\bno\s+(?:borres|elimine[ns]?|borrar|eliminar)\s+(?:(?:mi|la|mis)\s+)?(?:cuenta|datos)\b',
    r'\bno (?:quiero|deseo|solicito)\b[^.!?;]{0,30}\b(?:eliminar|borrar|eliminacion)\b',
    r'\b(?:conservar|mantener) mi cuenta\b',
    r"\bne\s+(?:supprimez|supprimer|effacez)[^.!?;]{0,15}\bpas\b",
    r'\bne pas\s+(?:supprimer|effacer)\b',
    r'\bne (?:souhaite|veux|demande) pas\b[^.!?;]{0,30}\b(?:supprimer|effacer|suppression)\b',
    r"\b(?:annuler|annulez|d'annuler)\b[^.!?;]{0,35}\bsuppression\b",
    r'\b(?:gardez|conserver) mon compte\b',
    r'\bnao\s+(?:exclua|apague|elimine|solicito)\b',
)
NON_DELETE = (
    r'\b(?:unsubscribe|opt out|marketing lists only|stop the promotional emails|marketing subscription)\b',
    r'\b(?:copy of|download|export|access|what personal information you hold)\b',
    r'\b(?:change the email|correct|correction|misspelled|out of date|resetting the login|account support|help (?:logging|signing) in)\b',
    r'\b(?:copia de mis datos|exportar mis datos|acceso a mis datos|desuscribir|corregir)\b',
    r'\b(?:copie de mes donnees|exporter mes donnees|acces a mes donnees|desabonner|corriger)\b',
)


class IntentClassifier:
    def classify(self, request: DeletionRequest | str) -> IntentResult:
        text = fold(request.request_text if isinstance(request, DeletionRequest) else request)
        # Conditional/hypothetical and quoted instructions are not authorization.
        if re.search(r"\b(?:what (?:happens|would happen) if|should i|if i|might want|thinking (?:about|of)|how (?:do|can) i|how to (?:delete|erase|remove|close)|is it possible to|can i|do you|not sure|said to delete)\b", text) or re.search(r'["“][^"”]*(?:delete|erase)[^"”]*["”]', text):
            return self._result('UNCERTAIN', 'conditional_or_quoted')
        negative = any(re.search(pattern, text) for pattern in NEGATIVE)
        marketing_only = re.search(r'\b(?:remove|delete|erase)\b[^.!?;]{0,65}\b(?:from|off)\b[^.!?;]{0,25}\b(?:marketing|mailing|promotional)\b', text)
        if marketing_only and not re.search(r'\b(?:delete|erase|close|remove) (?:my|this|the) account\b', text):
            return self._result('NO_DELETE_INTENT', 'marketing_scope_only')
        matches = [rule for rule, pattern in DELETE_RULES if re.search(pattern, text)]
        if negative:
            # Remove only negated clauses before looking for conflicting authorization.
            clauses = re.split(r'[.!?;]|\bbut\b', text)
            positive = any(any(re.search(p, clause) for _, p in DELETE_RULES)
                           for clause in clauses
                           if not any(re.search(p, clause) for p in NEGATIVE))
            return self._result('UNCERTAIN' if positive else 'NO_DELETE_INTENT',
                                'conflicting_instructions' if positive else 'explicit_no_deletion')
        if matches:
            return self._result('DELETE_INTENT', matches[0])
        if any(re.search(pattern, text) for pattern in NON_DELETE):
            return self._result('NO_DELETE_INTENT', 'non_deletion_request')
        return self._result('UNCERTAIN', 'no_reliable_rule')

    @staticmethod
    def _result(decision, reason):
        uncertain = decision == 'UNCERTAIN'
        return IntentResult(decision=decision, reason_id=reason,
                            confidence='LOW' if uncertain else 'HIGH',
                            fallback_recommended=uncertain)
