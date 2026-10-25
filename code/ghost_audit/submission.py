"""Submission prediction: the best-supported official answer for every request.

The strict audit engine (prediction.py) abstains whenever the evidence does not
conclusively establish a result. The official output has no abstention status, so this
module chooses the most defensible COMPLETE/INCOMPLETE/NOT_APPLICABLE answer from the
same participant-visible facts and records how each resource was attributed.

Hard limits, regardless of confidence:
- every resource and citation comes from participant data (no invented IDs);
- a citation is a file captured by audit_at whose contents state the cited fact;
- a resource explicitly owned by another subject is never attributed to this one;
- a workflow result never proves a state; workflow events only attribute resources.
"""

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field

from .extraction import COLLECTION_SYSTEMS, SYSTEM_ALIASES
from .identity import IdentityResolver
from .index import identifier_values, normalize_identifier
from .intent import IntentClassifier
from .output import OPERATIONS, OutputRow, OutputStep, canonical_steps
from .phase2_models import AssociatedObservation, CorrelationLink, ObservationLink
from .sql import TABLE_SYSTEMS
from .temporal_adapters import REPLICA_SUFFIX, interpret, observation_time

# reported_status -> reported_result of the account submission made for that request.
WORKFLOW_RESULT = {'COMPLETE': 'SUCCESS', 'PARTIALLY_COMPLETE': 'PARTIAL', 'NOT_STARTED': 'FAILED'}
# Observed deletion-worker cadence, in minutes before reported_at (negative = after).
ACCOUNT_WINDOW = (40, 80)
POLICY_ACTION_WINDOW = (4, 35)
FINAL_RESULT_WINDOW = (-125, -30)
DIRECT_REPORT_WINDOW = (-15, 15)

SYSTEM_BY_PREFIX = {
    'account': 'account_service', 'search': 'search_service', 'support': 'support_platform',
    'analytics': 'analytics_platform', 'audit_record': 'security_service',
    'data_flow': 'integration_service', 'backup': 'backup_service', 'export': 'export_service',
    'tombstone': 'identity_service', 'cache': 'cache_service', 'marketing': 'marketing_platform',
    'legal_hold': 'legal_service',
}
PREFIX_BY_COLLECTION = {
    'customer_profiles': 'account', 'customer_search_documents': 'search', 'search_documents': 'search',
    'customer_analytics_reports': 'analytics', 'customer_analytics_profiles': 'analytics',
    'support_conversations': 'support', 'support_records': 'support', 'ticket_attachments': 'support',
    'customer_export_jobs': 'export', 'customer_exports': 'export', 'security_audit_events': 'audit_record',
    'security_audit_records': 'audit_record', 'backup_catalog': 'backup', 'backup_restore_entries': 'backup',
    'connector_configurations': 'data_flow', 'connector_subscriptions': 'data_flow',
    'deleted_customer_references': 'tombstone', 'retained_order_records': 'legal_hold',
}
DIRECT_KEYS = {'name', 'full_name', 'display_name', 'requester_name', 'customer_name', 'email', 'phone',
               'email_hash', 'customer_email', 'owner_email', 'requester_email', 'customer_phone',
               'owner_phone', 'requester_phone', 'uploaded_by', 'matched_value'}
STABLE_KEYS = {'user_id', 'customer_reference', 'subject_reference', 'subject_ref'}
# Keys naming what a reader looked for, not what the record contains.
QUERY_KEYS = {'lookup_key', 'correlation_key', 'query', 'match_key', 'subject_key', 'scan_key', 'lookup_value'}
CONTENT_KEYS = {'message_text', 'message_excerpt', 'body', 'notes', 'document_text'}
# Console wording for a connector that is running versus stopped.
FLOW_ACTIVE = re.compile(r'\b(healthy|continuous|events? delivered|running|active)\b', re.I)
FLOW_STOPPED = re.compile(r'\b(disabled|paused|stopped|inactive|suspended)\b', re.I)
RESTORE_BLOCKED = re.compile(r'\b(restore (?:blocked|disabled|denied)|blocked|legal hold|no restore)\b', re.I)
NULLS = {'', 'null', 'none', 'no direct identifier', '[redacted]', 'redacted', '[anonymized]', 'anonymized'}

REMEDIATION = {'DELETE': 'DELETE_RECORD', 'REDACT': 'REDACT_RECORD', 'ANONYMIZE': 'ANONYMIZE_RECORD',
               'DISABLE': 'DISABLE_DATA_FLOW', 'BLOCK': 'BLOCK_RESTORE'}
VERIFICATION = {'DELETE': 'VERIFY_RECORD_ABSENT', 'RETAIN': 'VERIFY_RECORD_PRESENT',
                'REDACT': 'VERIFY_RECORD_REDACTED', 'ANONYMIZE': 'VERIFY_RECORD_ANONYMIZED',
                'DISABLE': 'VERIFY_DATA_FLOW_DISABLED', 'BLOCK': 'VERIFY_RESTORE_BLOCKED'}
FINDING = {'DELETE': 'REPORT_REMAINING_RECORD', 'REDACT': 'REPORT_EXPOSED_PII',
           'ANONYMIZE': 'REPORT_EXPOSED_PII', 'DISABLE': 'REPORT_ACTIVE_DATA_FLOW', 'BLOCK': 'REPORT_RESTORE_RISK'}


def prefix(resource_id: str) -> str:
    return resource_id.rsplit('_', 1)[0]


def minutes(delta) -> float:
    return delta.total_seconds() / 60


def sha256(value: str) -> str:
    return hashlib.sha256(value.strip().casefold().encode()).hexdigest()


def present(value) -> bool:
    return value is not None and not isinstance(value, (dict, list)) and str(value).strip().casefold() not in NULLS


def table_scope(table: str) -> str:
    match = REPLICA_SUFFIX.search(table)
    return match[1] if match else 'table:' + table


@dataclass
class Fact:
    """One interpreted, time-bounded statement about a resource in one evidence file."""
    evidence_id: str
    at: object
    captured_at: object
    scope: str
    verdicts: dict  # action -> 'VIOLATION' | 'COMPLIANT'
    kind: str = 'readback'


@dataclass
class Listing:
    evidence_id: str
    at: object
    captured_at: object
    system: str
    prefix: str
    scope: str
    ids: frozenset


@dataclass
class Resource:
    resource_id: str
    system_id: str
    methods: set = field(default_factory=set)


@dataclass
class CasePrediction:
    case_id: str
    row: OutputRow
    user_id: str | None
    resources: dict
    notes: list[str]
    low_confidence: list[str]


def snapshot_listings(observations) -> dict:
    """(system, resource kind) -> point-in-time collection contents.

    A SQL snapshot table is a full dump of that table at capture time, and a JSON
    snapshot envelope names its data store and collection and lists its records, so
    a resource of that kind missing from either was not in that copy at that time.
    Callers decide which copies are relevant to a case; this only reads contents."""
    tables = {}
    envelopes = {}
    for o in observations:
        if o.kind != 'evidence':
            continue
        p, loc, eid = o.payload, o.provenance.locator, o.provenance.evidence_id
        schema = re.fullmatch(r'sql:(.+):schema', loc)
        row = re.fullmatch(r'sql:(.+):row:\d+', loc)
        if schema and schema[1] != 'snapshot_scope':
            tables.setdefault((eid, schema[1]), {'o': o, 'rows': defaultdict(set)})['o'] = o
        elif row:
            entry = tables.setdefault((eid, row[1]), {'o': o, 'rows': defaultdict(set)})
            for r in o.resources:
                entry['rows'][SYSTEM_ALIASES.get(r.system_id, r.system_id)].add(r.resource_id)
        env = re.fullmatch(r'(\$\.snapshots\[\d+\])', loc)
        rec = re.match(r'(\$\.snapshots\[\d+\])\.records\[\d+\]', loc)
        if env and p.get('data_store') and p.get('collection'):
            envelopes.setdefault((eid, env[1]), {'o': o, 'ids': set()})['o'] = o
        elif rec:
            envelopes.setdefault((eid, rec[1]), {'o': o, 'ids': set()})['ids'].update(
                r.resource_id for r in o.resources)
    listings = defaultdict(list)
    for (eid, table), entry in tables.items():
        o = entry['o']
        at = observation_time(o) or o.provenance.captured_at
        family = REPLICA_SUFFIX.sub('', table)
        dedicated = TABLE_SYSTEMS.get(family) or COLLECTION_SYSTEMS.get(family)
        rows = dict(entry['rows'])
        if dedicated:
            rows.setdefault(dedicated, set())
        for system, ids in rows.items():
            kinds = {prefix(r) for r in ids} or ({PREFIX_BY_COLLECTION[family]} if family in PREFIX_BY_COLLECTION else set())
            for kind in kinds:
                listings[(system, kind)].append(Listing(eid, at, o.provenance.captured_at, system, kind,
                                                        table_scope(table), frozenset(ids)))
    for (eid, _), entry in envelopes.items():
        o = entry['o']
        p = o.payload
        if not p.get('data_store'):
            continue
        system = SYSTEM_ALIASES.get(p['data_store'], p['data_store'])
        kinds = {prefix(r) for r in entry['ids']} or ({PREFIX_BY_COLLECTION[p['collection']]}
                                                      if p['collection'] in PREFIX_BY_COLLECTION else set())
        at = observation_time(o) or o.provenance.captured_at
        for kind in kinds:
            listings[(system, kind)].append(Listing(eid, at, o.provenance.captured_at, system, kind,
                                                    'service:' + o.provenance.origin, frozenset(entry['ids'])))
    return listings


class SubmissionPredictor:
    def __init__(self, dataset):
        self.dataset = dataset
        self.observations = dataset.observations
        self.resolver = IdentityResolver(dataset.identities, dataset.identity_changes)
        self.classifier = IntentClassifier()
        self.requests = list(getattr(dataset, 'workflow_requests', None) or dataset.requests)
        # Required treatment per data category comes from deletion_rules.csv. A retained
        # backup must also be unable to restore the subject; a data flow must be stopped.
        self.required = {rule.data_category: rule.required_action for rule in dataset.rules}
        if 'BACKUP_ARCHIVE' in self.required:
            self.required['BACKUP_ARCHIVE'] = 'BLOCK'
        self.required['DATA_FLOW'] = 'DISABLE'
        self.activities_by_resource = defaultdict(list)
        for a in dataset.activities:
            if a.resource_id:
                self.activities_by_resource[a.resource_id].append(a)
        self._index_identifiers()
        self._index_observations()
        self._index_listings()
        self._index_workflow()

    # ---------------------------------------------------------------- identities
    def _index_identifiers(self):
        values = defaultdict(set)
        names = defaultdict(set)
        for row in self.dataset.identities:
            for value in (row.user_id, row.email, row.phone, row.email_hash):
                if value.strip():
                    values[row.user_id].add(normalize_identifier(value))
            values[row.user_id].add(sha256(row.email))
            names[normalize_identifier(row.name)].add(row.user_id)
        for change in self.dataset.identity_changes:
            for value in (change.old_value, change.new_value):
                if not value.strip():
                    continue
                if change.field_name == 'name':
                    names[normalize_identifier(value)].add(change.user_id)
                    continue
                values[change.user_id].add(normalize_identifier(value))
                if change.field_name == 'email':
                    values[change.user_id].add(sha256(value))
        self.user_values = values
        self.owners_by_value = defaultdict(set)
        for user, items in values.items():
            for value in items:
                self.owners_by_value[value].add(user)
        # A full name links a record only when no other subject has ever used it.
        for name, users in names.items():
            if len(users) == 1:
                self.owners_by_value[name] |= users
                self.user_values[next(iter(users))].add(name)

    def users_in(self, value) -> set[str]:
        found = set()
        for token in identifier_values(value):
            found |= self.owners_by_value.get(token, set())
        return found

    def user_for(self, request):
        identity = self.resolver.resolve(request)
        if identity.status == 'RESOLVED':
            return identity.user_id, None
        owners = self.owners_by_value.get(normalize_identifier(request.email), set())
        if len(owners) == 1:
            return next(iter(owners)), 'identity_resolved_without_cutoff'
        return None, 'identity_unresolved'

    # ---------------------------------------------------------------- evidence
    def _index_observations(self):
        self.by_resource = defaultdict(list)
        groups = defaultdict(list)
        for i, o in enumerate(self.observations):
            if o.kind == 'evidence' and o.trace_id:
                groups[(o.provenance.evidence_id, o.trace_id)].append(i)
        self.obs_users = {}
        self.obs_resources = {}
        self.negative_trace = {}
        for i, o in enumerate(self.observations):
            if o.kind != 'evidence':
                continue
            members = groups.get((o.provenance.evidence_id, o.trace_id), [i]) if o.trace_id else [i]
            self.obs_users[i] = set().union(*(self.users_in(self.observations[j].payload) for j in members))
            self.obs_resources[i] = {r.resource_id for j in members for r in self.observations[j].resources}
            # A lookup by key that found nothing does not tie the key to the resource.
            self.negative_trace[i] = any(self._negative(self.observations[j].payload) for j in members) and \
                not any(self.users_in({k: v for k, v in self.observations[j].payload.items()
                                       if k not in QUERY_KEYS | {'text', 'message'}}) for j in members)
            for r in o.resources:
                self.by_resource[r.resource_id].append(i)
        # resource -> user -> [(available_at, strength)]
        self.explicit = defaultdict(lambda: defaultdict(list))
        for i, users in self.obs_users.items():
            at = self.observations[i].available_at
            if at is None:
                continue
            strength = 'lookup' if self.negative_trace[i] else 'record'
            for resource in self.obs_resources[i]:
                for user in users:
                    self.explicit[resource][user].append((at, strength))
        for a in self.dataset.activities:
            if a.event_type == 'LINK_RESOURCE_IDENTITY' and a.resource_id:
                for user in self.users_in(a.details):
                    self.explicit[a.resource_id][user].append((a.event_time, 'catalog'))

    @staticmethod
    def _negative(payload) -> bool:
        data = payload.get('decoded_record') if isinstance(payload.get('decoded_record'), dict) else payload
        return (str(data.get('result', '')).upper() in {'NOT_FOUND', 'MISS'} or
                str(data.get('http_status', data.get('status_code', ''))) == '404' or str(data.get('rows', '')) == '0')

    def owners(self, resource_id: str, cutoff=None, strong=False) -> set[str]:
        return {user for user, links in self.explicit.get(resource_id, {}).items()
                if any((cutoff is None or at <= cutoff) and (not strong or kind != 'lookup') for at, kind in links)}

    def system_of(self, resource_id: str) -> str | None:
        systems = defaultdict(int)
        for i in self.by_resource.get(resource_id, ()):
            for r in self.observations[i].resources:
                if r.resource_id == resource_id and r.system_id:
                    systems[SYSTEM_ALIASES.get(r.system_id, r.system_id)] += 1
        for a in self.activities_by_resource.get(resource_id, ()):
            if a.source_system == 'deletion_worker' and a.target_system:
                systems[a.target_system] += 1
        if systems:
            return max(sorted(systems), key=systems.get)
        return SYSTEM_BY_PREFIX.get(prefix(resource_id))

    def _index_listings(self):
        self.listings = snapshot_listings(self.observations)

    # ---------------------------------------------------------------- workflow
    def _index_workflow(self):
        deleting = [r for r in self.requests if self.classifier.classify(r).decision == 'DELETE_INTENT']
        users = {r.case_id: self.user_for(r)[0] for r in self.requests}
        self.request_user = users
        worker = [a for a in self.dataset.activities if a.source_system == 'deletion_worker']
        submissions = [a for a in worker if 'submitted primary profile' in a.details]
        submitted = {a.resource_id for a in submissions}

        def explicit_kinds(r):
            return {prefix(res) for res, owners in self.explicit.items()
                    if users[r.case_id] in self.owners(res, r.audit_at, strong=True)}

        kinds = {r.case_id: explicit_kinds(r) for r in deleting}
        # 1. Primary profile submissions: one per request, ~1h before reported_at, with the
        # submission result mirroring the reported status. Solved as a constrained matching.
        candidates = {}
        for r in deleting:
            options = set()
            for a in submissions:
                lag = minutes(r.reported_at - a.event_time)
                if not (ACCOUNT_WINDOW[0] <= lag <= ACCOUNT_WINDOW[1]):
                    continue
                if a.reported_result != WORKFLOW_RESULT.get(r.reported_status):
                    continue
                owners = self.owners(a.resource_id, strong=True)
                if owners and users[r.case_id] not in owners:
                    continue  # contradicted by an explicit owner
                options.add(a.resource_id)
            own = {o for o in options if any(kind != 'lookup' or at >= r.requested_at
                                             for at, kind in self.explicit.get(o, {}).get(users[r.case_id], ()))}
            candidates[r.case_id] = own if len(own) == 1 else options
        self._propagate(candidates)
        self.account_candidates = candidates
        # An account submitted in some other request's batch is not this subject's merely
        # because an old lookup by this subject's key touched it.
        self.batch_owner = {next(iter(v)): k for k, v in candidates.items() if len(v) == 1}
        self.submitted = submitted
        # Hand-written workflow reports name their target at reporting time.
        self.direct_reports = defaultdict(set)
        for a in worker:
            if 'Target resource:' not in a.details:
                continue
            near = [r for r in deleting
                    if DIRECT_REPORT_WINDOW[0] <= minutes(r.reported_at - a.event_time) <= DIRECT_REPORT_WINDOW[1]]
            if len(near) == 1:
                self.direct_reports[near[0].case_id].add(a.resource_id)
        # 2. Downstream policy actions and final results belong to the batch reported just
        # after (actions) or just before (final results) them. A request that already has
        # an explicitly owned record of the same kind is not a candidate for another one.
        self.downstream = defaultdict(set)
        self.downstream_ambiguous = defaultdict(set)
        for a in worker:
            if a in submissions or 'Target resource:' in a.details:
                continue
            if a.details.startswith('Policy action completed'):
                window = POLICY_ACTION_WINDOW
            elif 'final result' in a.details or a.event_type in {'CHECK_DATA_FLOW', 'CHECK_RESTORE_ACCESS'}:
                window = FINAL_RESULT_WINDOW
            else:
                continue
            batch = [r for r in deleting if window[0] <= minutes(r.reported_at - a.event_time) <= window[1]]
            owners = self.owners(a.resource_id, strong=True)
            if owners:
                batch = [r for r in batch if users[r.case_id] in owners]
            else:
                # A request that already owns a record of this kind is not a candidate for
                # an unlabelled one; with no other candidate the record stays unattributed.
                batch = [r for r in batch if prefix(a.resource_id) not in kinds[r.case_id]]
            if len(batch) == 1:
                self.downstream[batch[0].case_id].add(a.resource_id)
            else:
                for r in batch:
                    self.downstream_ambiguous[r.case_id].add(a.resource_id)

    @staticmethod
    def _propagate(candidates):
        changed = True
        while changed:
            changed = False
            for case_id, options in candidates.items():
                if len(options) != 1:
                    continue
                (account,) = options
                for other, values in candidates.items():
                    if other != case_id and account in values and len(values) > 1:
                        values.discard(account)
                        changed = True

    # ---------------------------------------------------------------- facts
    def facts(self, resource_id: str, user: str):
        """Interpreted readbacks of one resource, with the record category signals."""
        result, signals = [], {'events': set(), 'types': set(), 'collections': set(), 'keys': set(), 'documents': set()}
        user_values = self.user_values.get(user, set())
        for i in self.by_resource.get(resource_id, ()):
            o = self.observations[i]
            refs = [r for r in o.resources if r.resource_id == resource_id]
            if not refs or o.available_at is None:
                continue
            if self.obs_users[i] and user not in self.obs_users[i] and not self.negative_trace[i]:
                continue  # a same-ID readback naming only another subject never describes this one
            item = AssociatedObservation(
                observation=o, association='CONFIRMED', reason='submission_resource_identity',
                links=[CorrelationLink(method='RESOURCE', supporting_observations=[ObservationLink.of(o)])])
            t = interpret(item, refs[0])
            data = o.payload.get('decoded_record') if isinstance(o.payload.get('decoded_record'), dict) else o.payload
            signals['events'].add(str(o.payload.get('event', '')))
            signals['types'].add(str(data.get('record_type') or '').upper())
            signals['collections'].add(str(refs[0].collection or ''))
            signals['keys'].update(data)
            if t.category == 'DOCUMENT':
                signals['documents'].add(o.provenance.file_path)
            if t.support in {'CLAIM_ONLY', 'UNKNOWN'} and t.category != 'DOCUMENT':
                continue
            if t.category == 'DOCUMENT':
                t = self._document_state(t, data, resource_id)
            verdicts = self._verdicts(t, data, user_values)
            if verdicts:
                result.append(Fact(o.provenance.evidence_id, observation_time(o) or o.available_at,
                                   o.available_at, t.scope.replica_scope, verdicts))
        return result, signals

    @staticmethod
    def _document_state(t, data, resource_id):
        """A console or business document rendering a connector or archive states its
        operating status in words; no status words leave the dimension unknown."""
        text = str(data.get('document_text', ''))
        update = {}
        if prefix(resource_id) == 'data_flow':
            if FLOW_STOPPED.search(text):
                update['flow_state'] = 'INACTIVE'
            elif FLOW_ACTIVE.search(text):
                update['flow_state'] = 'ACTIVE'
        if prefix(resource_id) == 'backup' and re.search(r'archive|\.tar|path', text, re.I):
            update['restore_state'] = 'BLOCKED' if RESTORE_BLOCKED.search(text) else 'ALLOWED'
        return t.model_copy(update=update) if update else t

    def _verdicts(self, t, data, user_values) -> dict:
        verdicts = {}
        direct, stable, subject = self._exposure(data, user_values)
        if t.flow_state != 'UNKNOWN':
            verdicts['DISABLE'] = 'VIOLATION' if t.flow_state == 'ACTIVE' else 'COMPLIANT'
        if t.restore_state != 'UNKNOWN':
            verdicts['BLOCK'] = 'VIOLATION' if t.restore_state == 'ALLOWED' else 'COMPLIANT'
        record = t.record_state
        if record == 'ABSENT':
            # A missing retained record has no remediation operation; it stays unproven.
            verdicts.update(DELETE='COMPLIANT')
            verdicts.setdefault('BLOCK', 'COMPLIANT')
        elif record in {'PRESENT', 'REDACTED', 'ANONYMIZED'}:
            verdicts.update(DELETE='VIOLATION', RETAIN='COMPLIANT')
            exposed_direct = bool(direct) or subject
            if exposed_direct or str(data.get('result', '')).upper() == 'IDENTIFIABLE':
                verdicts.update(REDACT='VIOLATION', ANONYMIZE='VIOLATION')
            else:
                if record == 'REDACTED' or direct is False:
                    verdicts['REDACT'] = 'COMPLIANT'
                if stable:
                    verdicts['ANONYMIZE'] = 'VIOLATION'
                elif record == 'ANONYMIZED' or (direct is False and stable is False):
                    verdicts['ANONYMIZE'] = 'COMPLIANT'
        return verdicts

    @staticmethod
    def _exposure(data, user_values):
        """(direct identifier present, stable reference present, a subject value present)."""
        direct = stable = None
        subject = False

        def visit(value, key=None):
            nonlocal direct, stable, subject
            if isinstance(value, dict):
                for k, v in value.items():
                    if k not in {'record_json', 'text', 'message'} | QUERY_KEYS:
                        visit(v, k)
            elif isinstance(value, list):
                for v in value:
                    visit(v, key)
            elif key in DIRECT_KEYS:
                has = present(value)
                direct = bool(direct) or has
                # Only a direct identifier exposes the subject; a stable internal
                # reference is what redaction and tombstones are allowed to keep.
                if has and identifier_values(value) & user_values:
                    subject = True
            elif key in STABLE_KEYS:
                stable = bool(stable) or present(value)
            elif key in CONTENT_KEYS and isinstance(value, str):
                direct_values = {v for v in user_values if not v.startswith('user_')}
                if identifier_values(value) & direct_values or any(
                        v in value.casefold() for v in direct_values if '@' in v or ' ' in v):
                    subject = True
        visit(data)
        flag = str(data.get('direct_identifiers', '')).casefold() if isinstance(data, dict) else ''
        if flag in {'present', 'true', '1', 'yes'}:
            direct = True
        elif flag in {'absent', 'false', '0', 'none', 'no'} and direct is None:
            direct = False
        return direct, stable, subject

    # ---------------------------------------------------------------- policy
    def category(self, resource_id: str, signals: dict) -> str:
        kind = prefix(resource_id)
        # A source that names the record's data category is authoritative.
        named = sorted(t for t in signals['types'] if t in self.required and t != 'BACKUP_ARCHIVE')
        if len(named) == 1:
            return named[0]
        fixed = {'account': 'USER_PROFILE', 'search': 'SEARCH_INDEX_ENTRY', 'cache': 'CACHE_ENTRY',
                 'export': 'USER_EXPORT', 'marketing': 'MARKETING_PROFILE', 'audit_record': 'SECURITY_AUDIT_LOG',
                 'legal_hold': 'LEGAL_HOLD_RECORD', 'backup': 'BACKUP_ARCHIVE', 'tombstone': 'ACCOUNT_TOMBSTONE',
                 'data_flow': 'DATA_FLOW', 'email_delivery': 'EMAIL_DELIVERY_LOG', 'telemetry': 'PRODUCT_TELEMETRY'}
        if kind in fixed:
            return fixed[kind]
        if kind == 'object' and any('belongs only to' in a.details for a in self.activities_by_resource.get(resource_id, ())):
            return 'SUPPORT_ATTACHMENT'
        if kind == 'analytics':
            # A contact record carrying a marketing opt-in is a marketing profile kept
            # on the analytics platform, not an attributable analytics report.
            if 'contact_lookup_completed' in signals['events'] or 'email_opt_in' in signals['keys']:
                return 'MARKETING_PROFILE'
            return 'ANALYTICS_PROFILE'
        if kind == 'support':
            catalogued = any('Attachment catalog' in a.details and 'belongs only to' in a.details
                             for a in self.activities_by_resource.get(resource_id, ()))
            if ('SUPPORT_ATTACHMENT' in signals['types'] or 'attachment_pii_scan' in signals['events']
                    or 'ticket_attachments' in signals['collections'] or catalogued
                    or any(path.endswith('.pdf') for path in signals['documents'])
                    or {'file_name', 'file', 'storage_class'} & signals['keys']):
                return 'SUPPORT_ATTACHMENT'
            # A deletion-marker check is the source's own statement that this record
            # (a legacy contact entry, not a shared conversation) is due for deletion.
            if 'deletion_marker_check' in signals['events']:
                return 'SUPPORT_ATTACHMENT'
            return 'SUPPORT_MESSAGE'
        return 'UNKNOWN'

    def listing_facts(self, resource_id: str, system_id: str):
        facts = []
        for item in self.listings.get((system_id, prefix(resource_id)), ()):
            absent = resource_id not in item.ids
            if absent:
                verdicts = {'DELETE': 'COMPLIANT'}
                facts.append(Fact(item.evidence_id, item.at, item.captured_at, item.scope, verdicts, 'listing'))
        return facts

    @staticmethod
    def assess(action: str, facts: list[Fact]):
        """The state at the latest evidence file: any violating replica in it wins."""
        relevant = [f for f in facts if action in f.verdicts]
        if not relevant:
            return 'UNKNOWN', None
        newest = max(f.at for f in relevant)
        files = {f.evidence_id for f in relevant if f.at == newest}
        current = [f for f in relevant if f.evidence_id in files]
        # Readbacks of the same file outrank its listings for the same scope.
        readbacks = {f.scope for f in current if f.kind == 'readback'}
        current = [f for f in current if f.kind == 'readback' or f.scope not in readbacks]
        violations = [f for f in current if f.verdicts[action] == 'VIOLATION']
        chosen = violations or current
        best = max(chosen, key=lambda f: (f.at, f.kind == 'readback', f.evidence_id))
        return ('VIOLATION' if violations else 'COMPLIANT'), best

    # ---------------------------------------------------------------- prediction
    def resources_for(self, request, user):
        audit_at = request.audit_at
        resources = {}
        notes = []

        def add(resource_id, method):
            system = self.system_of(resource_id)
            if system is None:
                return
            resources.setdefault(resource_id, Resource(resource_id, system)).methods.add(method)

        accounts = self.account_candidates.get(request.case_id, set())
        batch_account = next(iter(accounts)) if len(accounts) == 1 else None
        for resource_id, owners in self.explicit.items():
            links = owners.get(user)
            if not links:
                continue
            strong = [at for at, kind in links if kind != 'lookup']
            if prefix(resource_id) == 'account' and not strong:
                other = self.batch_owner.get(resource_id)
                if other and other != request.case_id or batch_account and batch_account != resource_id:
                    notes.append('ignored_lookup_only_account:' + resource_id)
                    continue
            retained = prefix(resource_id) in {'audit_record', 'legal_hold'}
            if not retained and all(at < request.requested_at for at, _ in links) and not any(
                    request.requested_at <= f.captured_at <= audit_at for f in self.facts(resource_id, user)[0]):
                # Seen only before the request: earlier context, not the state the request changed.
                notes.append('pre_request_context_only:' + resource_id)
                continue
            early = any(at <= audit_at for at, _ in links)
            add(resource_id, 'explicit_identifier' if early else 'explicit_identifier_after_audit')
        if batch_account:
            add(batch_account, 'workflow_batch_unique')
        elif accounts:
            notes.append('ambiguous_workflow_account:' + ','.join(sorted(accounts)))
        for resource_id in self.direct_reports.get(request.case_id, ()):
            owners = self.owners(resource_id, strong=True)
            if not owners or user in owners:
                add(resource_id, 'workflow_direct_report')
        for resource_id in self.downstream.get(request.case_id, ()):
            add(resource_id, 'workflow_batch_downstream')
        ambiguous = self.downstream_ambiguous.get(request.case_id, set()) - set(resources)
        if ambiguous:
            notes.append('ambiguous_workflow_downstream:' + ','.join(sorted(ambiguous)))
        return resources, notes

    def predict_case(self, request) -> CasePrediction:
        intent = self.classifier.classify(request)
        if intent.decision == 'NO_DELETE_INTENT':
            return CasePrediction(request.case_id, OutputRow(case_id=request.case_id,
                                  deletion_status='NOT_APPLICABLE', steps=[]), None, {}, [], [])
        user, identity_note = self.user_for(request)
        notes = [n for n in (identity_note,) if n]
        if intent.decision != 'DELETE_INTENT':
            notes.append('uncertain_intent_treated_as_deletion')
        if user is None:
            raise ValueError(f'{request.case_id}: subject cannot be identified from participant data')
        resources, resource_notes = self.resources_for(request, user)
        notes.extend(resource_notes)
        audit_at = request.audit_at
        assessments = []
        gathered = {r.resource_id: self.facts(r.resource_id, user) for r in resources.values()}
        case_files = {f.evidence_id for facts, _ in gathered.values() for f in facts}
        for resource in sorted(resources.values(), key=lambda r: (r.system_id, r.resource_id)):
            facts, signals = gathered[resource.resource_id]
            category = self.category(resource.resource_id, signals)
            action = self.required.get(category)
            if action is None:
                notes.append('unsupported_category:' + resource.resource_id)
                continue
            if action == 'DELETE':
                # Snapshot contents prove absence only in a file that captured this case's
                # other records; a file about unrelated subjects is not a full inventory.
                listed = self.listing_facts(resource.resource_id, resource.system_id)
                own = [f for f in listed if f.evidence_id in case_files]
                if not own and not facts:
                    own = listed
                    if own:
                        notes.append('absence_from_unlinked_snapshot:' + resource.resource_id)
                facts = facts + own
            # The request is judged on what was observed after it was made, up to audit_at.
            visible = [f for f in facts if request.requested_at <= f.captured_at <= audit_at and f.at <= audit_at]
            verdict, fact = self.assess(action, visible)
            assessments.append([resource, category, action, verdict, fact, facts])
        if assessments and all(a[3] == 'UNKNOWN' for a in assessments):
            # Nothing observed since the request: the latest state known by audit_at is the
            # best available evidence of what the request still has to change.
            for a in assessments:
                a[3], a[4] = self.assess(a[2], [f for f in a[5] if f.captured_at <= audit_at and f.at <= audit_at])
            notes.append('state_from_pre_request_evidence')
        assessments = [tuple(a[:5]) for a in assessments]
        steps = []
        violations = [a for a in assessments if a[3] == 'VIOLATION']
        low = [a[0].resource_id for a in assessments if a[3] == 'UNKNOWN']
        # Ambiguous attributions stay out of the steps; record whether any viable
        # assignment would change the status conclusion.
        candidates = sorted({c for n in notes if n.startswith('ambiguous_workflow_')
                             for c in n.split(':', 1)[1].split(',')} - set(resources))
        flips = []
        for resource_id in candidates:
            facts, signals = self.facts(resource_id, user)
            action = self.required.get(self.category(resource_id, signals))
            if action is None:
                continue
            visible = [f for f in facts if request.requested_at <= f.captured_at <= audit_at and f.at <= audit_at]
            if self.assess(action, visible)[0] == 'VIOLATION':
                flips.append(resource_id)
        if flips and not violations:
            notes.append('status_depends_on_ambiguous_attribution:' + ','.join(flips))
            low.extend(flips)
        if violations:
            status = 'INCOMPLETE'
            for resource, category, action, verdict, fact in violations:
                steps.append(self.step(resource, FINDING[action], fact.evidence_id))
                steps.append(self.step(resource, REMEDIATION[action]))
            for resource, category, action, verdict, fact in assessments:
                steps.append(self.step(resource, VERIFICATION[action]))
        else:
            proven = [a for a in assessments if a[3] == 'COMPLIANT']
            if not proven:
                raise ValueError(f'{request.case_id}: no provable resource state at audit_at')
            status = 'COMPLETE'
            for resource, category, action, verdict, fact in proven:
                steps.append(self.step(resource, VERIFICATION[action], fact.evidence_id))
        row = OutputRow(case_id=request.case_id, deletion_status=status, steps=canonical_steps(self.unique(steps)))
        return CasePrediction(request.case_id, row, user,
                              {r.resource_id: sorted(r.methods) for r, *_ in assessments}, notes, low)

    @staticmethod
    def unique(steps):
        seen = {}
        for s in steps:
            seen.setdefault((s.operation, s.system_id, s.resource_id), s)
        return list(seen.values())

    @staticmethod
    def step(resource, operation, evidence_id=''):
        phase, state = OPERATIONS[operation]
        return OutputStep(step_no=1, phase=phase, system_id=resource.system_id, resource_id=resource.resource_id,
                          operation=operation, state=state, evidence_id=evidence_id)


def predict_submission(dataset) -> list[CasePrediction]:
    """One prediction per request, sorted by case_id. Raises if any case is unsupported."""
    predictor = SubmissionPredictor(dataset)
    cases, unresolved = [], []
    for request in sorted(dataset.requests, key=lambda r: r.case_id):
        try:
            cases.append(predictor.predict_case(request))
        except ValueError as exc:
            unresolved.append(str(exc))
    if unresolved:
        raise ValueError(f'{len(unresolved)} cases cannot be represented without unsupported findings or '
                         'verifications: ' + '; '.join(unresolved))
    return cases


def submission_diagnostics(cases: list[CasePrediction]) -> dict:
    """Identifier-only provenance of every prediction: attribution methods, ambiguity and
    low-confidence resources. Kept separate from the official CSV."""
    from collections import Counter

    statuses = Counter(c.row.deletion_status for c in cases)
    notes = Counter(n.split(':', 1)[0] for c in cases for n in c.notes)
    methods = Counter(m for c in cases for values in c.resources.values() for m in values)
    return {
        'summary': {
            'cases': len(cases),
            'status_counts': {s: statuses[s] for s in ('COMPLETE', 'INCOMPLETE', 'NOT_APPLICABLE')},
            'steps': sum(len(c.row.steps) for c in cases),
            'attribution_methods': dict(sorted(methods.items())),
            'inference_notes': dict(sorted(notes.items())),
            'cases_with_low_confidence_resources': sum(bool(c.low_confidence) for c in cases),
            'status_depends_on_ambiguous_attribution': sorted(
                c.case_id for c in cases if any(n.startswith('status_depends_on_ambiguous') for n in c.notes)),
        },
        'cases': [{'case_id': c.case_id, 'status': c.row.deletion_status, 'user_id': c.user_id,
                   'resources': c.resources, 'notes': c.notes, 'low_confidence': sorted(set(c.low_confidence))}
                  for c in cases],
    }
