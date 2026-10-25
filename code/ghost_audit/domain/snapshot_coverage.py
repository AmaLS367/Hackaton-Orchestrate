"""Explicit complete-listing coverage; omission alone never proves strict absence."""

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from pydantic import JsonValue

from ghost_audit.domain.association_models import CaseEvidenceBundle
from ghost_audit.domain.catalog import REPLICA_SUFFIX, SYSTEM_ALIASES, TABLE_SYSTEMS
from ghost_audit.domain.models import Observation
from ghost_audit.domain.observation_clocks import logical_collection, observation_time

PAGINATION = ("truncated", "partial", "next_page", "next_cursor")
FILTERS = ("filter", "filters", "where", "subject_selector")


def known_collections(bundle: CaseEvidenceBundle) -> dict[tuple[str | None, str], str | None]:
    """(system, resource) -> its single explicit logical collection among confirmed rows."""
    found = defaultdict(set)
    for item in bundle.observations:
        if item.association == "CONFIRMED":
            for r in item.observation.resources:
                if r.system_id and r.collection:
                    found[(r.system_id, r.resource_id)].add(logical_collection(r))
    return {key: next(iter(values)) for key, values in found.items() if len(values) == 1}


@dataclass(frozen=True)
class Listing:
    """One captured listing of a system's logical collection and what it can prove.

    Omission proves absence only when the listing carries an explicit completeness
    proof and declares neither a filter nor pagination/truncation.
    """

    system: str | None
    collection: str | None
    physical_table: str | None
    observed_at: datetime | None
    surface: Observation
    resource_ids: frozenset[str]
    filter_scope: str | None
    truncated: bool
    proof: str | None

    @property
    def complete(self) -> bool:
        return self.proof is not None and self.filter_scope is None and not self.truncated


def complete_listing(payload: dict[str, JsonValue]) -> bool:
    """An explicit completeness assertion for an unfiltered collection.

    A schema, row_count, empty records array, or snapshot label alone is insufficient.
    """
    return payload.get("complete_listing") is True and not any(
        payload.get(k) for k in (*PAGINATION, *FILTERS)
    )


def listing(
    key: tuple[str | None, str | None],
    at: datetime | None,
    surface: Observation,
    ids: Iterable[str],
    table: str | None = None,
) -> Listing:
    p = surface.payload
    filters = [k for k in FILTERS if p.get(k)]
    return Listing(
        system=key[0],
        collection=key[1],
        physical_table=table,
        observed_at=at,
        surface=surface,
        resource_ids=frozenset(ids),
        filter_scope=",".join(filters) or None,
        truncated=any(p.get(k) for k in PAGINATION),
        proof="complete_listing_flag" if p.get("complete_listing") is True else None,
    )


def coverage_surfaces(
    observations: Iterable[Observation], *, include_incomplete: bool = False
) -> dict[tuple[str | None, str | None], list[Listing]]:
    """(system, logical collection) -> listings captured at one time each.

    A listing is a SQL table (dedicated tables even when empty; generic tables only for
    system/collection pairs they contain) or a JSON snapshot whose envelope names its
    data store and collection. Only complete listings are returned unless requested.
    """
    schemas: dict[tuple[str, str], Observation] = {}
    rows: defaultdict[tuple[str, str], defaultdict[tuple[str | None, str | None], set[str]]] = (
        defaultdict(lambda: defaultdict(set))
    )
    envelopes: dict[tuple[str, str], Observation] = {}
    members: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    for o in observations:
        if o.kind != "evidence":
            continue
        locator, evidence = o.provenance.locator, o.provenance.evidence_id
        table_match = re.fullmatch(r"sql:(.+):schema", locator)
        if table_match:
            schemas[(evidence, table_match[1])] = o
            continue
        row = re.fullmatch(r"sql:(.+):row:\d+", locator)
        if row:
            for r in o.resources:
                if r.system_id and r.collection:
                    rows[(evidence, row[1])][(r.system_id, logical_collection(r))].add(
                        r.resource_id
                    )
            continue
        p = o.payload
        if (
            p.get("data_store")
            and p.get("collection")
            and not p.get("resource_id")
            and re.fullmatch(r"\$\.snapshots\[\d+\]", locator)
        ):
            envelopes[(evidence, locator)] = o
        record = re.match(r"(\$\.snapshots\[\d+\])\.records\[\d+\]", locator)
        if record:
            members[(evidence, record[1])].update(r.resource_id for r in o.resources)
    surfaces: defaultdict[tuple[str | None, str | None], list[Listing]] = defaultdict(list)
    for (evidence, table), schema in schemas.items():
        listed: dict[tuple[str | None, str | None], set[str]] = dict(
            rows.get((evidence, table), {})
        )
        family = REPLICA_SUFFIX.sub("", table)
        if family in TABLE_SYSTEMS:
            listed.setdefault((TABLE_SYSTEMS[family], family), set())
        for key, ids in listed.items():
            surfaces[key].append(listing(key, observation_time(schema), schema, ids, table))
    for envelope_key, envelope in envelopes.items():
        p = envelope.payload
        store, collection = p["data_store"], p["collection"]
        assert isinstance(store, str) and isinstance(collection, str)
        system = SYSTEM_ALIASES.get(store, store)
        surfaces[(system, collection)].append(
            listing(
                (system, collection),
                observation_time(envelope),
                envelope,
                members.get(envelope_key, ()),
            )
        )
    return {
        key: [v for v in values if include_incomplete or v.complete]
        for key, values in surfaces.items()
        if include_incomplete or any(v.complete for v in values)
    }
