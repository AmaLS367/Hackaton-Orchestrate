"""Exact, cutoff-aware alias ownership. No fuzzy matching or derived hashes."""

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from ghost_audit.domain.association_models import IdentityAlias, ResolvedIdentity
from ghost_audit.domain.evidence_index import normalize_identifier
from ghost_audit.domain.models import DeletionRequest, Identity, IdentityChange
from ghost_audit.domain.time import parse_timestamp

IDENTITY_FIELDS: tuple[Literal["user_id", "email", "phone", "email_hash", "name"], ...] = (
    "user_id",
    "email",
    "phone",
    "email_hash",
    "name",
)

FIELDS: tuple[Literal["email", "phone", "email_hash", "name"], ...] = (
    "email",
    "phone",
    "email_hash",
    "name",
)


class IdentityResolver:
    """Resolve exact identity facts only when available by the requested cutoff."""

    def __init__(self, identities: Iterable[Identity], changes: Iterable[IdentityChange]):
        self.snapshots = {row.user_id: row for row in identities}
        self.changes: defaultdict[str, list[IdentityChange]] = defaultdict(list)
        # Ownership facts carry the time they became available, including old_value.
        self.by_identifier: defaultdict[str, list[tuple[str, datetime]]] = defaultdict(list)
        self.by_email: defaultdict[str, list[tuple[str, datetime]]] = defaultdict(list)
        for row in self.snapshots.values():
            for field in IDENTITY_FIELDS:
                self._index(field, getattr(row, field), row.user_id, row.updated_at)
        for change in sorted(changes, key=lambda r: (r.event_time, r.audit_id)):
            self.changes[change.user_id].append(change)
            self._index("user_id", change.user_id, change.user_id, change.event_time)
            if change.field_name in FIELDS:
                for value in (change.old_value, change.new_value):
                    self._index(change.field_name, value, change.user_id, change.event_time)

    def _index(self, field: str, value: str, user: str, at: datetime) -> None:
        if not value.strip() or field == "name":
            return
        key = normalize_identifier(value)
        self.by_identifier[key].append((user, at))
        if field == "email":
            self.by_email[key].append((user, at))

    def owners(self, value: str, audit_at: str | datetime) -> set[str]:
        """Return exact owners whose identifier statement was available by the cutoff."""
        cutoff = parse_timestamp(audit_at)
        return {
            user
            for user, at in self.by_identifier.get(normalize_identifier(value), ())
            if at <= cutoff
        }

    def resolve(
        self, request: DeletionRequest | str, audit_at: str | datetime | None = None
    ) -> ResolvedIdentity:
        """Resolve a request email uniquely or retain ambiguity and historical aliases."""
        if isinstance(request, DeletionRequest):
            email = request.email
            cutoff = parse_timestamp(audit_at) if audit_at is not None else request.audit_at
        else:
            if audit_at is None:
                raise ValueError("audit_at is required for email resolution")
            email, cutoff = request, parse_timestamp(audit_at)
        candidates = sorted(
            {
                user
                for user, at in self.by_email.get(normalize_identifier(email), ())
                if at <= cutoff
            }
        )
        if len(candidates) != 1:
            return ResolvedIdentity(
                status="AMBIGUOUS" if candidates else "UNRESOLVED",
                candidates=candidates,
                ambiguities=["request_email_has_multiple_owners"] if candidates else [],
            )
        user = candidates[0]
        aliases, issues = self.aliases_for(user, cutoff)
        for alias in aliases:
            if alias.field_name != "name" and len(self.owners(alias.normalized_value, cutoff)) > 1:
                issues.add("shared_alias:" + alias.field_name)
        return ResolvedIdentity(
            status="RESOLVED",
            user_id=user,
            candidates=candidates,
            aliases=aliases,
            ambiguities=sorted(issues),
        )

    def aliases_for(
        self, user: str, audit_at: str | datetime
    ) -> tuple[list[IdentityAlias], set[str]]:
        """Reconstruct alias statements and bounded intervals without using future transitions."""
        cutoff = parse_timestamp(audit_at)
        snapshot = self.snapshots.get(user)
        visible_snapshot = snapshot if snapshot and snapshot.updated_at <= cutoff else None
        changes = [c for c in self.changes.get(user, ()) if c.event_time <= cutoff]
        facts = []
        issues = set()
        if visible_snapshot:
            for field in IDENTITY_FIELDS:
                value = getattr(visible_snapshot, field)
                if value.strip():
                    facts.append(
                        IdentityAlias(
                            field_name=field,
                            normalized_value=normalize_identifier(value),
                            original_value=value,
                            source="identity_snapshot",
                            event_time=visible_snapshot.updated_at,
                            value_role="snapshot",
                            valid_from=visible_snapshot.updated_at,
                            active_at_cutoff=None,
                        )
                    )
        for change in changes:
            facts.append(
                IdentityAlias(
                    field_name="user_id",
                    normalized_value=normalize_identifier(user),
                    original_value=user,
                    source="audit_log",
                    audit_id=change.audit_id,
                    event_time=change.event_time,
                    value_role="new_value",
                    valid_from=change.event_time,
                    active_at_cutoff=True,
                )
            )
            if change.field_name not in FIELDS:
                continue
            roles: tuple[Literal["old_value", "new_value"], ...] = ("old_value", "new_value")
            for role in roles:
                value = getattr(change, role)
                if value.strip():
                    facts.append(
                        IdentityAlias.model_validate(
                            {
                                "field_name": change.field_name,
                                "normalized_value": normalize_identifier(value),
                                "original_value": value,
                                "source": "audit_log",
                                "audit_id": change.audit_id,
                                "event_time": change.event_time,
                                "value_role": role,
                                "valid_from": change.event_time if role == "new_value" else None,
                                "valid_until": change.event_time if role == "old_value" else None,
                                "active_at_cutoff": None,
                            }
                        )
                    )
        # Latest known field statement establishes the active alias at the cutoff.
        # A later snapshot is never rolled backwards using future audit events.
        active: dict[str, set[str]] = {}
        for field in FIELDS:
            field_changes = [c for c in changes if c.field_name == field]
            timeline = [
                (c.event_time, "audit", normalize_identifier(c.new_value)) for c in field_changes
            ]
            if visible_snapshot:
                timeline.append(
                    (
                        visible_snapshot.updated_at,
                        "snapshot",
                        normalize_identifier(getattr(visible_snapshot, field)),
                    )
                )
            if timeline:
                latest = max(t[0] for t in timeline)
                values = {v for at, _, v in timeline if at == latest}
                active[field] = values
                if len(values) > 1:
                    issues.add("conflicting_latest_values:" + field)
            for earlier, later in zip(field_changes, field_changes[1:], strict=False):
                if normalize_identifier(earlier.new_value) != normalize_identifier(later.old_value):
                    issues.add("discontinuous_history:" + field)
        result = []
        for alias in facts:
            values = active.get(alias.field_name, {normalize_identifier(user)})
            is_active = alias.normalized_value in values if len(values) == 1 else None
            # Only bound an interval when an observed transition supports its end.
            endings = [
                c.event_time
                for c in changes
                if c.field_name == alias.field_name
                and normalize_identifier(c.old_value) == alias.normalized_value
                and c.event_time >= (alias.valid_from or alias.event_time)
            ]
            result.append(
                alias.model_copy(
                    update={
                        "active_at_cutoff": is_active,
                        "valid_until": min(endings) if endings else alias.valid_until,
                    }
                )
            )
        result.sort(
            key=lambda a: (
                a.event_time,
                a.field_name,
                a.audit_id or "",
                a.value_role,
                a.normalized_value,
            )
        )
        return result, issues
