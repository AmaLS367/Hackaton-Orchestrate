import hashlib
import json
import sqlite3
from dataclasses import replace

import pytest
from ghost_audit.domain.evidence_index import EvidenceIndex
from ghost_audit.domain.models import IdentityChange
from ghost_audit.domain.time import parse_timestamp
from ghost_audit.infrastructure.parsers.documents import evidence_path, parse_document
from ghost_audit.infrastructure.parsers.sql_snapshot import parse_sql
from ghost_audit.infrastructure.parsers.structured import parse_csv, parse_json, parse_text
from ghost_audit.infrastructure.serialization.csv_records import load_models
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def test_nested_json_scopes_and_identifiers(context):
    payload = {
        "exported_at": "2026-01-02T10:00:00Z",
        "snapshots": [
            {
                "captured_at": "2026-01-02T11:00:00Z",
                "data_store": "account_service",
                "collection": "profiles",
                "records": [
                    {
                        "resource_id": "account_x",
                        "email": "FICTIONAL@EXAMPLE.INVALID",
                        "updated_at": "2026-01-03T00:00:00Z",
                    }
                ],
            },
            {
                "captured_at": "2026-01-02T09:00:00Z",
                "data_store": "search_service",
                "records": [{"resource_id": "search_x", "email": "second@example.invalid"}],
            },
        ],
    }
    observations = parse_json(payload, context)
    index = EvidenceIndex(observations)
    first = index.lookup(resource_id="account_x")[0]
    assert first.provenance.evidence_id == "fixture_file"
    assert first.provenance.locator == "$.snapshots[0].records[0]"
    assert first.provenance.sha256 == "a" * 64
    assert first.resources[0].system_id == "account_service"
    assert first.resources[0].collection == "profiles"
    assert {time.value for time in first.provenance.timestamps} == {
        parse_timestamp(value)
        for value in ("2026-01-02T10:00:00Z", "2026-01-02T11:00:00Z", "2026-01-03T00:00:00Z")
    }
    assert not index.lookup(resource_id="account_x", audit_at="2026-01-02T12:00:00Z")
    assert index.lookup(resource_id="search_x", audit_at="2026-01-02T12:00:00Z")
    assert first in index.lookup(identifiers=["fictional@example.invalid"])
    assert not index.lookup(identifiers=["fictional@example.invalid"], resource_id="search_x")


@pytest.mark.parametrize("field", ["expires_at", "retention_until", "retained_until"])
def test_business_deadline_does_not_hide_available_evidence(context, field):
    items = parse_json({"resource_id": "export_x", field: "2027-01-01T00:00:00Z"}, context)
    assert items[0].available_at == context.manifest.captured_at
    assert items[0].provenance.timestamps[0].role == "business"


def test_service_export_system_is_grounded_in_enclosing_key(context):
    observations = parse_json(
        {
            "service_exports": {
                "account_service": {
                    "lookups": [
                        {
                            "resource_id": "account_x",
                            "profile": {"email": "fixture@example.invalid"},
                        }
                    ]
                }
            }
        },
        context,
    )
    assert observations[0].resources[0].system_id == "account_service"
    assert observations[0].payload["profile"]["email"] == "fixture@example.invalid"


def test_no_system_inferred_from_resource_prefix_or_origin(context):
    item = parse_json({"resource_id": "account_x"}, context)[0]
    assert item.resources[0].system_id is None
    assert item.system_ids == []


def test_log_trace_links_keep_file_and_time_boundaries(context):
    lines = "\n".join(
        [
            '2026-01-02T10:00:00Z [INFO] [account_service] [trace-x] lookup_started: lookup_key="Person@Example.Invalid"',
            '2026-01-02T10:01:00Z [INFO] [account_service] [trace-x] lookup_finished: resource_id="account_x" rows="0"',
            '2026-01-04T10:01:00Z [INFO] [account_service] [trace-x] lookup_finished: resource_id="account_future" rows="1"',
        ]
    )
    parsed = parse_text(lines, context)
    other_file = replace(
        context, manifest=context.manifest.model_copy(update={"file_path": "evidence/other.log"})
    )
    unrelated = parse_text(lines.splitlines()[1], other_file)
    index = EvidenceIndex([*parsed, *unrelated])
    found = index.lookup(
        identifiers=["person@example.invalid"], audit_at="2026-01-03T00:00:00Z", expand_traces=True
    )
    assert len(found) == 2
    assert found[1].payload["rows"] == "0"
    assert found[1].provenance.locator == "line:2"
    assert found[1].raw_text == lines.splitlines()[1]
    assert not index.lookup(identifiers=["person@example.invalid"], audit_at="2026-01-01T00:00:00Z")


def test_phone_normalization_preserves_original_payload(context):
    original = "+1 (202) 555-0142"
    index = EvidenceIndex(parse_json({"resource_id": "record_x", "phone": original}, context))
    assert index.lookup(identifiers=["+12025550142"])[0].payload["phone"] == original


def test_text_handover_preserves_header_time_and_line_location(context):
    text = (
        "Snapshot: 2026-01-05T00:00:00Z\n\n"
        "- 2026-01-02T10:00:00Z | account_service | account_x | USER_PROFILE | NOT_FOUND | user_fixture"
    )
    items = parse_text(text, context)
    assert items[-1].provenance.locator == "line:3"
    assert items[-1].payload["result"] == "NOT_FOUND"
    assert items[-1].available_at == parse_timestamp("2026-01-05T00:00:00Z")


def test_sql_replicas_empty_tables_and_embedded_json(context):
    sql = """-- Captured at: 2026-01-02T09:00:00Z
CREATE TABLE customer_data_primary (resource_id TEXT PRIMARY KEY, origin_system TEXT, record_json TEXT CHECK(json_valid(record_json)), updated_at TEXT);
CREATE TABLE customer_data_replica (resource_id TEXT PRIMARY KEY, origin_system TEXT, record_json TEXT, updated_at TEXT);
INSERT INTO customer_data_replica VALUES ('record_x', 'account_service', '{"email":"fixture@example.invalid","observed_at":"2026-01-04T00:00:00Z"}', '2026-01-01T00:00:00Z');"""
    items = parse_sql(sql, context)
    assert any(
        item.payload.get("table") == "customer_data_primary" and item.payload["row_count"] == 0
        for item in items
    )
    record = next(item for item in items if item.resources)
    assert record.resources[0].collection == "customer_data_replica"
    assert record.resources[0].system_id == "account_service"
    assert record.payload["decoded_record"]["email"] == "fixture@example.invalid"
    assert record.available_at == parse_timestamp("2026-01-04T00:00:00Z")
    assert record in EvidenceIndex(items).lookup(identifiers=["fixture@example.invalid"])


def test_sql_snapshot_scope_does_not_mix_other_systems(context):
    sql = """CREATE TABLE snapshot_scope (origin_system TEXT, captured_at TEXT);
INSERT INTO snapshot_scope VALUES ('account_service','2026-01-02T08:00:00Z');
INSERT INTO snapshot_scope VALUES ('search_service','2026-02-01T08:00:00Z');
CREATE TABLE customer_profiles (resource_id TEXT PRIMARY KEY, email TEXT);
INSERT INTO customer_profiles VALUES ('account_x','fixture@example.invalid');"""
    record = next(item for item in parse_sql(sql, context) if item.resources)
    assert record.available_at == context.manifest.captured_at


@pytest.mark.parametrize("logical_location", ["column", "decoded"])
def test_sql_preserves_logical_collection_and_physical_replica(context, logical_location):
    collection_column = ", collection_name TEXT" if logical_location == "column" else ""
    collection_value = ", 'customer_profiles'" if logical_location == "column" else ""
    decoded = {
        "resource_id": "record_x",
        "collection_name": "customer_profiles",
        "email": "fictional@example.invalid",
    }
    sql = f"""-- Captured at: 2026-01-02T09:00:00Z
CREATE TABLE snapshot_scope (origin_system TEXT, captured_at TEXT);
INSERT INTO snapshot_scope VALUES ('account_service','2026-01-02T08:00:00Z');
CREATE TABLE customer_data_replica (resource_id TEXT, origin_system TEXT,
                                  record_json TEXT{collection_column});
INSERT INTO customer_data_replica VALUES
('record_x','account_service','{json.dumps(decoded)}'{collection_value});"""
    record = next(item for item in parse_sql(sql, context) if item.resources)
    assert record.resources[0].collection == "customer_profiles"
    assert record.resources[0].physical_table == "customer_data_replica"
    assert record.resources[0].system_id == "account_service"
    assert record.payload["decoded_record"] == decoded
    assert record.provenance.locator == "sql:customer_data_replica:row:1"
    assert {stamp.locator for stamp in record.provenance.timestamps} >= {
        "sql:header.captured_at",
        "sql:snapshot_scope[0].captured_at",
    }


def test_sql_decoded_resource_keeps_origin_snapshot_scope(context):
    sql = """CREATE TABLE snapshot_scope (origin_system TEXT, captured_at TEXT);
INSERT INTO snapshot_scope VALUES ('account_service','2026-01-05T00:00:00Z');
CREATE TABLE generic_replica (record_json TEXT);
INSERT INTO generic_replica VALUES
('{"resource_id":"record_x","origin_system":"account_service","collection_name":"profiles"}');"""
    item = next(item for item in parse_sql(sql, context) if item.resources)
    assert item.resources[0].system_id == "account_service"
    assert item.resources[0].collection == "profiles"
    assert item.resources[0].physical_table == "generic_replica"
    assert item.available_at == parse_timestamp("2026-01-05T00:00:00Z")


@pytest.mark.parametrize(
    "statement",
    [
        "ATTACH DATABASE 'outside.db' AS outside;",
        "SELECT load_extension('anything');",
        "PRAGMA writable_schema=ON;",
        "CREATE VIRTUAL TABLE external USING fts5(content);",
    ],
)
def test_sql_rejects_unsafe_commands(statement, context):
    with pytest.raises(sqlite3.Error):
        parse_sql(statement, context)


def test_csv_utf8_quoted_fields_and_provenance_fields(tmp_path):
    path = tmp_path / "changes.csv"
    path.write_text(
        "audit_id,user_id,event_time,field_name,old_value,new_value\n"
        'audit_x,user_x,2026-01-01T00:00:00Z,name,"Fictional, Old","Fictional, 新"\n',
        encoding="utf-8-sig",
    )
    rows = load_models(path, IdentityChange, "audit_id")
    assert rows[0].old_value == "Fictional, Old"
    assert rows[0].new_value == "Fictional, 新"


def test_csv_evidence_preserves_timestamps_and_resource_scope(context):
    text = (
        "resource_id,system,observed_at,email\n"
        "record_x,account_service,2026-01-02T10:00:00+02:00,fixture@example.invalid\n"
    )
    item = parse_csv(text, context)[0]
    assert item.provenance.locator == "row:2"
    assert item.resources[0].system_id == "account_service"
    assert item.provenance.timestamps[0].value == parse_timestamp("2026-01-02T08:00:00Z")


@pytest.mark.parametrize("text", ["", "id,id\nx,y\n", "a,b\nx\n"])
def test_csv_evidence_rejects_invalid_headers_and_rows(context, text):
    with pytest.raises(ValueError):
        parse_csv(text, context)


@pytest.mark.parametrize(
    "content",
    [
        "audit_id,user_id\naudit_x,user_x\n",
        "audit_id,user_id,event_time,field_name,old_value,new_value\naudit_x,user_x\n",
        "audit_id,user_id,event_time,field_name,old_value,new_value\naudit_x,user_x,bad,email,x,y,extra\n",
    ],
)
def test_csv_rejects_wrong_schema_or_width(tmp_path, content):
    path = tmp_path / "invalid.csv"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        load_models(path, IdentityChange, "audit_id")


def test_csv_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "duplicates.csv"
    row = "audit_x,user_x,2026-01-01T00:00:00Z,email,x,y\n"
    path.write_text(
        "audit_id,user_id,event_time,field_name,old_value,new_value\n" + row * 2, encoding="utf-8"
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_models(path, IdentityChange, "audit_id")


@pytest.mark.parametrize(
    "relative", ["../private.json", "evidence/../../private.json", "user_identities.csv"]
)
def test_manifest_path_cannot_escape_evidence(tmp_path, relative):
    with pytest.raises(ValueError):
        evidence_path(tmp_path, relative)


def test_document_digest_and_json_source_location(tmp_path, context):
    path = tmp_path / context.manifest.file_path
    path.parent.mkdir(parents=True)
    content = b'{"resource_id":"fixture_x","email":"fixture@example.invalid"}'
    path.write_bytes(content)
    document = parse_document(tmp_path, context.manifest)
    assert document.sha256 == hashlib.sha256(content).hexdigest()
    assert document.observations[0].provenance.file_path == context.manifest.file_path
    assert document.observations[0].provenance.locator == "$"


def test_images_are_explicitly_deferred(tmp_path, context):
    manifest = context.manifest.model_copy(update={"file_path": "evidence/images/fixture.png"})
    path = tmp_path / manifest.file_path
    path.parent.mkdir(parents=True)
    path.write_bytes(b"fixture-image-placeholder")
    document = parse_document(tmp_path, manifest)
    assert document.status == "deferred"
    assert document.observations == []
    assert document.notes


def test_pdf_text_extraction_and_page_provenance(tmp_path, context):
    manifest = context.manifest.model_copy(update={"file_path": "evidence/documents/fixture.pdf"})
    path = tmp_path / manifest.file_path
    path.parent.mkdir(parents=True)
    writer = PdfWriter()
    page = writer.add_blank_page(width=500, height=500)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 450 Td (Fixture resource_x email@example.invalid) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)
    document = parse_document(tmp_path, manifest)
    assert document.status == "parsed"
    assert document.observations[0].provenance.locator.startswith("page:1:line:")
    assert EvidenceIndex(document.observations).lookup(identifiers=["email@example.invalid"])


def test_scanned_pdf_is_deferred(tmp_path, context):
    manifest = context.manifest.model_copy(update={"file_path": "evidence/documents/empty.pdf"})
    path = tmp_path / manifest.file_path
    path.parent.mkdir(parents=True)
    writer = PdfWriter()
    writer.add_blank_page(width=500, height=500)
    writer.write(path)
    assert parse_document(tmp_path, manifest).status == "deferred"
