"""Shared extraction utilities. Observations retain facts, never deletion verdicts."""

import csv
import io
import re
from dataclasses import dataclass, replace

from pydantic import JsonValue

from .models import EvidenceFile, Observation, Provenance, ResourceRef, SourceTimestamp

ISO_TOKEN = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})"
BUSINESS_TIMES = {"expires_at", "retention_until", "retained_until", "next_run_at", "scheduled_at"}
SOURCE_TIMES = {
    "captured_at", "exported_at", "recorded_at", "observed_at", "event_time",
    "updated_at", "created_at", "timestamp", "snapshot", "snapshot_at",
}
SYSTEM_FIELDS = ("system_id", "system", "origin_system", "data_store")


def timestamps(payload: dict, locator: str, recursive: bool = False) -> list[SourceTimestamp]:
    result = []
    for key, value in payload.items():
        field = key.lower().replace(" ", "_")
        if field in SOURCE_TIMES | BUSINESS_TIMES and value not in (None, ""):
            # Date-only business deadlines stay losslessly in the payload.
            if field in BUSINESS_TIMES and isinstance(value, str) and len(value) == 10:
                continue
            result.append(SourceTimestamp(
                locator=f"{locator}.{key}", field=key, value=value,
                role="business" if field in BUSINESS_TIMES else "source",
            ))
        if recursive and isinstance(value, dict):
            result.extend(timestamps(value, f"{locator}.{key}", True))
        elif recursive and isinstance(value, list):
            for index, child in enumerate(value):
                if isinstance(child, dict):
                    result.extend(timestamps(child, f"{locator}.{key}[{index}]", True))
    return result


@dataclass(frozen=True)
class ExtractionContext:
    manifest: EvidenceFile
    sha256: str
    times: tuple[SourceTimestamp, ...] = ()
    system: str | None = None
    collection: str | None = None

    def scoped(self, payload: dict, locator: str) -> "ExtractionContext":
        system = next((payload[k] for k in SYSTEM_FIELDS if payload.get(k)), self.system)
        return replace(
            self, times=(*self.times, *timestamps(payload, locator)), system=system,
            collection=payload.get("collection", payload.get("collection_name", self.collection)),
        )

    def observation(self, payload: dict[str, JsonValue], locator: str,
                    raw_text: str = "", trace_id: str | None = None,
                    recursive_times: bool = False) -> Observation:
        scope = self.scoped(payload, locator)
        times = list(scope.times)
        if recursive_times:
            direct = {t.locator for t in timestamps(payload, locator)}
            times.extend(t for t in timestamps(payload, locator, True) if t.locator not in direct)
        resource = payload.get("resource_id")
        systems = {scope.system} if scope.system else set()
        systems.update(payload[k] for k in ("source_system", "target_system") if payload.get(k))
        return Observation(
            provenance=Provenance(
                evidence_id=self.manifest.file_id, file_path=self.manifest.file_path,
                origin=self.manifest.origin, locator=locator,
                captured_at=self.manifest.captured_at, sha256=self.sha256, timestamps=times,
            ), payload=payload, raw_text=raw_text, trace_id=trace_id,
            resources=[ResourceRef(resource_id=resource, system_id=scope.system,
                                   collection=scope.collection)] if resource else [],
            system_ids=sorted(systems),
        )


def parse_json(value: JsonValue, context: ExtractionContext,
               locator: str = "$") -> list[Observation]:
    if isinstance(value, list):
        return [item for i, child in enumerate(value)
                for item in parse_json(child, context, f"{locator}[{i}]")]
    if not isinstance(value, dict):
        return [context.observation({"value": value}, locator)]
    if value.get("resource_id"):
        return [context.observation(value, locator, recursive_times=True)]
    scope = context.scoped(value, locator)
    observations = []
    # Preserve envelope metadata without indexing every unrelated record together.
    scalars = {k: v for k, v in value.items() if not isinstance(v, (dict, list))}
    if scalars:
        observations.append(context.observation(scalars, locator))
    for key, child in value.items():
        if not isinstance(child, (dict, list)):
            continue
        child_scope = scope
        if key == "service_exports" and isinstance(child, dict):
            for system, exported in child.items():
                observations.extend(parse_json(exported, replace(scope, system=system),
                                               f"{locator}.{key}.{system}"))
        else:
            observations.extend(parse_json(child, child_scope, f"{locator}.{key}"))
    if not value:
        observations.append(context.observation({}, locator))
    return observations


def parse_csv(text: str, context: ExtractionContext) -> list[Observation]:
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if (not reader.fieldnames or any(not name.strip() for name in reader.fieldnames)
            or len(set(reader.fieldnames)) != len(reader.fieldnames)):
        raise ValueError("CSV evidence requires nonduplicate headers")
    observations = []
    for row_no, row in enumerate(reader, 2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"malformed CSV evidence row {row_no}")
        observations.append(context.observation(row, f"row:{row_no}"))
    return observations


LOG_LINE = re.compile(
    rf"^(?P<timestamp>{ISO_TOKEN}) \[(?P<level>[^]]+)\] "
    r"\[(?P<system>[^]]+)\] \[(?P<trace>[^]]+)\] (?P<event>[^:]+):\s*(?P<fields>.*)$"
)
KEY_VALUE = re.compile(r'([A-Za-z_][\w.-]*)=("(?:[^"\\]|\\.)*"|\S+)')


def parse_text(text: str, context: ExtractionContext,
               locator_prefix: str = "line") -> list[Observation]:
    observations = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        locator = f"{locator_prefix}:{number}"
        payload: dict = {"text": line}
        match = LOG_LINE.match(line)
        trace = None
        if match:
            payload.update({"timestamp": match['timestamp'], "system": match['system'],
                            "level": match['level'], "event": match['event']})
            trace = match['trace']
            for key, value in KEY_VALUE.findall(match['fields']):
                # Preserve the original value; no coercion of "0", "null", or "false".
                payload[key] = value[1:-1] if value.startswith('"') else value
        else:
            parts = [part.strip() for part in line.removeprefix("- ").split("|")]
            if len(parts) == 6 and re.fullmatch(ISO_TOKEN, parts[0]):
                payload.update(dict(zip(
                    ("recorded_at", "system", "resource_id", "record_type", "result", "subject_reference"),
                    parts, strict=True,
                )))
            else:
                timestamp = re.match(rf"(?:Snapshot:\s*|^)(?P<time>{ISO_TOKEN})", line)
                if timestamp:
                    payload['timestamp'] = timestamp['time']
        observations.append(context.observation(payload, locator, raw_text=line, trace_id=trace))
        if line.startswith("Snapshot:") and 'timestamp' in payload:
            context = context.scoped({"snapshot": payload['timestamp']}, locator)
    return observations
