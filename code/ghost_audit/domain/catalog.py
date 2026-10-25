"""Established participant schema names and clock roles, independent of storage."""

import re

ISO_TOKEN = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})"


BUSINESS_TIMES = {"expires_at", "retention_until", "retained_until", "next_run_at", "scheduled_at"}


SOURCE_TIMES = {
    "captured_at",
    "exported_at",
    "recorded_at",
    "observed_at",
    "event_time",
    "updated_at",
    "created_at",
    "timestamp",
    "snapshot",
    "snapshot_at",
}


SYSTEM_FIELDS = ("system_id", "system", "origin_system", "data_store", "service")


COLLECTION_SYSTEMS = {
    "customer_profiles": "account_service",
    "customer_search_documents": "search_service",
    "search_documents": "search_service",
    "customer_analytics_reports": "analytics_platform",
    "customer_analytics_profiles": "analytics_platform",
    "support_conversations": "support_platform",
    "support_records": "support_platform",
    "ticket_attachments": "support_platform",
    "customer_export_jobs": "export_service",
    "customer_exports": "export_service",
    "security_audit_events": "security_service",
    "security_audit_records": "security_service",
    "backup_catalog": "backup_service",
    "backup_restore_entries": "backup_service",
    "connector_configurations": "integration_service",
    "connector_subscriptions": "integration_service",
    "deleted_customer_references": "identity_service",
    "retained_order_records": "legal_service",
}


SYSTEM_ALIASES = {"support_replica": "support_platform"}


REPLICA_TABLE = re.compile(
    r"_(?:primary|read_replica|reporting_replica|failover_replica|replica\w*)$"
)


def collection_system(collection: str | None) -> str | None:
    if not collection:
        return None
    return COLLECTION_SYSTEMS.get(collection) or COLLECTION_SYSTEMS.get(
        REPLICA_TABLE.sub("", collection)
    )


TABLE_SYSTEMS = {
    "customer_profiles": "account_service",
    "customer_search_documents": "search_service",
    "search_documents": "search_service",
    "customer_analytics_profiles": "analytics_platform",
    "support_records": "support_platform",
    "customer_exports": "export_service",
    "connector_subscriptions": "integration_service",
    "backup_restore_entries": "backup_service",
    "security_audit_records": "security_service",
}

REPLICA_SUFFIX = re.compile(
    r"_(primary|read_replica|regional_replica(?:_[a-z0-9_]+)?|reporting_replica|"
    r"failover_replica|replica(?:_[a-z0-9_]+)?)$"
)
