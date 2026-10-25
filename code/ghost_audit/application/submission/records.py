"""Interpret submission readbacks, policy categories and replica verdicts."""

import re

from pydantic import JsonValue

from ghost_audit.application.observation_interpretation import interpret
from ghost_audit.application.submission.evidence import SubmissionEvidence
from ghost_audit.domain.association_models import (
    AssociatedObservation,
    CorrelationLink,
    ObservationLink,
)
from ghost_audit.domain.evidence_index import identifier_values
from ghost_audit.domain.observation_clocks import observation_time
from ghost_audit.domain.record_interpretation import record_payload
from ghost_audit.domain.snapshot_inventory import snapshot_listings
from ghost_audit.domain.submission_models import Action, Fact, RecordSignals, Verdict
from ghost_audit.domain.submission_semantics import (
    CONTENT_KEYS,
    DIRECT_KEYS,
    FLOW_ACTIVE,
    FLOW_STOPPED,
    QUERY_KEYS,
    RESTORE_BLOCKED,
    STABLE_KEYS,
    prefix,
    present,
)
from ghost_audit.domain.temporal_models import TemporalObservation


class SubmissionRecords:
    """Interpret submitted record facts without promoting claims into readbacks."""

    def __init__(self, evidence: SubmissionEvidence) -> None:
        self.evidence = evidence
        # Required treatment per data category comes from deletion_rules.csv. A retained
        # backup must also be unable to restore the subject; a data flow must be stopped.
        self.required: dict[str, Action] = {
            rule.data_category: rule.required_action for rule in evidence.dataset.rules
        }
        if "BACKUP_ARCHIVE" in self.required:
            self.required["BACKUP_ARCHIVE"] = "BLOCK"
        self.required["DATA_FLOW"] = "DISABLE"
        self.listings = snapshot_listings(evidence.observations)

    def facts(self, resource_id: str, user: str) -> tuple[list[Fact], RecordSignals]:
        """Interpreted readbacks of one resource, with the record category signals."""
        result: list[Fact] = []
        signals: RecordSignals = {
            "events": set(),
            "types": set(),
            "collections": set(),
            "keys": set(),
            "documents": set(),
        }
        user_values = self.evidence.user_values.get(user, set())
        for i in self.evidence.by_resource.get(resource_id, ()):
            o = self.evidence.observations[i]
            refs = [r for r in o.resources if r.resource_id == resource_id]
            if not refs or o.available_at is None:
                continue
            if (
                self.evidence.obs_users[i]
                and user not in self.evidence.obs_users[i]
                and not self.evidence.negative_trace[i]
            ):
                continue  # a same-ID readback naming only another subject never describes this one
            item = AssociatedObservation(
                observation=o,
                association="CONFIRMED",
                reason="submission_resource_identity",
                links=[
                    CorrelationLink(
                        method="RESOURCE", supporting_observations=[ObservationLink.of(o)]
                    )
                ],
            )
            t = interpret(item, refs[0])
            data = record_payload(o.payload)
            signals["events"].add(str(o.payload.get("event", "")))
            signals["types"].add(str(data.get("record_type") or "").upper())
            signals["collections"].add(str(refs[0].collection or ""))
            signals["keys"].update(data)
            if t.category == "DOCUMENT":
                signals["documents"].add(o.provenance.file_path)
            if t.support in {"CLAIM_ONLY", "UNKNOWN"} and t.category != "DOCUMENT":
                continue
            if t.category == "DOCUMENT":
                t = self._document_state(t, data, resource_id)
            verdicts = self._verdicts(t, data, user_values)
            if verdicts:
                result.append(
                    Fact(
                        o.provenance.evidence_id,
                        observation_time(o) or o.available_at,
                        o.available_at,
                        t.scope.replica_scope,
                        verdicts,
                    )
                )
        return result, signals

    @staticmethod
    def _document_state(t, data, resource_id):
        """A console or business document rendering a connector or archive states its
        operating status in words; no status words leave the dimension unknown."""
        text = str(data.get("document_text", ""))
        update = {}
        if prefix(resource_id) == "data_flow":
            if FLOW_STOPPED.search(text):
                update["flow_state"] = "INACTIVE"
            elif FLOW_ACTIVE.search(text):
                update["flow_state"] = "ACTIVE"
        if prefix(resource_id) == "backup" and re.search(r"archive|\.tar|path", text, re.I):
            update["restore_state"] = "BLOCKED" if RESTORE_BLOCKED.search(text) else "ALLOWED"
        return t.model_copy(update=update) if update else t

    def _verdicts(
        self, t: TemporalObservation, data: dict[str, JsonValue], user_values: set[str]
    ) -> dict[Action, Verdict]:
        verdicts: dict[Action, Verdict] = {}
        direct, stable, subject = self._exposure(data, user_values)
        if t.flow_state != "UNKNOWN":
            verdicts["DISABLE"] = "VIOLATION" if t.flow_state == "ACTIVE" else "COMPLIANT"
        if t.restore_state != "UNKNOWN":
            verdicts["BLOCK"] = "VIOLATION" if t.restore_state == "ALLOWED" else "COMPLIANT"
        record = t.record_state
        if record == "ABSENT":
            # A missing retained record has no remediation operation; it stays unproven.
            verdicts.update({"DELETE": "COMPLIANT"})
            verdicts.setdefault("BLOCK", "COMPLIANT")
        elif record in {"PRESENT", "REDACTED", "ANONYMIZED"}:
            verdicts.update({"DELETE": "VIOLATION", "RETAIN": "COMPLIANT"})
            exposed_direct = bool(direct) or subject
            if exposed_direct or str(data.get("result", "")).upper() == "IDENTIFIABLE":
                verdicts.update({"REDACT": "VIOLATION", "ANONYMIZE": "VIOLATION"})
            else:
                if record == "REDACTED" or direct is False:
                    verdicts["REDACT"] = "COMPLIANT"
                if stable:
                    verdicts["ANONYMIZE"] = "VIOLATION"
                elif record == "ANONYMIZED" or (direct is False and stable is False):
                    verdicts["ANONYMIZE"] = "COMPLIANT"
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
                    if k not in {"record_json", "text", "message"} | QUERY_KEYS:
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
                direct_values = {v for v in user_values if not v.startswith("user_")}
                if identifier_values(value) & direct_values or any(
                    v in value.casefold() for v in direct_values if "@" in v or " " in v
                ):
                    subject = True

        visit(data)
        flag = str(data.get("direct_identifiers", "")).casefold() if isinstance(data, dict) else ""
        if flag in {"present", "true", "1", "yes"}:
            direct = True
        elif flag in {"absent", "false", "0", "none", "no"} and direct is None:
            direct = False
        return direct, stable, subject

    def category(self, resource_id: str, signals: RecordSignals) -> str:
        kind = prefix(resource_id)
        # A source that names the record's data category is authoritative.
        named = sorted(t for t in signals["types"] if t in self.required and t != "BACKUP_ARCHIVE")
        if len(named) == 1:
            return named[0]
        fixed = {
            "account": "USER_PROFILE",
            "search": "SEARCH_INDEX_ENTRY",
            "cache": "CACHE_ENTRY",
            "export": "USER_EXPORT",
            "marketing": "MARKETING_PROFILE",
            "audit_record": "SECURITY_AUDIT_LOG",
            "legal_hold": "LEGAL_HOLD_RECORD",
            "backup": "BACKUP_ARCHIVE",
            "tombstone": "ACCOUNT_TOMBSTONE",
            "data_flow": "DATA_FLOW",
            "email_delivery": "EMAIL_DELIVERY_LOG",
            "telemetry": "PRODUCT_TELEMETRY",
        }
        if kind in fixed:
            return fixed[kind]
        if kind == "object" and any(
            "belongs only to" in a.details
            for a in self.evidence.activities_by_resource.get(resource_id, ())
        ):
            return "SUPPORT_ATTACHMENT"
        if kind == "analytics":
            # A contact record carrying a marketing opt-in is a marketing profile kept
            # on the analytics platform, not an attributable analytics report.
            if "contact_lookup_completed" in signals["events"] or "email_opt_in" in signals["keys"]:
                return "MARKETING_PROFILE"
            return "ANALYTICS_PROFILE"
        if kind == "support":
            catalogued = any(
                "Attachment catalog" in a.details and "belongs only to" in a.details
                for a in self.evidence.activities_by_resource.get(resource_id, ())
            )
            if (
                "SUPPORT_ATTACHMENT" in signals["types"]
                or "attachment_pii_scan" in signals["events"]
                or "ticket_attachments" in signals["collections"]
                or catalogued
                or any(path.endswith(".pdf") for path in signals["documents"])
                or {"file_name", "file", "storage_class"} & signals["keys"]
            ):
                return "SUPPORT_ATTACHMENT"
            # A deletion-marker check is the source's own statement that this record
            # (a legacy contact entry, not a shared conversation) is due for deletion.
            if "deletion_marker_check" in signals["events"]:
                return "SUPPORT_ATTACHMENT"
            return "SUPPORT_MESSAGE"
        return "UNKNOWN"

    def listing_facts(self, resource_id: str, system_id: str) -> list[Fact]:
        facts = []
        for item in self.listings.get((system_id, prefix(resource_id)), ()):
            absent = resource_id not in item.ids
            if absent:
                assert item.at is not None and item.captured_at is not None
                verdicts: dict[Action, Verdict] = {"DELETE": "COMPLIANT"}
                facts.append(
                    Fact(
                        item.evidence_id, item.at, item.captured_at, item.scope, verdicts, "listing"
                    )
                )
        return facts

    @staticmethod
    def assess(action: Action, facts: list[Fact]) -> tuple[Verdict, Fact | None]:
        """The state at the latest evidence file: any violating replica in it wins."""
        relevant = [f for f in facts if action in f.verdicts]
        if not relevant:
            return "UNKNOWN", None
        newest = max(f.at for f in relevant)
        files = {f.evidence_id for f in relevant if f.at == newest}
        current = [f for f in relevant if f.evidence_id in files]
        # Readbacks of the same file outrank its listings for the same scope.
        readbacks = {f.scope for f in current if f.kind == "readback"}
        current = [f for f in current if f.kind == "readback" or f.scope not in readbacks]
        violations = [f for f in current if f.verdicts[action] == "VIOLATION"]
        chosen = violations or current
        best = max(chosen, key=lambda f: (f.at, f.kind == "readback", f.evidence_id))
        return ("VIOLATION" if violations else "COMPLIANT"), best
