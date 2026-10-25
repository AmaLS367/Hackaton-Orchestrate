"""Evidence-driven policy over physical scopes; no identifiers encode policy or labels."""

import re
from collections import defaultdict
from datetime import datetime
from typing import Literal

from pydantic import JsonValue

from ghost_audit.domain.association_models import ObservationLink, ResolvedIdentity
from ghost_audit.domain.models import DeletionRule
from ghost_audit.domain.observation_clocks import boolean
from ghost_audit.domain.policy_models import PolicyAssessment
from ghost_audit.domain.state_selection import links_sorted, scope_key
from ghost_audit.domain.temporal_models import (
    CaseStateBundle,
    FieldObservation,
    ResourceHistory,
    TemporalObservation,
)
from ghost_audit.domain.time import parse_timestamp

# Explicit participant schemas, not resource-ID conventions. An unknown schema stays unknown.
COLLECTION_CATEGORIES: dict[tuple[str | None, str | None], str] = {
    ("account_service", "customer_profiles"): "USER_PROFILE",
    ("account_service", "deleted_customer_references"): "ACCOUNT_TOMBSTONE",
    ("identity_service", "deleted_customer_references"): "ACCOUNT_TOMBSTONE",
    ("search_service", "customer_search_documents"): "SEARCH_INDEX_ENTRY",
    ("search_service", "search_documents_primary"): "SEARCH_INDEX_ENTRY",
    ("analytics_platform", "customer_analytics_profiles"): "ANALYTICS_PROFILE",
    ("analytics_platform", "customer_analytics_reports"): "ANALYTICS_PROFILE",
    # Inventory `support_records` lists every support item (messages and attachments)
    # and therefore does not type a record; specific collections do.
    ("support_platform", "support_conversations"): "SUPPORT_MESSAGE",
    ("support_platform", "ticket_attachments"): "SUPPORT_ATTACHMENT",
    ("export_service", "customer_export_jobs"): "USER_EXPORT",
    ("export_service", "customer_exports"): "USER_EXPORT",
    ("security_service", "security_audit_records"): "SECURITY_AUDIT_LOG",
    ("security_service", "security_audit_events"): "SECURITY_AUDIT_LOG",
    ("legal_service", "retained_order_records"): "LEGAL_HOLD_RECORD",
    ("backup_service", "backup_catalog"): "BACKUP_ARCHIVE",
    ("backup_service", "backup_restore_entries"): "BACKUP_ARCHIVE",
    ("integration_service", "connector_configurations"): "DATA_FLOW",
    ("integration_service", "connector_subscriptions"): "DATA_FLOW",
}
EXPORT_CATEGORIES: dict[tuple[str | None, str | None], str] = {
    ("account_service", "profile_lookups"): "USER_PROFILE",
    ("analytics_platform", "profiles"): "ANALYTICS_PROFILE",
    ("backup_service", "restore_entries"): "BACKUP_ARCHIVE",
    ("export_service", "exports"): "USER_EXPORT",
    ("integration_service", "connectors"): "DATA_FLOW",
    ("search_service", "index_queries"): "SEARCH_INDEX_ENTRY",
    ("security_service", "audit_records"): "SECURITY_AUDIT_LOG",
    ("support_platform", "tickets"): "SUPPORT_MESSAGE",
}
EVENT_CATEGORIES = {
    "profile_lookup_completed": "USER_PROFILE",
    "index_query_completed": "SEARCH_INDEX_ENTRY",
    "analytics_profile_read_completed": "ANALYTICS_PROFILE",
    "analytics_profile_read": "ANALYTICS_PROFILE",
    "analytics_identity_scan": "ANALYTICS_PROFILE",
    "support_ticket_read_completed": "SUPPORT_MESSAGE",
    "message_read": "SUPPORT_MESSAGE",
    "message_pii_scan": "SUPPORT_MESSAGE",
    "attachment_pii_scan": "SUPPORT_ATTACHMENT",
    "export_download_check_completed": "USER_EXPORT",
    "export_metadata_read_completed": "USER_EXPORT",
    "audit_record_read_completed": "SECURITY_AUDIT_LOG",
    "retained_order_loaded": "LEGAL_HOLD_RECORD",
    "connector_config_read_completed": "DATA_FLOW",
    "connector_config_loaded": "DATA_FLOW",
    "connector_heartbeat": "DATA_FLOW",
    "restore_policy_read_completed": "BACKUP_ARCHIVE",
    "restore_authorization_completed": "BACKUP_ARCHIVE",
    "restore_candidate_evaluated": "BACKUP_ARCHIVE",
}
CONDITIONS = {
    "Always": "always",
    "Conversation contains shared customer, agent, or order context that must be retained": "shared",
    "Attachment belongs only to the deletion subject": "subject_only",
    "Record is still attributable to a user": "attributable",
    "Log contains a user email address": "email",
    "Record is within the supplied retention period": "retention",
    "A supplied legal hold is active": "hold",
    "Restore access can be blocked": "blockable",
    "Account is deleted and only a stable internal user_id is needed to preserve references to retained records": "tombstone",
}
FINAL_STATES = {
    "DELETE": "ABSENT",
    "REDACT": "REDACTED",
    "ANONYMIZE": "ANONYMIZED",
    "RETAIN": "PRESENT",
}
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
# Last-resort record type of an explicitly scoped system when no collection, record
# type, export container, or read event names one. Never inferred from resource IDs.
SYSTEM_CATEGORIES = {
    "account_service": "USER_PROFILE",
    "search_service": "SEARCH_INDEX_ENTRY",
    "analytics_platform": "ANALYTICS_PROFILE",
    "support_platform": "SUPPORT_MESSAGE",
    "export_service": "USER_EXPORT",
    "security_service": "SECURITY_AUDIT_LOG",
    "backup_service": "BACKUP_ARCHIVE",
    "integration_service": "DATA_FLOW",
    "identity_service": "ACCOUNT_TOMBSTONE",
    "legal_service": "LEGAL_HOLD_RECORD",
    "marketing_platform": "MARKETING_PROFILE",
    "email_delivery_service": "EMAIL_DELIVERY_LOG",
    "cache_service": "CACHE_ENTRY",
    # Object storage holds uploaded support files (the attachment catalogue's objects).
    "object_storage": "SUPPORT_ATTACHMENT",
}
# Identifier fields whose observed treatment (null/redacted) evidences redaction.
IDENTIFYING = {
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
    "user_id",
    "customer_reference",
    "subject_reference",
    "message_text",
    "message_body",
    "message_excerpt",
    "matched_value",
}


def supported_observations(history: ResourceHistory, cutoff: datetime) -> list[TemporalObservation]:
    """Keep only proven, confirmed facts available before the audit cutoff."""
    return [
        o
        for o in history.observations
        if o.association == "CONFIRMED"
        and o.association_links
        and o.support == "PROVEN"
        and o.observed_at <= cutoff
        and o.available_at <= cutoff
        and (o.provenance.captured_at is not None and o.provenance.captured_at <= cutoff)
    ]


def latest(observations: list[TemporalObservation]) -> list[TemporalObservation]:
    """Select all contemporaneous latest statements, preserving possible conflicts."""
    if not observations:
        return []
    at = max(o.observed_at for o in observations)
    return sorted(
        (o for o in observations if o.observed_at == at), key=lambda o: o.model_dump_json()
    )


def attributes(observations: list[TemporalObservation]) -> dict[str, JsonValue]:
    """Conflicting contemporaneous attributes cannot authorize destructive treatment."""
    values: defaultdict[str, list[JsonValue]] = defaultdict(list)
    for o in observations:
        for key, value in o.attributes.items():
            if value not in values[key]:
                values[key].append(value)
    return {key: items[0] for key, items in values.items() if len(items) == 1}


def exposed(
    fields: list[FieldObservation], identity: ResolvedIdentity, *, stable: bool = False
) -> bool:
    # The stable internal user_id is a permitted reference unless anonymizing.
    """Detect prohibited direct or subject-linked fields under the requested treatment."""
    aliases = [
        a.original_value.casefold()
        for a in identity.aliases
        if a.original_value and (stable or a.field_name != "user_id")
    ]
    for f in fields:
        if f.representation != "VALUE":
            continue
        if f.role == "DIRECT_IDENTIFIER" or stable and f.role == "STABLE_REFERENCE":
            return True
        text = str(f.value).casefold()
        if (
            EMAIL.search(text)
            or f.role == "CONTENT"
            and any(re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text) for alias in aliases)
        ):
            return True
        if f.role == "STABLE_REFERENCE" and identity.user_id and str(f.value) != identity.user_id:
            return True
    return False


def coverage(
    fields: list[FieldObservation], *, anonymize: bool = False, tombstone: bool = False
) -> bool:
    """Full identifying-field groups must be observed, not just one null email."""
    names = {f.path.rsplit(".", 1)[-1] for f in fields}
    groups = [
        {"email", "customer_email", "requester_email", "owner_email"},
        {"phone", "customer_phone", "requester_phone", "owner_phone"},
        {"email_hash"},
    ]
    if tombstone:
        groups.append({"name", "full_name", "display_name", "requester_name"})
    if anonymize or tombstone:
        groups.append({"user_id", "customer_reference", "subject_reference", "subject_ref"})
    return all(names & group for group in groups)


class PolicyEvaluator:
    """Apply supplied policy facts without treating missing conditions as permission."""

    def __init__(self, rules: list[DeletionRule]) -> None:
        self.rules = defaultdict(list)
        for rule in sorted(rules, key=lambda r: r.rule_id):
            self.rules[rule.data_category].append(rule)

    def category(
        self,
        history: ResourceHistory,
        observations: list[TemporalObservation],
        *,
        fallback: bool = True,
    ) -> str | None:
        """Record type from explicit evidence of the resource (any confirmed observation,
        including linkage-only rows), most specific signal first."""
        system = history.scope.system_id
        typed = [
            o for o in observations if o.record_type in self.rules or o.record_type == "DATA_FLOW"
        ]
        explicit = {o.record_type for o in latest(typed)}
        schemas = {
            COLLECTION_CATEGORIES.get((system, o.scope.collection)) for o in observations
        } - {None}
        if (
            explicit == {"ACCOUNT_TOMBSTONE"}
            and schemas == {"USER_PROFILE"}
            and any(
                str(o.attributes.get("account_status", "")).upper() == "DELETED"
                for o in latest(typed)
            )
        ):
            # A current explicitly typed tombstone may occupy a former profile row.
            # Its condition still requires a confirmed permitted stable reference.
            return "ACCOUNT_TOMBSTONE"
        explicit |= schemas
        # Service-export object names establish type, not ownership or equivalence
        # with another collection. Phase 2 associations and physical scopes stay intact.
        for o in observations:
            match = re.fullmatch(
                r"\$\.service_exports\.([\w]+)\.([\w]+)\[\d+\]", o.provenance.locator
            )
            if match and match[1] == system:
                category = EXPORT_CATEGORIES.get((match[1], match[2]))
                if category:
                    explicit.add(category)
            if (
                o.attributes.get("event") == "contact_lookup_completed"
                and "email_opt_in" in o.attributes
            ):
                explicit.add("MARKETING_PROFILE")
        if not explicit:
            explicit.update(
                EVENT_CATEGORIES[str(o.attributes["event"])]
                for o in observations
                if o.attributes.get("event") in EVENT_CATEGORIES
            )
        if not explicit and system == "support_platform":
            # A rendered support document describing an uploaded file is an attachment;
            # otherwise the workflow's own per-resource treatment distinguishes a
            # deletable attachment (DELETE) from a retained conversation (REDACT).
            if any(
                o.category == "DOCUMENT" and re.search(r"\battachment\b", str(f.value), re.I)
                for o in observations
                for f in o.fields
                if f.role == "CONTENT"
            ):
                explicit.add("SUPPORT_ATTACHMENT")
            else:
                operations = {
                    str(o.attributes.get("event_type", ""))
                    for o in observations
                    if o.category == "OPERATION_CLAIM"
                }
                if operations & {"DELETE_RECORD"} and not operations & {"REDACT_RECORD"}:
                    explicit.add("SUPPORT_ATTACHMENT")
        if not explicit and fallback and system in SYSTEM_CATEGORIES:
            explicit.add(SYSTEM_CATEGORIES[system])
        return next(iter(explicit)) if len(explicit) == 1 else None

    def condition(
        self,
        kind: str | None,
        obs: list[TemporalObservation],
        history: ResourceHistory,
        bundle: CaseStateBundle,
    ) -> bool | None:
        """True/False from supplied facts; omitted conditions remain unknown."""
        a = attributes(obs)
        fields = [f for o in obs for f in o.fields]
        if kind == "always":
            return True
        if kind == "shared":
            value = boolean(a.get("shared_context"))
            if value is not None:
                return value
            return None
        if kind == "subject_only":
            value = boolean(a.get("subject_only"))
            if value is not None:
                return value
            return None
        if kind == "attributable":
            if (
                exposed(fields, bundle.identity, stable=True)
                or str(a.get("result", "")).upper() == "IDENTIFIABLE"
            ):
                return True
            # A previously applicable anonymization obligation remains verifiable after treatment.
            if history.record.state == "ANONYMIZED" or coverage(fields, anonymize=True):
                return True
            # Observed identifier slots (even nulled) show the record's attribution schema.
            if any(f.path.rsplit(".", 1)[-1] in IDENTIFYING for f in fields):
                return True
            return None
        if kind == "email":
            if any(EMAIL.search(str(f.value)) for f in fields if f.representation == "VALUE"):
                return True
            return True if any("email" in f.path for f in fields) else None
        if kind in {"retention", "hold"}:
            if kind == "hold" and boolean(a.get("hold_active")) is False:
                return False
            deadlines = [
                a[k] for k in ("retention_until", "retained_until", "legal_hold_until") if a.get(k)
            ]
            try:
                if deadlines:
                    return max(parse_timestamp(value) for value in deadlines) > bundle.audit_at
            except (TypeError, ValueError):
                return None
            if kind == "hold" and boolean(a.get("hold_active")) is not None:
                return boolean(a.get("hold_active"))
            # Preservation is safe, but no supplied deadline/hold means applicability
            # cannot be asserted as current compliance.
            return None
        if kind == "blockable":
            return (
                True
                if history.restore.support == "PROVEN"
                or boolean(a.get("restore_blockable")) is True
                else None
            )
        if kind == "tombstone":
            deleted = (
                str(a.get("account_status", "")).upper() == "DELETED"
                or any(o.record_type == "ACCOUNT_TOMBSTONE" for o in obs)
                or history.scope.collection == "deleted_customer_references"
            )
            return (
                True
                if deleted
                and any(
                    f.role == "STABLE_REFERENCE" and f.value == bundle.identity.user_id
                    for f in fields
                )
                else None
            )
        return None

    def applicable(
        self,
        rule: DeletionRule,
        selected: list[TemporalObservation],
        observations: list[TemporalObservation],
        history: ResourceHistory,
        bundle: CaseStateBundle,
    ) -> tuple[bool | None, list[ObservationLink]]:
        kind = CONDITIONS.get(rule.condition)
        current = self.condition(kind, selected, history, bundle)
        if current is not None:
            return current, links_sorted(o.link for o in selected)
        condition_fields = {
            "shared": {"shared_context"},
            "subject_only": {"subject_only"},
            "retention": {"retention_until", "retained_until"},
            "hold": {"hold_active", "legal_hold_until", "retained_until"},
        }
        if any(
            key in o.attributes for o in selected for key in condition_fields.get(kind or "", ())
        ):
            # Malformed or contradictory current facts cannot be replaced with a
            # convenient historical condition.
            return None, []
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
        groups = defaultdict(list)
        for h in bundle.resource_histories:
            groups[(h.scope.system_id or "", h.scope.resource_id)].append(h)
        for key in sorted(groups):
            histories = sorted(groups[key], key=lambda h: scope_key(h.scope))
            # Type comes from every confirmed row of the resource, including rows that
            # only identify it; a POTENTIAL row never establishes the subject's obligations.
            confirmed = [
                o
                for h in histories
                for o in h.observations
                if o.association == "CONFIRMED" and o.association_links
            ]
            category = self.category(histories[0], confirmed) if confirmed else None
            supported = {id(h): supported_observations(h, bundle.audit_at) for h in histories}
            freshness = {
                id(h): max((o.observed_at for o in supported[id(h)]), default=None)
                for h in histories
            }
            newest = max((t for t in freshness.values() if t is not None), default=None)
            if newest is None:
                results.append(self.unobserved(histories[0], category, confirmed, bundle))
                continue
            # Time orders observations within a physical scope. A read of another
            # surface cannot establish that this copy received deletion treatment.
            for h in histories:
                local = [
                    o
                    for o in h.observations
                    if o.association == "CONFIRMED" and o.association_links
                ]
                local_category = (
                    (self.category(h, local, fallback=False) or category) if local else None
                )
                if freshness[id(h)] is not None:
                    results.extend(self.assess(h, local_category, supported[id(h)], bundle))
                elif any(
                    o.association == "CONFIRMED"
                    and o.association_links
                    and o.category in {"SNAPSHOT", "SNAPSHOT_GAP", "DOCUMENT", "RESOURCE_READBACK"}
                    for o in h.observations
                ):
                    results.append(self.unobserved(h, local_category, local, bundle))
        return results

    def unobserved(
        self,
        h: ResourceHistory,
        category: str | None,
        confirmed: list[TemporalObservation],
        bundle: CaseStateBundle,
    ) -> PolicyAssessment:
        """A confirmed resource without a citable state: obligation known, compliance unknown."""
        reasons = ["no_confirmed_state_evidence"]
        if category in {"DATA_FLOW", "BACKUP_ARCHIVE"}:
            flow = category == "DATA_FLOW"
            return PolicyAssessment(
                scope=h.scope,
                dimension="flow" if flow else "restore",
                category=category,
                required_action="DISABLE" if flow else "BLOCK",
                required_state="DISABLED" if flow else "BLOCKED",
                observed_state="UNKNOWN",
                compliance="UNKNOWN",
                reasons=reasons,
            )
        candidates = self.rules.get(category or "", [])
        selected = latest(confirmed)
        rules = [
            r
            for r in candidates
            if self.condition(CONDITIONS.get(r.condition), selected, h, bundle) is True
        ]
        rule = rules[0] if len(rules) == 1 else None
        return PolicyAssessment(
            scope=h.scope,
            dimension="record",
            category=category,
            rule_id=rule.rule_id if rule else None,
            required_action=rule.required_action if rule else None,
            required_state=FINAL_STATES[rule.required_action] if rule else None,
            observed_state="UNKNOWN",
            compliance="UNKNOWN",
            reasons=reasons
            if rule or not candidates
            else [*reasons, "policy_condition_unestablished_or_ambiguous"],
        )

    def assess(
        self,
        h: ResourceHistory,
        category: str | None,
        observations: list[TemporalObservation],
        bundle: CaseStateBundle,
    ) -> list[PolicyAssessment]:
        if category == "DATA_FLOW":
            return [self.process(h, "flow", category)]
        if category == "BACKUP_ARCHIVE":
            # Archives are retained (rule 14); the obligation is the restore path.
            return [self.process(h, "restore", category)]
        candidates = self.rules.get(category or "", [])
        selected = latest([o for o in observations if o.link in h.record.supporting_evidence])
        applicability = [
            (r, *self.applicable(r, selected, observations, h, bundle)) for r in candidates
        ]
        rules = [(r, evidence) for r, applies, evidence in applicability if applies is True]
        if len(rules) != 1:
            # Missing retention applicability cannot justify deletion or COMPLETE.
            # Preserve a known security/legal record in a future INCOMPLETE plan
            # while the retention question is investigated; never assert compliance.
            precaution = (
                candidates[0]
                if len(candidates) == 1 and candidates[0].required_action == "RETAIN"
                else None
            )
            return [
                PolicyAssessment(
                    scope=h.scope,
                    dimension="record",
                    category=category,
                    rule_id=precaution.rule_id if precaution else None,
                    required_action="RETAIN" if precaution else None,
                    required_state="PRESENT" if precaution else None,
                    observed_state=h.record.state,
                    compliance="UNKNOWN",
                    reasons=[
                        "policy_category_unknown"
                        if not candidates
                        else "policy_condition_unestablished_or_ambiguous"
                    ],
                )
            ]
        rule, condition_evidence = rules[0]
        base = PolicyAssessment(
            scope=h.scope,
            dimension="record",
            category=category,
            rule_id=rule.rule_id,
            required_action=rule.required_action,
            required_state=FINAL_STATES[rule.required_action],
            observed_state=h.record.state,
            condition_evidence=condition_evidence,
            compliance="UNKNOWN",
        )
        if h.record.support != "PROVEN" or not selected:
            return [base.model_copy(update={"reasons": ["record_state_unproven"]})]
        compliance, reasons = self.record_compliance(h, selected, rule, bundle)
        return [
            base.model_copy(
                update={
                    "compliance": compliance,
                    "evidence": links_sorted(o.link for o in selected),
                    "reasons": reasons,
                }
            )
        ]

    @staticmethod
    def process(
        h: ResourceHistory, dimension: Literal["flow", "restore"], category: str
    ) -> PolicyAssessment:
        selection = getattr(h, dimension)
        flow = dimension == "flow"
        required, bad = ("INACTIVE", "ACTIVE") if flow else ("BLOCKED", "ALLOWED")
        compliance: Literal["COMPLIANT", "VIOLATION", "UNKNOWN"] = (
            "UNKNOWN"
            if selection.support != "PROVEN"
            else "VIOLATION"
            if selection.state == bad
            else "COMPLIANT"
            if selection.state == required
            else "UNKNOWN"
        )
        return PolicyAssessment(
            scope=h.scope,
            dimension=dimension,
            category=category,
            required_action="DISABLE" if flow else "BLOCK",
            required_state="DISABLED" if flow else "BLOCKED",
            observed_state=selection.state,
            compliance=compliance,
            evidence=selection.supporting_evidence if selection.support == "PROVEN" else [],
            reasons=[] if compliance != "UNKNOWN" else ["process_safety_unproven"],
        )

    @staticmethod
    def record_compliance(
        h: ResourceHistory,
        observations: list[TemporalObservation],
        rule: DeletionRule,
        bundle: CaseStateBundle,
    ) -> tuple[Literal["COMPLIANT", "VIOLATION", "UNKNOWN"], list[str]]:
        state, action = h.record.state, rule.required_action
        fields = [f for o in observations for f in o.fields]
        if action == "DELETE":
            return ("COMPLIANT", []) if state == "ABSENT" else ("VIOLATION", [])
        if action == "RETAIN":
            return (
                ("COMPLIANT", [])
                if state in {"PRESENT", "REDACTED", "ANONYMIZED"}
                else (
                    "UNKNOWN",
                    ["required_retained_record_missing_no_supported_recreation_operation"],
                )
            )
        if state == "ABSENT":
            return "UNKNOWN", ["required_preserved_record_absent"]
        # Existence can agree while field contents conflict at the selected time.
        signatures = defaultdict(set)
        for f in fields:
            signatures[f.path].add((f.representation, str(f.value)))
        if any(len(values) > 1 for values in signatures.values()):
            return "UNKNOWN", ["conflicting_identifier_fields"]
        if exposed(fields, bundle.identity, stable=action == "ANONYMIZE"):
            return "VIOLATION", []
        # No identifier is exposed; observed null/redacted identifier fields are the
        # treatment itself. A record showing no identifier slot at all proves nothing.
        if action == "ANONYMIZE":
            if state == "ANONYMIZED" or coverage(fields, anonymize=True):
                return "COMPLIANT", []
            return "UNKNOWN", ["anonymization_field_coverage_insufficient"]
        tombstone = rule.data_category == "ACCOUNT_TOMBSTONE"
        if tombstone and not any(
            f.role == "STABLE_REFERENCE" and f.value == bundle.identity.user_id for f in fields
        ):
            return "UNKNOWN", ["permitted_stable_reference_unproven"]
        if (
            state == "REDACTED"
            or coverage(fields, tombstone=tombstone)
            or (
                rule.data_category == "EMAIL_DELIVERY_LOG"
                and any("email" in f.path for f in fields)
            )
        ):
            return "COMPLIANT", []
        return "UNKNOWN", ["redaction_field_coverage_insufficient"]
