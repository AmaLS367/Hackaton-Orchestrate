"""Evidence-driven policy over physical scopes; no identifiers encode policy or labels."""

import re
from collections import defaultdict

from .models import DeletionRule
from .phase2_models import ResolvedIdentity
from .policy_models import PolicyAssessment
from .temporal import links_sorted, scope_key
from .temporal_adapters import boolean
from .temporal_models import CaseStateBundle, ResourceHistory, TemporalObservation
from .time import parse_timestamp

# Explicit participant schemas, not resource-ID conventions. An unknown schema stays unknown.
COLLECTION_CATEGORIES = {
    ('account_service', 'customer_profiles'): 'USER_PROFILE',
    ('account_service', 'deleted_customer_references'): 'ACCOUNT_TOMBSTONE',
    ('identity_service', 'deleted_customer_references'): 'ACCOUNT_TOMBSTONE',
    ('search_service', 'customer_search_documents'): 'SEARCH_INDEX_ENTRY',
    ('search_service', 'search_documents_primary'): 'SEARCH_INDEX_ENTRY',
    ('analytics_platform', 'customer_analytics_profiles'): 'ANALYTICS_PROFILE',
    ('analytics_platform', 'customer_analytics_reports'): 'ANALYTICS_PROFILE',
    ('support_platform', 'support_conversations'): 'SUPPORT_MESSAGE',
    ('support_platform', 'support_records'): 'SUPPORT_MESSAGE',
    ('support_platform', 'ticket_attachments'): 'SUPPORT_ATTACHMENT',
    ('export_service', 'customer_export_jobs'): 'USER_EXPORT',
    ('export_service', 'customer_exports'): 'USER_EXPORT',
    ('security_service', 'security_audit_records'): 'SECURITY_AUDIT_LOG',
    ('security_service', 'security_audit_events'): 'SECURITY_AUDIT_LOG',
    ('legal_service', 'retained_order_records'): 'LEGAL_HOLD_RECORD',
    ('backup_service', 'backup_catalog'): 'BACKUP_ARCHIVE',
    ('backup_service', 'backup_restore_entries'): 'BACKUP_ARCHIVE',
    ('integration_service', 'connector_configurations'): 'DATA_FLOW',
    ('integration_service', 'connector_subscriptions'): 'DATA_FLOW',
}
EXPORT_CATEGORIES = {
    ('account_service', 'profile_lookups'): 'USER_PROFILE',
    ('analytics_platform', 'profiles'): 'ANALYTICS_PROFILE',
    ('backup_service', 'restore_entries'): 'BACKUP_ARCHIVE',
    ('export_service', 'exports'): 'USER_EXPORT',
    ('integration_service', 'connectors'): 'DATA_FLOW',
    ('search_service', 'index_queries'): 'SEARCH_INDEX_ENTRY',
    ('security_service', 'audit_records'): 'SECURITY_AUDIT_LOG',
    ('support_platform', 'tickets'): 'SUPPORT_MESSAGE',
}
EVENT_CATEGORIES = {
    'profile_lookup_completed': 'USER_PROFILE',
    'index_query_completed': 'SEARCH_INDEX_ENTRY',
    'analytics_profile_read_completed': 'ANALYTICS_PROFILE',
    'analytics_profile_read': 'ANALYTICS_PROFILE',
    'analytics_identity_scan': 'ANALYTICS_PROFILE',
    'support_ticket_read_completed': 'SUPPORT_MESSAGE',
    'message_read': 'SUPPORT_MESSAGE',
    'message_pii_scan': 'SUPPORT_MESSAGE',
    'attachment_pii_scan': 'SUPPORT_ATTACHMENT',
    'export_download_check_completed': 'USER_EXPORT',
    'export_metadata_read_completed': 'USER_EXPORT',
    'audit_record_read_completed': 'SECURITY_AUDIT_LOG',
    'retained_order_loaded': 'LEGAL_HOLD_RECORD',
    'connector_config_read_completed': 'DATA_FLOW',
    'connector_config_loaded': 'DATA_FLOW',
    'connector_heartbeat': 'DATA_FLOW',
    'restore_policy_read_completed': 'BACKUP_ARCHIVE',
    'restore_authorization_completed': 'BACKUP_ARCHIVE',
    'restore_candidate_evaluated': 'BACKUP_ARCHIVE',
}
CONDITIONS = {
    'Always': 'always',
    'Conversation contains shared customer, agent, or order context that must be retained': 'shared',
    'Attachment belongs only to the deletion subject': 'subject_only',
    'Record is still attributable to a user': 'attributable',
    'Log contains a user email address': 'email',
    'Record is within the supplied retention period': 'retention',
    'A supplied legal hold is active': 'hold',
    'Restore access can be blocked': 'blockable',
    'Account is deleted and only a stable internal user_id is needed to preserve references to retained records': 'tombstone',
}
FINAL_STATES = {'DELETE': 'ABSENT', 'REDACT': 'REDACTED', 'ANONYMIZE': 'ANONYMIZED', 'RETAIN': 'PRESENT'}
EMAIL = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')


def supported_observations(history: ResourceHistory, cutoff) -> list[TemporalObservation]:
    return [o for o in history.observations if o.association == 'CONFIRMED' and o.association_links
            and o.support == 'PROVEN' and o.observed_at <= cutoff and o.available_at <= cutoff
            and (o.provenance.captured_at is not None and o.provenance.captured_at <= cutoff)]


def latest(observations):
    if not observations:
        return []
    at = max(o.observed_at for o in observations)
    return sorted((o for o in observations if o.observed_at == at), key=lambda o: o.model_dump_json())


def attributes(observations):
    """Conflicting contemporaneous attributes cannot authorize destructive treatment."""
    values = defaultdict(list)
    for o in observations:
        for key, value in o.attributes.items():
            if value not in values[key]:
                values[key].append(value)
    return {key: items[0] for key, items in values.items() if len(items) == 1}


def exposed(fields, identity: ResolvedIdentity, *, stable=False):
    aliases = [a.original_value.casefold() for a in identity.aliases if a.original_value]
    for f in fields:
        if f.representation != 'VALUE':
            continue
        if f.role == 'DIRECT_IDENTIFIER' or stable and f.role == 'STABLE_REFERENCE':
            return True
        text = str(f.value).casefold()
        if EMAIL.search(text) or f.role == 'CONTENT' and any(
                re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', text) for alias in aliases):
            return True
        if f.role == 'STABLE_REFERENCE' and identity.user_id and str(f.value) != identity.user_id:
            return True
    return False


def coverage(fields, *, anonymize=False, tombstone=False):
    """Full identifying-field groups must be observed, not just one null email."""
    names = {f.path.rsplit('.', 1)[-1] for f in fields}
    groups = [{'email', 'customer_email', 'requester_email', 'owner_email'},
              {'phone', 'customer_phone', 'requester_phone', 'owner_phone'}, {'email_hash'}]
    if tombstone:
        groups.append({'name', 'full_name', 'display_name', 'requester_name'})
    if anonymize or tombstone:
        groups.append({'user_id', 'customer_reference', 'subject_reference', 'subject_ref'})
    return all(names & group for group in groups)


class PolicyEvaluator:
    def __init__(self, rules: list[DeletionRule]):
        self.rules = defaultdict(list)
        for rule in sorted(rules, key=lambda r: r.rule_id):
            self.rules[rule.data_category].append(rule)

    def category(self, history, observations):
        typed = [o for o in observations if o.record_type in self.rules or o.record_type == 'DATA_FLOW']
        explicit = {o.record_type for o in latest(typed)}
        schema = COLLECTION_CATEGORIES.get((history.scope.system_id, history.scope.collection))
        if explicit == {'ACCOUNT_TOMBSTONE'} and schema == 'USER_PROFILE' and any(
                str(o.attributes.get('account_status', '')).upper() == 'DELETED' for o in latest(typed)):
            # A current explicitly typed tombstone may occupy a former profile row.
            # Its condition still requires a confirmed permitted stable reference.
            return 'ACCOUNT_TOMBSTONE'
        if schema:
            explicit.add(schema)
        # Service-export object names establish type, not ownership or equivalence
        # with another collection. Phase 2 associations and physical scopes stay intact.
        for o in observations:
            match = re.fullmatch(r'\$\.service_exports\.([\w]+)\.([\w]+)\[\d+\]', o.provenance.locator)
            if match and match[1] == history.scope.system_id:
                category = EXPORT_CATEGORIES.get((match[1], match[2]))
                if category:
                    explicit.add(category)
            if o.attributes.get('event') == 'contact_lookup_completed' and 'email_opt_in' in o.attributes:
                explicit.add('MARKETING_PROFILE')
        if not explicit:
            explicit.update(EVENT_CATEGORIES[o.attributes['event']] for o in observations
                            if o.attributes.get('event') in EVENT_CATEGORIES)
        return next(iter(explicit)) if len(explicit) == 1 else None

    def condition(self, kind, obs, history, bundle):
        a = attributes(obs)
        fields = [f for o in obs for f in o.fields]
        if kind == 'always':
            return True
        if kind == 'shared':
            value = boolean(a.get('shared_context'))
            if value is not None:
                return value
            content = ' '.join(str(f.value) for f in fields if f.role == 'CONTENT')
            return True if a.get('ticket_id') or re.search(
                r'\b(order|agent|shared|delivery|contacted support)\b', content, re.I) else None
        if kind == 'subject_only':
            return boolean(a.get('subject_only'))
        if kind == 'attributable':
            if exposed(fields, bundle.identity, stable=True) or str(a.get('result', '')).upper() == 'IDENTIFIABLE':
                return True
            # A previously applicable anonymization obligation remains verifiable after treatment.
            if history.record.state == 'ANONYMIZED' or coverage(fields, anonymize=True):
                return True
            return None
        if kind == 'email':
            if any(EMAIL.search(str(f.value)) for f in fields if f.representation == 'VALUE'):
                return True
            return True if any('email' in f.path for f in fields) else None
        if kind in {'retention', 'hold'}:
            if kind == 'hold' and boolean(a.get('hold_active')) is False:
                return False
            deadlines = [a[k] for k in ('retention_until', 'retained_until', 'legal_hold_until') if a.get(k)]
            try:
                if deadlines:
                    return max(parse_timestamp(value) for value in deadlines) > bundle.audit_at
            except (TypeError, ValueError):
                return None
            return boolean(a.get('hold_active')) if kind == 'hold' else None
        if kind == 'blockable':
            return True if history.restore.support == 'PROVEN' or boolean(a.get('restore_blockable')) is True else None
        if kind == 'tombstone':
            return True if str(a.get('account_status', '')).upper() == 'DELETED' and any(
                f.role == 'STABLE_REFERENCE' and f.value == bundle.identity.user_id for f in fields) else None
        return None

    def applicable(self, rule, selected, observations, history, bundle):
        kind = CONDITIONS.get(rule.condition)
        current = self.condition(kind, selected, history, bundle)
        if current is not None:
            return current, links_sorted(o.link for o in selected)
        # Missing fields on a later read do not revoke a previously established
        # shared-context/retention obligation. Re-evaluate each historical fact
        # against the case cutoff, never combine old fields into a clean-state proof.
        times = sorted({o.observed_at for o in observations}, reverse=True)
        for at in times:
            earlier = [o for o in observations if o.observed_at == at]
            value = self.condition(kind, earlier, history, bundle)
            if value is not None:
                return value, links_sorted(o.link for o in earlier)
        return None, []

    def evaluate(self, bundle: CaseStateBundle) -> list[PolicyAssessment]:
        results = []
        for h in sorted(bundle.resource_histories, key=lambda h: scope_key(h.scope)):
            observations = supported_observations(h, bundle.audit_at)
            category = self.category(h, observations)
            # A POTENTIAL row can describe a schema, but cannot establish a subject's obligations.
            if not observations:
                results.append(PolicyAssessment(scope=h.scope, dimension='record', category=None,
                    observed_state='UNKNOWN', compliance='UNKNOWN', reasons=['no_confirmed_state_evidence']))
                continue
            if category == 'DATA_FLOW':
                results.append(self.process(h, 'flow', category))
                continue
            if category == 'BACKUP_ARCHIVE':
                results.append(self.process(h, 'restore', category))
            candidates = self.rules.get(category, [])
            selected = latest([o for o in observations if o.link in h.record.supporting_evidence])
            applicability = [(r, *self.applicable(r, selected, observations, h, bundle)) for r in candidates]
            rules = [(r, evidence) for r, applies, evidence in applicability if applies is True]
            if len(rules) != 1:
                # Missing retention applicability cannot justify deletion or COMPLETE.
                # Preserve a known security/legal record in a future INCOMPLETE plan
                # while the retention question is investigated; never assert compliance.
                precaution = candidates[0] if len(candidates) == 1 and candidates[0].required_action == 'RETAIN' else None
                results.append(PolicyAssessment(scope=h.scope, dimension='record', category=category,
                    rule_id=precaution.rule_id if precaution else None,
                    required_action='RETAIN' if precaution else None,
                    required_state='PRESENT' if precaution else None,
                    observed_state=h.record.state, compliance='UNKNOWN', reasons=[
                        'policy_category_unknown' if not candidates else 'policy_condition_unestablished_or_ambiguous']))
                continue
            rule, condition_evidence = rules[0]
            base = dict(scope=h.scope, dimension='record', category=category, rule_id=rule.rule_id,
                        required_action=rule.required_action, required_state=FINAL_STATES[rule.required_action],
                        observed_state=h.record.state, condition_evidence=condition_evidence)
            if h.record.support != 'PROVEN' or not selected:
                results.append(PolicyAssessment(**base, compliance='UNKNOWN', reasons=['record_state_unproven']))
                continue
            compliance, reasons = self.record_compliance(h, selected, rule, bundle)
            results.append(PolicyAssessment(**base, compliance=compliance,
                evidence=links_sorted(o.link for o in selected), reasons=reasons))
        return results

    @staticmethod
    def process(h, dimension, category):
        selection = getattr(h, dimension)
        flow = dimension == 'flow'
        required, bad = ('INACTIVE', 'ACTIVE') if flow else ('BLOCKED', 'ALLOWED')
        compliance = ('UNKNOWN' if selection.support != 'PROVEN' else
                      'VIOLATION' if selection.state == bad else
                      'COMPLIANT' if selection.state == required else 'UNKNOWN')
        return PolicyAssessment(scope=h.scope, dimension=dimension, category=category,
            required_action='DISABLE' if flow else 'BLOCK', required_state='DISABLED' if flow else 'BLOCKED',
            observed_state=selection.state, compliance=compliance,
            evidence=selection.supporting_evidence if selection.support == 'PROVEN' else [],
            reasons=[] if compliance != 'UNKNOWN' else ['process_safety_unproven'])

    @staticmethod
    def record_compliance(h, observations, rule, bundle):
        state, action = h.record.state, rule.required_action
        fields = [f for o in observations for f in o.fields]
        if action == 'DELETE':
            return ('COMPLIANT', []) if state == 'ABSENT' else ('VIOLATION', [])
        if action == 'RETAIN':
            return ('COMPLIANT', []) if state in {'PRESENT', 'REDACTED', 'ANONYMIZED'} else (
                'UNKNOWN', ['required_retained_record_missing_no_supported_recreation_operation'])
        if state == 'ABSENT':
            return 'UNKNOWN', ['required_preserved_record_absent']
        # Existence can agree while field contents conflict at the selected time.
        signatures = defaultdict(set)
        for f in fields:
            signatures[f.path].add((f.representation, str(f.value)))
        if any(len(values) > 1 for values in signatures.values()):
            return 'UNKNOWN', ['conflicting_identifier_fields']
        if exposed(fields, bundle.identity, stable=action == 'ANONYMIZE'):
            return 'VIOLATION', []
        if action == 'ANONYMIZE':
            if state == 'ANONYMIZED' or coverage(fields, anonymize=True):
                return 'COMPLIANT', []
            return 'UNKNOWN', ['anonymization_field_coverage_insufficient']
        tombstone = rule.data_category == 'ACCOUNT_TOMBSTONE'
        if tombstone and not any(f.role == 'STABLE_REFERENCE' and f.value == bundle.identity.user_id for f in fields):
            return 'UNKNOWN', ['permitted_stable_reference_unproven']
        if state == 'REDACTED' or coverage(fields, tombstone=tombstone) or (
                rule.data_category == 'EMAIL_DELIVERY_LOG' and any('email' in f.path for f in fields)):
            return 'COMPLIANT', []
        return 'UNKNOWN', ['redaction_field_coverage_insufficient']
