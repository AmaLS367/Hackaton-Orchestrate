"""Index exact submission ownership facts without selecting workflow assignments."""

from collections import defaultdict
from datetime import datetime

from pydantic import JsonValue

from ghost_audit.domain.catalog import SYSTEM_ALIASES
from ghost_audit.domain.dataset import Dataset
from ghost_audit.domain.evidence_index import identifier_values, normalize_identifier
from ghost_audit.domain.identity import IdentityResolver
from ghost_audit.domain.intent import IntentClassifier
from ghost_audit.domain.models import DeletionRequest
from ghost_audit.domain.record_interpretation import record_payload
from ghost_audit.domain.submission_semantics import QUERY_KEYS, SYSTEM_BY_PREFIX, prefix, sha256


class SubmissionEvidence:
    """Index exact identifier and resource statements for the submission strategy."""

    def __init__(self, dataset: Dataset) -> None:
        self.dataset = dataset
        self.observations = dataset.observations
        self.resolver = IdentityResolver(dataset.identities, dataset.identity_changes)
        self.classifier = IntentClassifier()
        self.requests = list(getattr(dataset, "workflow_requests", None) or dataset.requests)
        self.activities_by_resource = defaultdict(list)
        for a in dataset.activities:
            if a.resource_id:
                self.activities_by_resource[a.resource_id].append(a)
        self._index_identifiers()
        self._index_observations()

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
                if change.field_name == "name":
                    names[normalize_identifier(value)].add(change.user_id)
                    continue
                values[change.user_id].add(normalize_identifier(value))
                if change.field_name == "email":
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

    def users_in(self, value: object) -> set[str]:
        """Find exact known identity atoms in extracted scalar or nested values."""
        found = set()
        for token in identifier_values(value):
            found |= self.owners_by_value.get(token, set())
        return found

    def user_for(self, request: DeletionRequest) -> tuple[str | None, str | None]:
        """Resolve the request subject and disclose the submission cutoff fallback."""
        identity = self.resolver.resolve(request)
        if identity.status == "RESOLVED":
            return identity.user_id, None
        owners = self.owners_by_value.get(normalize_identifier(request.email), set())
        if len(owners) == 1:
            return next(iter(owners)), "identity_resolved_without_cutoff"
        return None, "identity_unresolved"

    def _index_observations(self):
        self.by_resource = defaultdict(list)
        groups = defaultdict(list)
        for i, o in enumerate(self.observations):
            if o.kind == "evidence" and o.trace_id:
                groups[(o.provenance.evidence_id, o.trace_id)].append(i)
        self.obs_users = {}
        self.obs_resources = {}
        self.negative_trace = {}
        for i, o in enumerate(self.observations):
            if o.kind != "evidence":
                continue
            members = groups.get((o.provenance.evidence_id, o.trace_id), [i]) if o.trace_id else [i]
            self.obs_users[i] = set().union(
                *(self.users_in(self.observations[j].payload) for j in members)
            )
            self.obs_resources[i] = {
                r.resource_id for j in members for r in self.observations[j].resources
            }
            # A lookup by key that found nothing does not tie the key to the resource.
            self.negative_trace[i] = any(
                self._negative(self.observations[j].payload) for j in members
            ) and not any(
                self.users_in(
                    {
                        k: v
                        for k, v in self.observations[j].payload.items()
                        if k not in QUERY_KEYS | {"text", "message"}
                    }
                )
                for j in members
            )
            for r in o.resources:
                self.by_resource[r.resource_id].append(i)
        # resource -> user -> [(available_at, strength)]
        self.explicit: defaultdict[str, defaultdict[str, list[tuple[datetime, str]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for i, users in self.obs_users.items():
            at = self.observations[i].available_at
            if at is None:
                continue
            strength = "lookup" if self.negative_trace[i] else "record"
            for resource in self.obs_resources[i]:
                for user in users:
                    self.explicit[resource][user].append((at, strength))
        for a in self.dataset.activities:
            if a.event_type == "LINK_RESOURCE_IDENTITY" and a.resource_id:
                for user in self.users_in(a.details):
                    self.explicit[a.resource_id][user].append((a.event_time, "catalog"))

    @staticmethod
    def _negative(payload: dict[str, JsonValue]) -> bool:
        data = record_payload(payload)
        return (
            str(data.get("result", "")).upper() in {"NOT_FOUND", "MISS"}
            or str(data.get("http_status", data.get("status_code", ""))) == "404"
            or str(data.get("rows", "")) == "0"
        )

    def owners(
        self, resource_id: str, cutoff: datetime | None = None, strong: bool = False
    ) -> set[str]:
        """Filter observed resource owners by cutoff and optional non-lookup strength."""
        return {
            user
            for user, links in self.explicit.get(resource_id, {}).items()
            if any(
                (cutoff is None or at <= cutoff) and (not strong or kind != "lookup")
                for at, kind in links
            )
        }

    def system_of(self, resource_id: str) -> str | None:
        """Select the supported resource system with deterministic tie-breaking."""
        systems: defaultdict[str, int] = defaultdict(int)
        for i in self.by_resource.get(resource_id, ()):
            for r in self.observations[i].resources:
                if r.resource_id == resource_id and r.system_id:
                    systems[SYSTEM_ALIASES.get(r.system_id, r.system_id)] += 1
        for a in self.activities_by_resource.get(resource_id, ()):
            if a.source_system == "deletion_worker" and a.target_system:
                systems[a.target_system] += 1
        if systems:
            return max(sorted(systems), key=systems.__getitem__)
        return SYSTEM_BY_PREFIX.get(prefix(resource_id))
