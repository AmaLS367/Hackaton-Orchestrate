"""Synthetic equivalents of the participant service, syslog and runtime exports."""

from dataclasses import replace

import pytest

from ghost_audit.extraction import parse_text
from ghost_audit.index import EvidenceIndex
from ghost_audit.time import parse_timestamp


FORMATS = [
    '[INFO] [account_service] [trace-x] {event}: {fields}',
    'level=INFO service=account_service trace_id=trace-x event={event} {fields}',
    'INFO service=account_service trace_id=trace-x event={event} {fields}',
    '<14>1 node-1 account_service trace-x - - level=INFO event={event} {fields}',
    '| INFO | account_service | trace-x | {event} | {fields}',
]


@pytest.mark.parametrize("template", FORMATS)
def test_log_formats_correlate_lookup_without_coercing_values(context, template):
    lines = [
        '2026-01-02T10:00:00Z ' + template.format(
            event='lookup_started', fields='email="Person@Example.Invalid"'),
        '2026-01-02T10:01:00Z ' + template.format(
            event='lookup_completed', fields='resource_id="record_x" rows=0 enabled=false key=null'),
    ]
    items = parse_text('\n'.join(lines), context)
    found = EvidenceIndex(items).lookup(identifiers=['person@example.invalid'], expand_traces=True)
    assert len(found) == 2
    assert found[0].trace_id == 'trace-x'
    assert found[1].resources[0].system_id == 'account_service'
    assert found[1].resources[0].resource_id == 'record_x'
    assert found[1].payload['event'] == 'lookup_completed'
    assert {key: found[1].payload[key] for key in ('rows', 'enabled', 'key')} == {
        'rows': '0', 'enabled': 'false', 'key': 'null',
    }
    assert found[1].raw_text == lines[1]
    assert found[1].provenance.locator == 'line:2'
    assert found[1].provenance.timestamps[0].value == parse_timestamp('2026-01-02T10:01:00Z')


def test_timestamp_json_preserves_native_types_and_trace(context):
    text = ('2026-01-02T10:00:00Z {"service":"account_service","trace_id":"trace-x",'
            '"event":"lookup_started","email":"person@example.invalid"}\n'
            '2026-01-02T10:01:00Z {"service":"account_service","trace_id":"trace-x",'
            '"event":"lookup_completed","resource_id":"record_x","rows":0,'
            '"enabled":false,"extra":{"key":null}}')
    found = EvidenceIndex(parse_text(text, context)).lookup(
        identifiers=['person@example.invalid'], expand_traces=True)
    assert len(found) == 2
    assert found[1].resources[0].system_id == 'account_service'
    assert found[1].payload['rows'] == 0
    assert found[1].payload['enabled'] is False
    assert found[1].payload['extra'] == {'key': None}


def test_cloud_runtime_nested_fields_and_request_trace(context):
    text = (r'2026-01-02T10:00:00Z requestId=trace-x level=DEBUG function=account_service '
            r'message="event=\"lookup_started\" email=\"person@example.invalid\""' '\n'
            r'2026-01-02T10:01:00Z requestId=trace-x level=INFO function=account_service '
            r'message="event=\"lookup_completed\" resource_id=\"record_x\" rows=\"0\""')
    found = EvidenceIndex(parse_text(text, context)).lookup(
        identifiers=['person@example.invalid'], expand_traces=True)
    assert len(found) == 2
    assert found[1].resources[0].system_id == 'account_service'
    assert found[1].payload['rows'] == '0'
    assert found[1].payload['message'].startswith('event="lookup_completed"')


def test_quoted_escaped_unknown_values_and_optional_fields(context):
    text = (r'2026-01-02T10:00:00Z level=INFO service=account_service resource_id=record_x '
            r'note="say \"hello\"; path C:\\logs" label=\'two words\' empty="" code=001')
    # A single-quoted value is supported as well as the dataset's double quotes.
    text = text.replace(r"\'", "'")
    item = parse_text(text, context)[0]
    assert item.trace_id is None
    assert item.payload['note'] == 'say "hello"; path C:\\logs'
    assert item.payload['label'] == 'two words'
    assert item.payload['empty'] == ''
    assert item.payload['code'] == '001'
    assert item.raw_text == text


def test_standard_syslog_and_nil_optional_headers(context):
    text = ('<14>1 2026-01-02T10:00:00Z host account_service - - '
            '[meta trace_id="trace-x"] event=lookup_completed resource_id=record_x rows=0')
    item = parse_text(text, context)[0]
    assert item.trace_id == 'trace-x'
    assert item.resources[0].system_id == 'account_service'
    assert item.payload['host'] == 'host'
    assert item.provenance.timestamps[0].value == parse_timestamp('2026-01-02T10:00:00Z')


def test_trace_scope_uses_service_not_record_system(context):
    text = ('2026-01-02T10:00:00Z INFO service=collector trace_id=trace-x email=person@example.invalid\n'
            '2026-01-02T10:01:00Z INFO service=collector trace_id=trace-x system=account_service resource_id=record_x\n'
            '2026-01-02T10:01:00Z INFO service=other trace_id=trace-x resource_id=unrelated\n'
            '2026-01-05T10:01:00Z INFO service=collector trace_id=trace-x resource_id=future')
    items = parse_text(text, context)
    other_file = replace(context, manifest=context.manifest.model_copy(
        update={'file_path': 'evidence/other.log'}))
    index = EvidenceIndex([*items, *parse_text(text.splitlines()[1], other_file)])
    found = index.lookup(identifiers=['person@example.invalid'], expand_traces=True,
                         audit_at='2026-01-03T00:00:00Z')
    assert [item.provenance.locator for item in found] == ['line:1', 'line:2']
    assert found[1].resources[0].system_id == 'account_service'


def test_json_fields_cannot_hide_later_log_header_time(context):
    text = ('2026-01-05T10:00:00Z {"timestamp":"2026-01-01T00:00:00Z",'
            '"recorded_at":"2026-01-01T00:00:00Z","service":"account_service",'
            '"resource_id":"record_x"}')
    item = parse_text(text, context)[0]
    assert item.payload['timestamp'] == '2026-01-01T00:00:00Z'
    assert item.payload['recorded_at'] == '2026-01-01T00:00:00Z'
    assert item.available_at == parse_timestamp('2026-01-05T10:00:00Z')
    assert not EvidenceIndex([item]).lookup(resource_id='record_x', audit_at='2026-01-03T00:00:00Z')


def test_bracket_log_without_optional_trace_keeps_resource(context):
    item = parse_text('2026-01-02T10:00:00Z [INFO] [account_service] '
                      'lookup_completed: resource_id=record_x rows=0', context)[0]
    assert item.trace_id is None
    assert item.resources[0].resource_id == 'record_x'
    assert item.resources[0].system_id == 'account_service'
