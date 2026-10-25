"""Point-in-time inventory interpretation for the submission confidence strategy."""

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from ghost_audit.domain.catalog import (
    COLLECTION_SYSTEMS,
    REPLICA_SUFFIX,
    SYSTEM_ALIASES,
    TABLE_SYSTEMS,
)
from ghost_audit.domain.models import Observation
from ghost_audit.domain.observation_clocks import observation_time
from ghost_audit.domain.submission_models import Listing
from ghost_audit.domain.submission_semantics import PREFIX_BY_COLLECTION, prefix, table_scope

Inventory = dict[tuple[str | None, str], list[Listing]]


@dataclass
class _TableSnapshot:
    observation: Observation
    rows: defaultdict[str | None, set[str]] = field(default_factory=lambda: defaultdict(set))


@dataclass
class _CollectionSnapshot:
    observation: Observation
    ids: set[str] = field(default_factory=set)


def _collect_snapshots(
    observations: Iterable[Observation],
) -> tuple[dict[tuple[str, str], _TableSnapshot], dict[tuple[str, str], _CollectionSnapshot]]:
    tables: dict[tuple[str, str], _TableSnapshot] = {}
    envelopes: dict[tuple[str, str], _CollectionSnapshot] = {}
    for observation in observations:
        if observation.kind != "evidence":
            continue
        payload = observation.payload
        locator, evidence_id = observation.provenance.locator, observation.provenance.evidence_id
        schema = re.fullmatch(r"sql:(.+):schema", locator)
        row = re.fullmatch(r"sql:(.+):row:\d+", locator)
        if schema and schema[1] != "snapshot_scope":
            tables.setdefault(
                (evidence_id, schema[1]), _TableSnapshot(observation)
            ).observation = observation
        elif row:
            entry = tables.setdefault((evidence_id, row[1]), _TableSnapshot(observation))
            for resource in observation.resources:
                system = (
                    SYSTEM_ALIASES.get(resource.system_id, resource.system_id)
                    if resource.system_id
                    else None
                )
                entry.rows[system].add(resource.resource_id)
        envelope = re.fullmatch(r"(\$\.snapshots\[\d+\])", locator)
        record = re.match(r"(\$\.snapshots\[\d+\])\.records\[\d+\]", locator)
        if envelope and payload.get("data_store") and payload.get("collection"):
            envelopes.setdefault(
                (evidence_id, envelope[1]), _CollectionSnapshot(observation)
            ).observation = observation
        elif record:
            envelopes.setdefault(
                (evidence_id, record[1]), _CollectionSnapshot(observation)
            ).ids.update(resource.resource_id for resource in observation.resources)
    return tables, envelopes


def snapshot_listings(observations: Iterable[Observation]) -> Inventory:
    """Read snapshot contents without assigning their relevance to any subject.

    Submission treats a supplied SQL dump or named JSON snapshot as a collection
    inventory. Strict audit uses the separate explicit-completeness contract.
    """
    tables, envelopes = _collect_snapshots(observations)
    listings: defaultdict[tuple[str | None, str], list[Listing]] = defaultdict(list)
    for (evidence_id, table), entry in tables.items():
        observation = entry.observation
        at = observation_time(observation) or observation.provenance.captured_at
        family = REPLICA_SUFFIX.sub("", table)
        dedicated = TABLE_SYSTEMS.get(family) or COLLECTION_SYSTEMS.get(family)
        rows = dict(entry.rows)
        if dedicated:
            rows.setdefault(dedicated, set())
        for system, ids in rows.items():
            kinds = {prefix(resource) for resource in ids} or (
                {PREFIX_BY_COLLECTION[family]} if family in PREFIX_BY_COLLECTION else set()
            )
            for kind in kinds:
                listings[(system, kind)].append(
                    Listing(
                        evidence_id,
                        at,
                        observation.provenance.captured_at,
                        system,
                        kind,
                        table_scope(table),
                        frozenset(ids),
                    )
                )
    for (evidence_id, _), collection in envelopes.items():
        observation = collection.observation
        payload = observation.payload
        store = payload.get("data_store")
        if not store:
            continue
        assert isinstance(store, str), "Snapshot data_store must name a system"
        system = SYSTEM_ALIASES.get(store, store)
        collection_name = payload["collection"]
        assert isinstance(collection_name, str), "Snapshot collection must be a name"
        kinds = {prefix(resource) for resource in collection.ids} or (
            {PREFIX_BY_COLLECTION[collection_name]}
            if collection_name in PREFIX_BY_COLLECTION
            else set()
        )
        at = observation_time(observation) or observation.provenance.captured_at
        for kind in kinds:
            listings[(system, kind)].append(
                Listing(
                    evidence_id,
                    at,
                    observation.provenance.captured_at,
                    system,
                    kind,
                    "service:" + observation.provenance.origin,
                    frozenset(collection.ids),
                )
            )
    return listings
