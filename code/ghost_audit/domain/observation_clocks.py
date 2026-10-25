"""Observation clocks, availability gates and scalar interpretation."""

import re
from ghost_audit.domain.models import Observation, ResourceRef
from ghost_audit.domain.catalog import TABLE_SYSTEMS

from ghost_audit.domain.catalog import REPLICA_SUFFIX


def logical_collection(reference: ResourceRef) -> str | None:
    collection = reference.collection
    if collection and reference.physical_table == collection:
        base = REPLICA_SUFFIX.sub("", collection)
        if base in TABLE_SYSTEMS:
            return base
    return collection


def replica_scope(observation: Observation, reference: ResourceRef) -> str:
    p = observation.payload
    explicit = p.get("replica_scope") or p.get("replica") or p.get("source_scope")
    if isinstance(explicit, str) and explicit:
        return explicit
    if reference.physical_table:
        match = REPLICA_SUFFIX.search(reference.physical_table)
        return match[1] if match else "table:" + reference.physical_table
    # Region denotes a distinct read surface; never erase another region's state.
    region = p.get("region")
    source = "service:" + observation.provenance.origin
    return source + ":" + str(region) if region else source


def observation_time(o: Observation):
    """A snapshot's clock is not row updated_at or a later packaging/export clock."""
    times = [t for t in o.provenance.timestamps if t.role == "source"]
    clocks = [
        t
        for t in times
        if t.field.lower()
        in {
            "observed_at",
            "recorded_at",
            "event_time",
            "timestamp",
            "snapshot",
            "snapshot_at",
            "captured_at",
        }
    ]
    if clocks:
        # Deeper scoped clocks describe the actual observation, not its envelope.
        depth = max(t.locator.rsplit(".", 1)[0].count(".") + t.locator.count("[") for t in clocks)
        deepest = [
            t
            for t in clocks
            if t.locator.rsplit(".", 1)[0].count(".") + t.locator.count("[") == depth
        ]
        # An explicit observation clock wins over incidental metadata at its scope.
        priorities = {
            "observed_at": 3,
            "recorded_at": 3,
            "event_time": 3,
            "timestamp": 3,
            "snapshot": 2,
            "snapshot_at": 2,
            "captured_at": 2,
        }
        priority = max(priorities[t.field.lower()] for t in deepest)
        return max(t.value for t in deepest if priorities[t.field.lower()] == priority)
    return o.provenance.captured_at or o.available_at


def linkage_time(o: Observation):
    """The source-side time of an observation's facts: its own observation clock, never
    earlier than a record time it reports. This orders facts; it is not availability."""
    at = observation_time(o)
    if at is None:
        return None
    record_times = [
        t.value
        for t in o.provenance.timestamps
        if t.role == "source" and t.field.lower() in {"updated_at", "created_at"}
    ]
    return max([at, *record_times])


def known_at(o: Observation):
    """When an auditor could first know an observation's facts, ownership included.

    The official contract decides each case only from information available at its
    audit_at, so a later export or catalogue link never establishes an earlier fact:
    every clock the observation depends on (capture, packaging, catalogue link,
    observation and record times) must have passed.
    """
    times = [t for t in (o.available_at, linkage_time(o)) if t is not None]
    return max(times) if times else None


def time_profile(o: Observation) -> dict:
    """observed_at/effective_at/captured_at/known_at of one observation, for diagnostics."""
    effective = [
        t.value
        for t in o.provenance.timestamps
        if t.role == "source" and t.field.lower() in {"updated_at", "created_at"}
    ]
    return {
        "observed_at": observation_time(o),
        "effective_at": max(effective, default=None),
        "captured_at": o.provenance.captured_at,
        "known_at": known_at(o),
    }


def boolean(value):
    if value is True or type(value) is int and value == 1 or value in ("true", "1"):
        return True
    if value is False or type(value) is int and value == 0 or value in ("false", "0"):
        return False
    return None


def integer(value):
    # bool is deliberately not a row count.
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"\d+", value):
        return int(value)
    return None
