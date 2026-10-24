"""Small schema adapters over already parsed participant observations.

Null fields describe representations, never policy compliance. Readbacks, snapshots,
operation claims, flow configuration, and restore permissions are distinct facts.
"""

import re
from pathlib import PurePosixPath

from .models import Observation, ResourceRef
from .phase2_models import AssociatedObservation
from .sql import TABLE_SYSTEMS
from .temporal_models import FieldObservation, ResourceScope, TemporalObservation

REPLICA_SUFFIX = re.compile(
    r'_(primary|read_replica|regional_replica(?:_[a-z0-9_]+)?|reporting_replica|'
    r'failover_replica|replica(?:_[a-z0-9_]+)?)$')
DIRECT_FIELDS = {'name', 'full_name', 'display_name', 'requester_name', 'customer_name',
                 'email', 'phone', 'email_hash', 'customer_email', 'owner_email',
                 'requester_email', 'customer_phone', 'owner_phone', 'requester_phone'}
STABLE_FIELDS = {'user_id', 'customer_reference', 'subject_reference', 'subject_ref'}
CONTENT_FIELDS = {'message_text', 'message_body', 'message_excerpt', 'body', 'notes', 'matched_value'}
REDACTED = {'[redacted]', 'redacted'}
ANONYMIZED = {'[anonymized]', 'anonymized', 'anonymous'}
NULL = {'null', 'none', ''}
OBSERVABLE_ATTRIBUTES = {
    'enabled', 'restore_allowed', 'archive_present', 'eligible', 'deletion_block',
    'decision', 'scheduler_registered', 'connector_name', 'destination', 'mode',
    'source_system', 'target_system', 'retention_until', 'account_status',
    'direct_identifiers', 'query_scope', 'rows', 'http_status', 'status_code',
    'total_hits', 'result', 'observed_state', 'event', 'reported_result', 'event_type',
}

# Only established schema families may equate physical replica tables. Generic
# customer_data_* tables need their explicit collection_name; no ID-prefix joins.
def logical_collection(reference: ResourceRef) -> str | None:
    collection = reference.collection
    if collection and reference.physical_table == collection:
        base = REPLICA_SUFFIX.sub('', collection)
        if base in TABLE_SYSTEMS:
            return base
    return collection


def replica_scope(observation: Observation, reference: ResourceRef) -> str:
    p = observation.payload
    explicit = p.get('replica_scope') or p.get('replica') or p.get('source_scope')
    if isinstance(explicit, str) and explicit:
        return explicit
    if reference.physical_table:
        match = REPLICA_SUFFIX.search(reference.physical_table)
        return match[1] if match else 'table:' + reference.physical_table
    # Region denotes a distinct read surface; never erase another region's state.
    region = p.get('region')
    source = 'service:' + observation.provenance.origin
    return source + ':' + str(region) if region else source


def observation_time(o: Observation):
    """A snapshot's clock is not row updated_at or a later packaging/export clock."""
    times = [t for t in o.provenance.timestamps if t.role == 'source']
    clocks = [t for t in times if t.field.lower() in {
        'observed_at', 'recorded_at', 'event_time', 'timestamp', 'snapshot',
        'snapshot_at', 'captured_at'}]
    if clocks:
        # Deeper scoped clocks describe the actual observation, not its envelope.
        depth = max(t.locator.rsplit('.', 1)[0].count('.') + t.locator.count('[') for t in clocks)
        deepest = [t for t in clocks
                   if t.locator.rsplit('.', 1)[0].count('.') + t.locator.count('[') == depth]
        # An explicit observation clock wins over incidental metadata at its scope.
        priorities = {'observed_at': 3, 'recorded_at': 3, 'event_time': 3, 'timestamp': 3,
                      'snapshot': 2, 'snapshot_at': 2, 'captured_at': 2}
        priority = max(priorities[t.field.lower()] for t in deepest)
        return max(t.value for t in deepest if priorities[t.field.lower()] == priority)
    return o.provenance.captured_at or o.available_at


def boolean(value):
    if value is True or type(value) is int and value == 1 or value in ('true', '1'):
        return True
    if value is False or type(value) is int and value == 0 or value in ('false', '0'):
        return False
    return None


def integer(value):
    # bool is deliberately not a row count.
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r'\d+', value):
        return int(value)
    return None


def field_observations(payload: dict) -> list[FieldObservation]:
    result = []

    def visit(value, path=''):
        if isinstance(value, dict):
            for key, child in sorted(value.items()):
                child_path = f'{path}.{key}' if path else key
                role = ('DIRECT_IDENTIFIER' if key in DIRECT_FIELDS else
                        'STABLE_REFERENCE' if key in STABLE_FIELDS else
                        'CONTENT' if key in CONTENT_FIELDS else None)
                if role and not isinstance(child, (dict, list)):
                    text = child.casefold().strip() if isinstance(child, str) else None
                    representation = ('NULL' if child is None or text in NULL else
                                      'REDACTED' if text in REDACTED else
                                      'ANONYMIZED' if text in ANONYMIZED else 'VALUE')
                    result.append(FieldObservation(path=child_path, role=role,
                                                   representation=representation, value=child))
                elif key not in {'record_json', 'text', 'message'}:
                    visit(child, child_path)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                visit(child, f'{path}[{i}]')

    visit(payload)
    return result


def interpret(item: AssociatedObservation, reference: ResourceRef) -> TemporalObservation:
    o = item.observation
    # Preserve wrapper provenance, but do not count the encoded copy twice.
    p = o.payload
    data = p.get('decoded_record') if isinstance(p.get('decoded_record'), dict) else p
    fields = field_observations(data)
    event = str(p.get('event', '')).lower()
    result = str(data.get('result', '')).upper()
    record_type = data.get('record_type') or data.get('account_status')
    record = flow = restore = 'UNKNOWN'
    category = 'UNINTERPRETED'
    reason = 'no_supported_state_semantics'
    conflicts = []
    claim = o.kind == 'activity_claim' or bool(p.get('reported_result')) or bool(
        re.search(r'(?:delete|restore|sync|redact|anonymize|workflow|purge)_(?:completed|result|success)$', event))
    suffix = PurePosixPath(o.provenance.file_path).suffix.lower()
    snapshot = bool(reference.physical_table) or (
        suffix == '.json' and bool(reference.collection) and not event and
        not any(k in data for k in ('result', 'status_code', 'http_status', 'hits')))
    resource_read = (event.endswith(('_lookup_completed', '_read_completed', '_query_completed'))
                     or event in {'record_lookup', 'analytics_profile_read', 'message_read',
                                  'retained_order_loaded', 'message_pii_scan',
                                  'attachment_pii_scan', 'analytics_identity_scan'})
    structured_read = bool(data.get('record_type') and 'result' in data and
                           any(k in data for k in ('recorded_at', 'observed_at', 'timestamp')))
    json_read = suffix == '.json' and any(k in data for k in ('status_code', 'hits', 'observed_at'))
    config_read = event in {'connector_heartbeat', 'connector_config_loaded',
                           'restore_candidate_evaluated', 'restore_authorization_completed'}
    status = integer(data.get('http_status', data.get('status_code')))
    failed_read = status is not None and status >= 400 and status != 404
    if claim:
        category, reason = 'OPERATION_CLAIM', 'operation_result_is_not_a_resource_readback'
        operation = str(p.get('event_type', event)).upper()
        successful = str(p.get('reported_result', p.get('result', 'SUCCESS'))).upper() == 'SUCCESS'
        if 'DELETE' in operation and successful:
            record = 'ABSENT'
        elif successful and any(word in operation for word in ('RESTORE', 'SYNC', 'IMPORT')):
            record = 'PRESENT'
    elif failed_read:
        reason = 'failed_read_does_not_establish_resource_state'
    elif snapshot or resource_read or structured_read or json_read or config_read:
        category = ('SNAPSHOT' if snapshot else
                    'SERVICE_READBACK' if structured_read else 'RESOURCE_READBACK')
        reason = 'explicit_snapshot_contents' if snapshot else 'explicit_resource_readback'
        rows = integer(data.get('rows'))
        hit_response = data.get('hits')
        hits = hit_response
        hits = hits.get('total') if isinstance(hits, dict) else data.get('total_hits')
        if isinstance(hits, dict):
            hits = hits.get('value')
        hits = integer(hits)
        search = event == 'index_query_completed' or 'hits' in data
        query = data.get('query')
        exact_search = (data.get('query_scope') == 'RESOURCE_ID' or
                        data.get('query_resource_id') == reference.resource_id or
                        isinstance(query, dict) and query.get('resource_id') == reference.resource_id)
        negative = result == 'NOT_FOUND' or status == 404 or rows == 0 or hits == 0
        positive = (snapshot or result in {'FOUND', 'HIT', 'IDENTIFIABLE', 'REDACTED', 'ANONYMIZED'}
                    or rows is not None and rows > 0 or status == 200 and not negative
                    or hits is not None and hits > 0)
        if isinstance(hit_response, dict) and isinstance(hit_response.get('documents'), list):
            documents = hit_response['documents']
            if not any(isinstance(doc, dict) and doc.get('resource_id') == reference.resource_id
                       for doc in documents):
                positive = False
                reason = 'search_documents_do_not_establish_this_resource'
        if negative and (not search or exact_search):
            record = 'ABSENT'
        elif negative:
            reason = 'negative_search_lacks_explicit_resource_query_scope'
        elif positive:
            record = 'PRESENT'
        elif not search and (resource_read or json_read or config_read) and (
            fields or any(k in data for k in ('enabled', 'archive_present')) or
            event in {'message_pii_scan', 'attachment_pii_scan', 'analytics_identity_scan'}):
            record = 'PRESENT'
        if negative and positive:
            conflicts.append('contradictory_presence_readback')
        if result in {'REDACTED', 'ANONYMIZED'}:
            record = result
        elif str(data.get('observed_state', '')).upper() in {'REDACTED', 'ANONYMIZED'}:
            record = str(data['observed_state']).upper()
        elif any(f.representation == 'REDACTED' for f in fields) and record == 'PRESENT':
            # An explicit marker is evidence of field redaction, not all-field removal.
            # Keep PRESENT; the fields carry the precise extent of redaction.
            reason = 'present_record_with_explicit_field_redactions'

        enabled = boolean(data.get('enabled'))
        if enabled is not None:
            flow = 'ACTIVE' if enabled else 'INACTIVE'
        if record_type == 'DATA_FLOW' and result in {'ACTIVE', 'DISABLED'}:
            flow = 'ACTIVE' if result == 'ACTIVE' else 'INACTIVE'
        allowed = boolean(data.get('restore_allowed'))
        blocked = boolean(data.get('deletion_block'))
        decision = str(data.get('decision', '')).lower()
        if allowed is not None:
            restore = 'ALLOWED' if allowed else 'BLOCKED'
        elif blocked is True or decision == 'deny':
            restore = 'BLOCKED'
        elif decision == 'allow' or (boolean(data.get('eligible')) is True and blocked is False):
            restore = 'ALLOWED'
        restore_signals = ({'ALLOWED' if allowed else 'BLOCKED'} if allowed is not None else set())
        if blocked is True or decision == 'deny':
            restore_signals.add('BLOCKED')
        if decision == 'allow':
            restore_signals.add('ALLOWED')
        if len(restore_signals) > 1:
            conflicts.append('restore_configuration_fields_disagree')
        if record_type == 'BACKUP_ARCHIVE' and result in {'FOUND', 'ACTIVE', 'BLOCKED'}:
            record = 'PRESENT'
            if result == 'BLOCKED':
                restore = 'BLOCKED'
        # Restore authorization is independent of archive existence.
        if any(k in data for k in ('archive_path', 'archive_key', 'object_key')) or boolean(data.get('available')) is True:
            record = 'PRESENT'
        if boolean(data.get('archive_present')) is False:
            if record == 'PRESENT':
                conflicts.append('archive_existence_fields_disagree')
            record = 'ABSENT'
        elif boolean(data.get('archive_present')) is True:
            record = 'PRESENT'

    exposed = any(f.role == 'DIRECT_IDENTIFIER' and f.representation == 'VALUE' for f in fields)
    linked = any(f.role == 'STABLE_REFERENCE' and f.representation == 'VALUE' for f in fields)
    if record in {'REDACTED', 'ANONYMIZED'} and (exposed or record == 'ANONYMIZED' and linked):
        conflicts.append('state_label_contradicts_observed_identity_fields')
    support = ('CLAIM_ONLY' if claim else 'PROVEN' if category != 'UNINTERPRETED' and
               (record != 'UNKNOWN' or flow != 'UNKNOWN' or restore != 'UNKNOWN') else 'UNKNOWN')
    if conflicts:
        support = 'CONFLICTED'
    if item.association != 'CONFIRMED' or not item.links:
        support = 'UNKNOWN'
        reason = 'potential_or_unsupported_ownership; ' + reason
    return TemporalObservation(
        scope=ResourceScope(resource_id=reference.resource_id, system_id=reference.system_id,
                            collection=logical_collection(reference), replica_scope=replica_scope(o, reference)),
        physical_table=reference.physical_table, observed_at=observation_time(o),
        available_at=o.available_at, provenance=o.provenance, association=item.association,
        association_links=sorted(item.links, key=lambda link: link.model_dump_json()),
        category=category, record_state=record, flow_state=flow, restore_state=restore,
        support=support, fields=fields,
        attributes={key: data[key] for key in sorted(OBSERVABLE_ATTRIBUTES) if key in data},
        record_type=str(record_type) if record_type else None,
        reason=reason, conflicts=conflicts,
        conflict_dimensions=sorted({'restore' if c.startswith('restore_') else 'record' for c in conflicts}),
    )
