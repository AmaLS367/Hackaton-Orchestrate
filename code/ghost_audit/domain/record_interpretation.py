"""Interpret already extracted record facts without reading files or deciding policy."""

import re
from dataclasses import dataclass

from pydantic import JsonValue

from ghost_audit.domain.association_models import AssociatedObservation
from ghost_audit.domain.models import ResourceRef
from ghost_audit.domain.observation_clocks import (
    boolean,
    integer,
    logical_collection,
    observation_time,
    replica_scope,
)
from ghost_audit.domain.temporal_models import FieldObservation, ResourceScope, TemporalObservation

DIRECT_FIELDS = {
    "name",
    "full_name",
    "display_name",
    "requester_name",
    "customer_name",
    "email",
    "phone",
    "email_hash",
    "customer_email",
    "owner_email",
    "requester_email",
    "customer_phone",
    "owner_phone",
    "requester_phone",
    "uploaded_by",
    "ip_address",
    "device_id",
    "advertising_id",
    "postal_address",
}


STABLE_FIELDS = {
    "user_id",
    "customer_reference",
    "subject_reference",
    "subject_ref",
    "subject_selector",
}


CONTENT_FIELDS = {
    "message_text",
    "message_body",
    "message_excerpt",
    "body",
    "notes",
    "matched_value",
    "document_text",
}


REDACTED = {"[redacted]", "redacted"}


ANONYMIZED = {"[anonymized]", "anonymized", "anonymous"}


NULL = {"null", "none", "", "no direct identifier"}


OBSERVABLE_ATTRIBUTES = {
    "enabled",
    "restore_allowed",
    "archive_present",
    "eligible",
    "deletion_block",
    "decision",
    "scheduler_registered",
    "connector_name",
    "destination",
    "mode",
    "source_system",
    "target_system",
    "retention_until",
    "account_status",
    "direct_identifiers",
    "query_scope",
    "rows",
    "http_status",
    "status_code",
    "total_hits",
    "result",
    "observed_state",
    "event",
    "reported_result",
    "event_type",
    "retained_until",
    "legal_hold_until",
    "hold_active",
    "shared_context",
    "subject_only",
    "restore_blockable",
    "ticket_id",
    "source_resource_id",
    "source_system_id",
    "target_resource_id",
    "target_system_id",
    "email_opt_in",
}


def field_observations(payload: dict[str, JsonValue]) -> list[FieldObservation]:
    """Preserve identifier/content roles and observed treatment extent recursively."""
    result = []

    def visit(value: JsonValue, path: str = "") -> None:
        if isinstance(value, dict):
            for key, child in sorted(value.items()):
                child_path = f"{path}.{key}" if path else key
                role = (
                    "DIRECT_IDENTIFIER"
                    if key in DIRECT_FIELDS
                    else "STABLE_REFERENCE"
                    if key in STABLE_FIELDS
                    else "CONTENT"
                    if key in CONTENT_FIELDS
                    else None
                )
                if role and not isinstance(child, (dict, list)):
                    text = child.casefold().strip() if isinstance(child, str) else None
                    representation = (
                        "NULL"
                        if child is None or text in NULL
                        else "REDACTED"
                        if text in REDACTED
                        else "ANONYMIZED"
                        if text in ANONYMIZED
                        else "VALUE"
                    )
                    result.append(
                        FieldObservation.model_validate(
                            {
                                "path": child_path,
                                "role": role,
                                "representation": representation,
                                "value": child,
                            }
                        )
                    )
                elif key not in {"record_json", "text", "message"}:
                    visit(child, child_path)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                visit(child, f"{path}[{i}]")

    visit(payload)
    return result


def interpret(
    item: AssociatedObservation, reference: ResourceRef, *, source_suffix: str
) -> TemporalObservation:
    """Interpret schema-supported state; potential ownership cannot establish proof."""
    o = item.observation
    # Preserve wrapper provenance, but do not count the encoded copy twice.
    p = o.payload
    data = record_payload(p)
    fields = field_observations(data)
    event = str(p.get("event", "")).lower()
    result = str(data.get("result", "")).upper()
    record_type = data.get("record_type") or data.get("account_status")
    record = flow = restore = "UNKNOWN"
    category = "UNINTERPRETED"
    reason = "no_supported_state_semantics"
    conflicts: list[str] = []
    claim = (
        o.kind == "activity_claim"
        or bool(p.get("reported_result"))
        or bool(
            re.search(
                r"(?:delete|restore|sync|redact|anonymize|workflow|purge)_(?:completed|result|success)$",
                event,
            )
        )
    )
    suffix = source_suffix
    snapshot = bool(reference.physical_table) or (
        suffix == ".json"
        and bool(reference.collection)
        and not event
        and not any(k in data for k in ("result", "status_code", "http_status", "hits"))
    )
    resource_read = event.endswith(
        ("_lookup_completed", "_read_completed", "_query_completed")
    ) or event in {
        "record_lookup",
        "analytics_profile_read",
        "message_read",
        "retained_order_loaded",
        "message_pii_scan",
        "attachment_pii_scan",
        "analytics_identity_scan",
    }
    structured_read = bool(
        data.get("record_type")
        and "result" in data
        and any(k in data for k in ("recorded_at", "observed_at", "timestamp"))
    )
    json_read = suffix == ".json" and any(k in data for k in ("status_code", "hits", "observed_at"))
    config_read = event in {
        "connector_heartbeat",
        "connector_config_loaded",
        "restore_candidate_evaluated",
        "restore_authorization_completed",
    }
    status = integer(data.get("http_status", data.get("status_code")))
    failed_read = status is not None and status >= 400 and status != 404
    if claim:
        category, reason = "OPERATION_CLAIM", "operation_result_is_not_a_resource_readback"
        operation = str(p.get("event_type", event)).upper()
        successful = str(p.get("reported_result", p.get("result", "SUCCESS"))).upper() == "SUCCESS"
        if "DELETE" in operation and successful:
            record = "ABSENT"
        elif successful and any(word in operation for word in ("RESTORE", "SYNC", "IMPORT")):
            record = "PRESENT"
    elif failed_read:
        reason = "failed_read_does_not_establish_resource_state"
    elif "document_reference" in data:
        # A business document or console screen rendering the record at capture time.
        category, reason, record = "DOCUMENT", "participant_document_renders_record", "PRESENT"
    elif snapshot or resource_read or structured_read or json_read or config_read:
        category = (
            "SNAPSHOT"
            if snapshot
            else "SERVICE_READBACK"
            if structured_read
            else "RESOURCE_READBACK"
        )
        reason = "explicit_snapshot_contents" if snapshot else "explicit_resource_readback"
        context = _ReadbackContext(
            data, reference, fields, event, snapshot, resource_read or json_read or config_read
        )
        record, reason, conflicts = _record_readback(context)
        flow = _flow_readback(data, record_type, result)
        record, restore, process_conflicts = _restore_readback(data, record_type, result, record)
        conflicts.extend(process_conflicts)

    exposed = any(f.role == "DIRECT_IDENTIFIER" and f.representation == "VALUE" for f in fields)
    linked = any(f.role == "STABLE_REFERENCE" and f.representation == "VALUE" for f in fields)
    if record in {"REDACTED", "ANONYMIZED"} and (exposed or record == "ANONYMIZED" and linked):
        conflicts.append("state_label_contradicts_observed_identity_fields")
    support = (
        "CLAIM_ONLY"
        if claim
        else "PROVEN"
        if category != "UNINTERPRETED"
        and (record != "UNKNOWN" or flow != "UNKNOWN" or restore != "UNKNOWN")
        else "UNKNOWN"
    )
    if conflicts:
        support = "CONFLICTED"
    if item.association != "CONFIRMED" or not item.links:
        support = "UNKNOWN"
        reason = "potential_or_unsupported_ownership; " + reason
    return TemporalObservation.model_validate(
        {
            "scope": ResourceScope(
                resource_id=reference.resource_id,
                system_id=reference.system_id,
                collection=logical_collection(reference),
                replica_scope=replica_scope(o, reference),
            ),
            "physical_table": reference.physical_table,
            "observed_at": observation_time(o),
            "available_at": o.available_at,
            "provenance": o.provenance,
            "association": item.association,
            "association_links": sorted(item.links, key=lambda link: link.model_dump_json()),
            "category": category,
            "record_state": record,
            "flow_state": flow,
            "restore_state": restore,
            "support": support,
            "fields": fields,
            "attributes": {key: data[key] for key in sorted(OBSERVABLE_ATTRIBUTES) if key in data},
            "record_type": str(record_type) if record_type else None,
            "reason": reason,
            "conflicts": conflicts,
            "conflict_dimensions": sorted(
                {"restore" if c.startswith("restore_") else "record" for c in conflicts}
            ),
        }
    )


@dataclass(frozen=True)
class _ReadbackContext:
    """One resource read and its schema interpretation flags."""

    data: dict[str, JsonValue]
    reference: ResourceRef
    fields: list[FieldObservation]
    event: str
    snapshot: bool
    implicit_presence: bool


def record_payload(payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Unwrap a decoded record without conflating its wrapper with record contents."""
    decoded = payload.get("decoded_record")
    return decoded if isinstance(decoded, dict) else payload


def _record_readback(context: _ReadbackContext) -> tuple[str, str, list[str]]:
    data, reference, fields = context.data, context.reference, context.fields
    event, snapshot = context.event, context.snapshot
    result = str(data.get("result", "")).upper()
    status = integer(data.get("http_status", data.get("status_code")))
    record = "UNKNOWN"
    reason = "explicit_snapshot_contents" if snapshot else "explicit_resource_readback"
    conflicts: list[str] = []
    rows = integer(data.get("rows"))
    hit_response = data.get("hits")
    hits = hit_response
    hits = hits.get("total") if isinstance(hits, dict) else data.get("total_hits")
    if isinstance(hits, dict):
        hits = hits.get("value")
    hits = integer(hits)
    search = event == "index_query_completed" or "hits" in data
    query = data.get("query")
    exact_search = (
        data.get("query_scope") == "RESOURCE_ID"
        or data.get("query_resource_id") == reference.resource_id
        or isinstance(query, dict)
        and query.get("resource_id") == reference.resource_id
    )
    negative = result == "NOT_FOUND" or status == 404 or rows == 0 or hits == 0
    # A read declaring a subject/collection query scope or a filter answers that
    # query; its emptiness says nothing exact about this one record.
    declared = data.get("query_scope")
    broad = (
        declared not in (None, "", "RESOURCE_ID")
        and data.get("query_resource_id") != reference.resource_id
        or any(data.get(k) for k in ("filter", "filters", "where"))
    )
    positive = (
        snapshot
        or result in {"FOUND", "HIT", "IDENTIFIABLE", "REDACTED", "ANONYMIZED"}
        or rows is not None
        and rows > 0
        or status == 200
        and not negative
        or hits is not None
        and hits > 0
    )
    if isinstance(hit_response, dict) and isinstance(hit_response.get("documents"), list):
        documents = hit_response["documents"]
        assert isinstance(documents, list)
        if not any(
            isinstance(doc, dict) and doc.get("resource_id") == reference.resource_id
            for doc in documents
        ):
            positive = False
            reason = "search_documents_do_not_establish_this_resource"
    if negative and (not search or exact_search) and not broad:
        record = "ABSENT"
    elif negative:
        reason = (
            "negative_read_lacks_exact_resource_scope"
            if not search
            else "negative_search_lacks_explicit_resource_query_scope"
        )
    elif positive or (
        not search
        and context.implicit_presence
        and (
            fields
            or any(k in data for k in ("enabled", "archive_present"))
            or event in {"message_pii_scan", "attachment_pii_scan", "analytics_identity_scan"}
        )
    ):
        record = "PRESENT"
    if negative and positive:
        conflicts.append("contradictory_presence_readback")
    if result in {"REDACTED", "ANONYMIZED"}:
        record = result
    elif str(data.get("observed_state", "")).upper() in {"REDACTED", "ANONYMIZED"}:
        record = str(data["observed_state"]).upper()
    elif any(f.representation == "REDACTED" for f in fields) and record == "PRESENT":
        # An explicit marker is evidence of field redaction, not all-field removal.
        # Keep PRESENT; the fields carry the precise extent of redaction.
        reason = "present_record_with_explicit_field_redactions"

    return record, reason, conflicts


def _flow_readback(data: dict[str, JsonValue], record_type: JsonValue, result: str) -> str:
    flow = "UNKNOWN"
    enabled = boolean(data.get("enabled"))
    if enabled is not None:
        flow = "ACTIVE" if enabled else "INACTIVE"
    if record_type == "DATA_FLOW" and result in {"ACTIVE", "DISABLED"}:
        flow = "ACTIVE" if result == "ACTIVE" else "INACTIVE"
    return flow


def _restore_readback(
    data: dict[str, JsonValue], record_type: JsonValue, result: str, record: str
) -> tuple[str, str, list[str]]:
    restore = "UNKNOWN"
    conflicts: list[str] = []
    allowed = boolean(data.get("restore_allowed"))
    blocked = boolean(data.get("deletion_block"))
    decision = str(data.get("decision", "")).lower()
    if allowed is not None:
        restore = "ALLOWED" if allowed else "BLOCKED"
    elif blocked is True or decision == "deny":
        restore = "BLOCKED"
    elif decision == "allow" or (boolean(data.get("eligible")) is True and blocked is False):
        restore = "ALLOWED"
    restore_signals = {"ALLOWED" if allowed else "BLOCKED"} if allowed is not None else set()
    if blocked is True or decision == "deny":
        restore_signals.add("BLOCKED")
    if decision == "allow":
        restore_signals.add("ALLOWED")
    if len(restore_signals) > 1:
        conflicts.append("restore_configuration_fields_disagree")
    if record_type == "BACKUP_ARCHIVE" and result in {"FOUND", "ACTIVE", "BLOCKED"}:
        record = "PRESENT"
        if result == "BLOCKED":
            restore = "BLOCKED"
        elif result == "ACTIVE" and restore == "UNKNOWN":
            # An archive reported ACTIVE (not BLOCKED) remains restorable.
            restore = "ALLOWED"
    # Restore authorization is independent of archive existence.
    if (
        any(k in data for k in ("archive_path", "archive_key", "object_key"))
        or boolean(data.get("available")) is True
    ):
        record = "PRESENT"
    if boolean(data.get("archive_present")) is False:
        if record == "PRESENT":
            conflicts.append("archive_existence_fields_disagree")
        record = "ABSENT"
    elif boolean(data.get("archive_present")) is True:
        record = "PRESENT"

    return record, restore, conflicts
