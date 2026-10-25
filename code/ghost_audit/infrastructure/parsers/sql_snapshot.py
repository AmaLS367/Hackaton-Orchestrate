"""Execute supplied SQL only in an isolated in-memory, authorizer-restricted DB."""

import json
import re
import sqlite3
from contextlib import closing
from dataclasses import replace

from ghost_audit.domain.catalog import ISO_TOKEN, TABLE_SYSTEMS
from ghost_audit.domain.models import Observation
from ghost_audit.infrastructure.parsers.structured import ExtractionContext, timestamps

# Schema adapters map named tables, never resource-ID prefixes or case families.


def _authorize(
    action: int, arg1: str | None, arg2: str | None, database: str | None, trigger: str | None
) -> int:
    allowed = {
        sqlite3.SQLITE_CREATE_TABLE,
        sqlite3.SQLITE_CREATE_INDEX,
        sqlite3.SQLITE_INSERT,
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_TRANSACTION,
        sqlite3.SQLITE_REINDEX,
    }
    if action in allowed:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_UPDATE and arg1 == "sqlite_master":
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and arg2 in {"json_valid", "like"}:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and arg1 == "foreign_keys":
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def parse_sql(text: str, context: ExtractionContext) -> list[Observation]:
    """Read supplied snapshots in a restricted in-memory SQLite connection."""
    observations = []
    # A header capture is independent of row updated_at and manifest capture time.
    header = re.search(rf"-- Captured at:\s*({ISO_TOKEN})", text)
    if header:
        context = context.scoped({"captured_at": header[1]}, "sql:header")
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.set_authorizer(_authorize)
        budget = 0

        def progress() -> int:
            nonlocal budget
            budget += 1
            return int(budget > 10_000)  # At most ten million virtual-machine instructions.

        connection.set_progress_handler(progress, 1000)
        connection.executescript(text)
        connection.row_factory = sqlite3.Row
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        scope_by_system = {}
        if "snapshot_scope" in tables:
            scope_rows = list(connection.execute("SELECT * FROM snapshot_scope"))
            scope_by_system = {
                row["origin_system"]: tuple(timestamps(dict(row), f"sql:snapshot_scope[{i}]"))
                for i, row in enumerate(scope_rows)
            }
        for table in tables:
            cursor = connection.execute(f"SELECT * FROM {_quote(table)}")
            columns = [column[0] for column in cursor.description]
            rows = sorted(
                (dict(row) for row in cursor),
                key=lambda row: json.dumps(row, sort_keys=True, ensure_ascii=False),
            )
            # Keep empty tables visible: emptiness is not automatically proof of absence.
            observations.append(
                context.observation(
                    {"table": table, "columns": columns, "row_count": len(rows)},
                    f"sql:{table}:schema",
                )
            )
            table_system = next(
                (
                    system
                    for name, system in TABLE_SYSTEMS.items()
                    if table == name or table.startswith(name + "_")
                ),
                None,
            )
            table_context = replace(
                context, collection=table, physical_table=table, system=table_system
            )
            for index, row in enumerate(rows):
                if "record_json" in row and row["record_json"] is not None:
                    row["decoded_record"] = json.loads(row["record_json"])
                decoded = row.get("decoded_record")
                system = (
                    row.get("origin_system")
                    or (decoded.get("origin_system") if isinstance(decoded, dict) else None)
                    or table_system
                )
                row_context = replace(
                    table_context,
                    times=(
                        *context.times,
                        *scope_by_system.get(system, ()),
                    ),
                )
                observations.append(
                    row_context.observation(
                        row,
                        f"sql:{table}:row:{index + 1}",
                        recursive_times=True,
                    )
                )
    return observations
