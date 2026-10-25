"""Shared extraction utilities. Observations retain facts, never deletion verdicts."""

import csv
import io
import json
import re
from ghost_audit.domain.catalog import (
    ISO_TOKEN,
    BUSINESS_TIMES,
    SOURCE_TIMES,
    SYSTEM_FIELDS,
    SYSTEM_ALIASES,
    collection_system,
)
from dataclasses import dataclass, replace

from pydantic import JsonValue

from ghost_audit.domain.models import (
    EvidenceFile,
    Observation,
    Provenance,
    ResourceRef,
    SourceTimestamp,
)

# Participant collections whose owning system is fixed by schema even when an
# export omits the system; never inferred from resource-ID prefixes.
# Read surfaces that report on another system's records under their own name.


def timestamps(payload: dict, locator: str, recursive: bool = False) -> list[SourceTimestamp]:
    result = []
    for key, value in payload.items():
        field = key.lower().replace(" ", "_")
        if field in SOURCE_TIMES | BUSINESS_TIMES and value not in (None, ""):
            # Date-only business deadlines stay losslessly in the payload.
            if field in BUSINESS_TIMES and isinstance(value, str) and len(value) == 10:
                continue
            result.append(
                SourceTimestamp(
                    locator=f"{locator}.{key}",
                    field=key,
                    value=value,
                    role="business" if field in BUSINESS_TIMES else "source",
                )
            )
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
    physical_table: str | None = None

    def scoped(self, payload: dict, locator: str) -> "ExtractionContext":
        decoded = payload.get("decoded_record")
        decoded = decoded if isinstance(decoded, dict) else {}
        system = next(
            (source[k] for source in (payload, decoded) for k in SYSTEM_FIELDS if source.get(k)),
            self.system,
        )
        inherited = self.collection if self.system in (None, system) else None
        # An envelope collection describes its own data store, not records that
        # explicitly name another system (for example operational lookup lists).
        collection = next(
            (
                source[k]
                for source in (payload, decoded)
                for k in ("collection_name", "collection")
                if source.get(k)
            ),
            inherited,
        )
        return replace(
            self,
            times=(*self.times, *timestamps(payload, locator)),
            system=system,
            collection=collection,
        )

    def observation(
        self,
        payload: dict[str, JsonValue],
        locator: str,
        raw_text: str = "",
        trace_id: str | None = None,
        recursive_times: bool = False,
    ) -> Observation:
        scope = self.scoped(payload, locator)
        times = list(scope.times)
        if recursive_times:
            direct = {t.locator for t in timestamps(payload, locator)}
            times.extend(t for t in timestamps(payload, locator, True) if t.locator not in direct)
        decoded = payload.get("decoded_record")
        resource = payload.get("resource_id") or (
            decoded.get("resource_id") if isinstance(decoded, dict) else None
        )
        system = SYSTEM_ALIASES.get(scope.system, scope.system) or collection_system(
            scope.collection
        )
        scope = replace(scope, system=system)
        systems = {scope.system} if scope.system else set()
        systems.update(payload[k] for k in ("source_system", "target_system") if payload.get(k))
        return Observation(
            provenance=Provenance(
                evidence_id=self.manifest.file_id,
                file_path=self.manifest.file_path,
                origin=self.manifest.origin,
                locator=locator,
                captured_at=self.manifest.captured_at,
                sha256=self.sha256,
                timestamps=times,
            ),
            payload=payload,
            raw_text=raw_text,
            trace_id=trace_id or payload.get("trace_id"),
            resources=[
                ResourceRef(
                    resource_id=resource,
                    system_id=scope.system,
                    collection=scope.collection,
                    physical_table=scope.physical_table,
                )
            ]
            if resource
            else [],
            system_ids=sorted(systems),
        )


def parse_json(
    value: JsonValue, context: ExtractionContext, locator: str = "$"
) -> list[Observation]:
    if isinstance(value, list):
        return [
            item
            for i, child in enumerate(value)
            for item in parse_json(child, context, f"{locator}[{i}]")
        ]
    if not isinstance(value, dict):
        return [context.observation({"value": value}, locator)]
    if value.get("resource_id"):
        return [context.observation(value, locator, recursive_times=True)]
    scope = context.scoped(value, locator)
    observations = []
    # Preserve envelope metadata without indexing every unrelated record together.
    scalars = {k: v for k, v in value.items() if not isinstance(v, (dict, list))}
    # Scope/pagination metadata must survive on its listing envelope, including
    # structured filters. Dropping it could turn a partial export into absence proof.
    scalars.update({k: value[k] for k in ("filter", "filters", "where") if k in value})
    if scalars:
        observations.append(context.observation(scalars, locator))
    for key, child in value.items():
        if not isinstance(child, (dict, list)):
            continue
        child_scope = scope
        if key == "service_exports" and isinstance(child, dict):
            for system, exported in child.items():
                observations.extend(
                    parse_json(exported, replace(scope, system=system), f"{locator}.{key}.{system}")
                )
        else:
            observations.extend(parse_json(child, child_scope, f"{locator}.{key}"))
    if not value:
        observations.append(context.observation({}, locator))
    return observations


def parse_csv(text: str, context: ExtractionContext) -> list[Observation]:
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if (
        not reader.fieldnames
        or any(not name.strip() for name in reader.fieldnames)
        or len(set(reader.fieldnames)) != len(reader.fieldnames)
    ):
        raise ValueError("CSV evidence requires nonduplicate headers")
    observations = []
    for row_no, row in enumerate(reader, 2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"malformed CSV evidence row {row_no}")
        observations.append(context.observation(row, f"row:{row_no}"))
    return observations


KEY_VALUE = re.compile(
    r"""(?<![\w.-])([A-Za-z_][\w.-]*)=("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|[^\s\]]+)"""
)
LEVELS = r"TRACE|DEBUG|INFO|WARN|WARNING|ERROR|CRITICAL|FATAL|NOTICE|ALERT|EMERG"


def parse_fields(text: str) -> dict[str, str]:
    """Decode quoting, keeping unquoted scalars and unknown escapes lossless."""
    fields = {}
    for key, value in KEY_VALUE.findall(text):
        if value.startswith(('"', "'")):
            try:
                decoded = json.loads(value) if value.startswith('"') else None
            except json.JSONDecodeError:
                decoded = None
            value = (
                decoded if decoded is not None else re.sub(r"""\\(["'\\\]])""", r"\1", value[1:-1])
            )
        fields[key] = value
    return fields


def parse_bracket_log(body: str) -> dict | None:
    match = re.fullmatch(
        r"\[(?P<level>[^]]+)\]\s+\[(?P<service>[^]]+)\]\s+"
        r"(?:\[(?P<trace_id>[^]]+)\]\s+)?(?P<event>[^:]+):\s*(?P<fields>.*)",
        body,
    )
    if not match:
        return None
    return {
        "system": match["service"],
        **{k: v for k, v in match.groupdict().items() if k != "fields" and v is not None},
        **parse_fields(match["fields"]),
    }


def parse_pipe_log(body: str) -> dict | None:
    match = re.fullmatch(
        rf"\|\s*(?P<level>{LEVELS})\s*\|\s*(?P<service>[^|]+?)\s*\|\s*"
        r"(?P<trace_id>[^|]+?)\s*\|\s*(?P<event>[^|]+?)\s*\|\s*(?P<fields>.*)",
        body,
    )
    if not match:
        return None
    return {
        **{k: v for k, v in match.groupdict().items() if k != "fields"},
        **parse_fields(match["fields"]),
    }


def parse_json_log(body: str) -> dict | None:
    if not body.startswith("{"):
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def parse_key_value_log(body: str) -> dict | None:
    if not re.match(r"^[A-Za-z_][\w.-]*=", body):
        return None
    payload = parse_fields(body)
    if not payload:
        return None
    # Cloud exports wrap the original structured message in an escaped value.
    if isinstance(payload.get("message"), str):
        for key, value in parse_fields(payload["message"]).items():
            payload.setdefault(key, value)
    return payload


def parse_plain_level_log(body: str) -> dict | None:
    match = re.fullmatch(rf"(?P<level>{LEVELS})(?:\s+(?P<fields>.*))?", body)
    if not match:
        return None
    return {"level": match["level"], **(parse_key_value_log(match["fields"] or "") or {})}


def parse_syslog(line: str) -> dict | None:
    # Both dataset timestamp-first exports and standard RFC5424 header order.
    match = re.fullmatch(
        rf"(?:(?P<outer>{ISO_TOKEN})\s+)?<(?P<priority>\d+)>(?P<version>\d+)\s+"
        rf"(?:(?P<inner>{ISO_TOKEN})\s+)?(?P<host>\S+)\s+(?P<service>\S+)\s+"
        r"(?P<process_id>\S+)\s+(?P<message_id>\S+)\s+(?P<body>.*)",
        line,
    )
    if not match or not (match["outer"] or match["inner"]):
        return None
    payload = {
        k: v
        for k, v in match.groupdict().items()
        if k not in {"outer", "inner", "body"} and v != "-"
    }
    payload.update(parse_fields(match["body"]))
    payload.setdefault("timestamp", match["outer"] or match["inner"])
    payload["structured_data"] = re.findall(r"\[(?:[^\]\\]|\\.)*\]", match["body"])
    if match["outer"] and match["process_id"] != "-":
        payload.setdefault("trace_id", match["process_id"])
    return payload


def parse_log(line: str) -> dict | None:
    payload = parse_syslog(line)
    if payload is None:
        match = re.fullmatch(rf"(?P<timestamp>{ISO_TOKEN})\s+(?P<body>.*)", line)
        if not match:
            return None
        for parser in (
            parse_bracket_log,
            parse_pipe_log,
            parse_json_log,
            parse_plain_level_log,
            parse_key_value_log,
        ):
            payload = parser(match["body"])
            if payload is not None:
                payload.setdefault("timestamp", match["timestamp"])
                break
    if payload is not None:
        if "service" not in payload:
            service = payload.get("function") or payload.get("logger")
            if service:
                payload["service"] = service
        if "trace_id" not in payload and payload.get("requestId"):
            payload["trace_id"] = payload["requestId"]
    return payload


def parse_text(
    text: str, context: ExtractionContext, locator_prefix: str = "line"
) -> list[Observation]:
    observations = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        locator = f"{locator_prefix}:{number}"
        payload: dict = {"text": line}
        line_context = context
        structured = parse_log(line)
        if structured is not None:
            payload.update(structured)
            # Keep the envelope clock separately: payload fields cannot overwrite it.
            header = re.match(rf"^(?:<\d+>\d+\s+)?(?P<timestamp>{ISO_TOKEN})", line)
            if header:
                line_context = context.scoped(
                    {"timestamp": header["timestamp"]}, f"{locator}:header"
                )
        else:
            parts = [part.strip() for part in line.removeprefix("- ").split("|")]
            if len(parts) == 6 and re.fullmatch(ISO_TOKEN, parts[0]):
                payload.update(
                    dict(
                        zip(
                            (
                                "recorded_at",
                                "system",
                                "resource_id",
                                "record_type",
                                "result",
                                "subject_reference",
                            ),
                            parts,
                            strict=True,
                        )
                    )
                )
            else:
                timestamp = re.match(rf"(?:Snapshot:\s*|^)(?P<time>{ISO_TOKEN})", line)
                if timestamp:
                    payload["timestamp"] = timestamp["time"]
        observations.append(line_context.observation(payload, locator, raw_text=line))
        if line.startswith("Snapshot:") and "timestamp" in payload:
            context = context.scoped({"snapshot": payload["timestamp"]}, locator)
    return observations
