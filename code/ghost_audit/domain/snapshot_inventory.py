"""Read point-in-time inventory values for the submission confidence strategy."""

import re
from collections import defaultdict
from ghost_audit.domain.catalog import COLLECTION_SYSTEMS, SYSTEM_ALIASES
from ghost_audit.domain.catalog import TABLE_SYSTEMS
from ghost_audit.domain.catalog import REPLICA_SUFFIX
from ghost_audit.domain.observation_clocks import observation_time

from ghost_audit.domain.submission_models import Listing
from ghost_audit.domain.submission_semantics import prefix, table_scope, PREFIX_BY_COLLECTION


def snapshot_listings(observations) -> dict:
    """(system, resource kind) -> point-in-time collection contents.

    A SQL snapshot table is a full dump of that table at capture time, and a JSON
    snapshot envelope names its data store and collection and lists its records, so
    a resource of that kind missing from either was not in that copy at that time.
    Callers decide which copies are relevant to a case; this only reads contents."""
    tables = {}
    envelopes = {}
    for o in observations:
        if o.kind != "evidence":
            continue
        p, loc, eid = o.payload, o.provenance.locator, o.provenance.evidence_id
        schema = re.fullmatch(r"sql:(.+):schema", loc)
        row = re.fullmatch(r"sql:(.+):row:\d+", loc)
        if schema and schema[1] != "snapshot_scope":
            tables.setdefault((eid, schema[1]), {"o": o, "rows": defaultdict(set)})["o"] = o
        elif row:
            entry = tables.setdefault((eid, row[1]), {"o": o, "rows": defaultdict(set)})
            for r in o.resources:
                entry["rows"][SYSTEM_ALIASES.get(r.system_id, r.system_id)].add(r.resource_id)
        env = re.fullmatch(r"(\$\.snapshots\[\d+\])", loc)
        rec = re.match(r"(\$\.snapshots\[\d+\])\.records\[\d+\]", loc)
        if env and p.get("data_store") and p.get("collection"):
            envelopes.setdefault((eid, env[1]), {"o": o, "ids": set()})["o"] = o
        elif rec:
            envelopes.setdefault((eid, rec[1]), {"o": o, "ids": set()})["ids"].update(
                r.resource_id for r in o.resources
            )
    listings = defaultdict(list)
    for (eid, table), entry in tables.items():
        o = entry["o"]
        at = observation_time(o) or o.provenance.captured_at
        family = REPLICA_SUFFIX.sub("", table)
        dedicated = TABLE_SYSTEMS.get(family) or COLLECTION_SYSTEMS.get(family)
        rows = dict(entry["rows"])
        if dedicated:
            rows.setdefault(dedicated, set())
        for system, ids in rows.items():
            kinds = {prefix(r) for r in ids} or (
                {PREFIX_BY_COLLECTION[family]} if family in PREFIX_BY_COLLECTION else set()
            )
            for kind in kinds:
                listings[(system, kind)].append(
                    Listing(
                        eid,
                        at,
                        o.provenance.captured_at,
                        system,
                        kind,
                        table_scope(table),
                        frozenset(ids),
                    )
                )
    for (eid, _), entry in envelopes.items():
        o = entry["o"]
        p = o.payload
        if not p.get("data_store"):
            continue
        system = SYSTEM_ALIASES.get(p["data_store"], p["data_store"])
        kinds = {prefix(r) for r in entry["ids"]} or (
            {PREFIX_BY_COLLECTION[p["collection"]]}
            if p["collection"] in PREFIX_BY_COLLECTION
            else set()
        )
        at = observation_time(o) or o.provenance.captured_at
        for kind in kinds:
            listings[(system, kind)].append(
                Listing(
                    eid,
                    at,
                    o.provenance.captured_at,
                    system,
                    kind,
                    "service:" + o.provenance.origin,
                    frozenset(entry["ids"]),
                )
            )
    return listings
