"""Submission-specific inference vocabulary; separate from strict confidence rules."""

import hashlib
import re
from datetime import timedelta

from ghost_audit.domain.catalog import REPLICA_SUFFIX

WORKFLOW_RESULT = {"COMPLETE": "SUCCESS", "PARTIALLY_COMPLETE": "PARTIAL", "NOT_STARTED": "FAILED"}


ACCOUNT_WINDOW = (40, 80)


POLICY_ACTION_WINDOW = (4, 35)


FINAL_RESULT_WINDOW = (-125, -30)


DIRECT_REPORT_WINDOW = (-15, 15)


SYSTEM_BY_PREFIX = {
    "account": "account_service",
    "search": "search_service",
    "support": "support_platform",
    "analytics": "analytics_platform",
    "audit_record": "security_service",
    "data_flow": "integration_service",
    "backup": "backup_service",
    "export": "export_service",
    "tombstone": "identity_service",
    "cache": "cache_service",
    "marketing": "marketing_platform",
    "legal_hold": "legal_service",
}


PREFIX_BY_COLLECTION = {
    "customer_profiles": "account",
    "customer_search_documents": "search",
    "search_documents": "search",
    "customer_analytics_reports": "analytics",
    "customer_analytics_profiles": "analytics",
    "support_conversations": "support",
    "support_records": "support",
    "ticket_attachments": "support",
    "customer_export_jobs": "export",
    "customer_exports": "export",
    "security_audit_events": "audit_record",
    "security_audit_records": "audit_record",
    "backup_catalog": "backup",
    "backup_restore_entries": "backup",
    "connector_configurations": "data_flow",
    "connector_subscriptions": "data_flow",
    "deleted_customer_references": "tombstone",
    "retained_order_records": "legal_hold",
}


DIRECT_KEYS = {
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
    "matched_value",
}


STABLE_KEYS = {"user_id", "customer_reference", "subject_reference", "subject_ref"}


QUERY_KEYS = {
    "lookup_key",
    "correlation_key",
    "query",
    "match_key",
    "subject_key",
    "scan_key",
    "lookup_value",
}


CONTENT_KEYS = {"message_text", "message_excerpt", "body", "notes", "document_text"}


FLOW_ACTIVE = re.compile(r"\b(healthy|continuous|events? delivered|running|active)\b", re.I)


FLOW_STOPPED = re.compile(r"\b(disabled|paused|stopped|inactive|suspended)\b", re.I)


RESTORE_BLOCKED = re.compile(
    r"\b(restore (?:blocked|disabled|denied)|blocked|legal hold|no restore)\b", re.I
)


NULLS = {
    "",
    "null",
    "none",
    "no direct identifier",
    "[redacted]",
    "redacted",
    "[anonymized]",
    "anonymized",
}


def prefix(resource_id: str) -> str:
    """Read the existing submission resource-kind convention without inventing an ID."""
    return resource_id.rsplit("_", 1)[0]


def minutes(delta: timedelta) -> float:
    """Express observed workflow timing offsets in minutes."""
    return delta.total_seconds() / 60


def sha256(value: str) -> str:
    """Derive the submission strategy's normalized email hash."""
    return hashlib.sha256(value.strip().casefold().encode()).hexdigest()


def present(value: object) -> bool:
    """Recognize non-null scalar representations without declaring policy compliance."""
    return (
        value is not None
        and not isinstance(value, (dict, list))
        and str(value).strip().casefold() not in NULLS
    )


def table_scope(table: str) -> str:
    """Preserve the named physical SQL replica or the original table scope."""
    match = REPLICA_SUFFIX.search(table)
    return match[1] if match else "table:" + table
