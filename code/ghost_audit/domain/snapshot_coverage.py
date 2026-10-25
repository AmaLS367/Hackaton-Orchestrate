"""Explicit complete-listing coverage; omission alone never proves strict absence."""

import re
from collections import defaultdict
from dataclasses import dataclass
from ghost_audit.domain.catalog import SYSTEM_ALIASES
from ghost_audit.domain.models import Observation
from ghost_audit.domain.association_models import CaseEvidenceBundle
from ghost_audit.domain.catalog import REPLICA_SUFFIX
from ghost_audit.domain.observation_clocks import logical_collection, observation_time
from ghost_audit.domain.catalog import TABLE_SYSTEMS

PAGINATION = ("truncated", "partial", "next_page", "next_cursor")
FILTERS = ("filter", "filters", "where", "subject_selector")


def known_collections(bundle: CaseEvidenceBundle) -> dict[tuple, str]:
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

    system: str
    collection: str
    physical_table: str | None
    observed_at: object
    surface: Observation
    resource_ids: frozenset
    filter_scope: str | None
    truncated: bool
    proof: str | None

    @property
    def complete(self) -> bool:
        return self.proof is not None and self.filter_scope is None and not self.truncated


def complete_listing(payload):
    """An explicit completeness assertion for an unfiltered collection.

    A schema, row_count, empty records array, or snapshot label alone is insufficient.
    """
    return payload.get("complete_listing") is True and not any(
        payload.get(k) for k in (*PAGINATION, *FILTERS)
    )


def listing(key, at, surface, ids, table=None) -> Listing:
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


def coverage_surfaces(observations, *, include_incomplete=False) -> dict[tuple, list[Listing]]:
    """(system, logical collection) -> listings captured at one time each.

    A listing is a SQL table (dedicated tables even when empty; generic tables only for
    system/collection pairs they contain) or a JSON snapshot whose envelope names its
    data store and collection. Only complete listings are returned unless requested.
    """
    schemas, rows = {}, defaultdict(lambda: defaultdict(set))
    envelopes, members = {}, defaultdict(set)
    for o in observations:
        if o.kind != "evidence":
            continue
        locator, evidence = o.provenance.locator, o.provenance.evidence_id
        table = re.fullmatch(r"sql:(.+):schema", locator)
        if table:
            schemas[(evidence, table[1])] = o
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
    surfaces = defaultdict(list)
    for (evidence, table), schema in schemas.items():
        listed = dict(rows.get((evidence, table), {}))
        family = REPLICA_SUFFIX.sub("", table)
        if family in TABLE_SYSTEMS:
            listed.setdefault((TABLE_SYSTEMS[family], family), set())
        for key, ids in listed.items():
            surfaces[key].append(listing(key, observation_time(schema), schema, ids, table))
    for key, envelope in envelopes.items():
        p = envelope.payload
        system = SYSTEM_ALIASES.get(p["data_store"], p["data_store"])
        surfaces[(system, p["collection"])].append(
            listing(
                (system, p["collection"]),
                observation_time(envelope),
                envelope,
                members.get(key, ()),
            )
        )
    return {
        key: [v for v in values if include_incomplete or v.complete]
        for key, values in surfaces.items()
        if include_incomplete or any(v.complete for v in values)
    }
