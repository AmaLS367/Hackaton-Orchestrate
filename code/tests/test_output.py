import csv
import json

import pytest
from pydantic import ValidationError

from ghost_audit.infrastructure.parsers.structured import parse_json, parse_text
from ghost_audit.domain.evidence_index import EvidenceIndex
from ghost_audit.domain.models import DeletionRequest
from ghost_audit.domain.output_contract import OPERATIONS, OutputRow, OutputStep, canonical_steps
from ghost_audit.infrastructure.serialization.csv_output import read_output, write_output
from ghost_audit.domain.citation_validation import validate_output


def step(operation="VERIFY_RECORD_ABSENT", **overrides):
    phase, state = OPERATIONS.get(operation, ("VERIFICATION", "ABSENT"))
    return OutputStep.model_validate({"step_no": 1, "phase": phase, "system_id": "account_service",
                                      "resource_id": "record_x", "operation": operation, "state": state,
                                      "evidence_id": "fixture_file", **overrides})


def request(**overrides):
    return DeletionRequest.model_validate({
        "case_id": "fixture_case", "email": "fictional@example.invalid",
        "requested_at": "2026-01-01T00:00:00Z", "reported_status": "COMPLETE",
        "reported_at": "2026-01-01T01:00:00Z", "audit_at": "2026-01-03T00:00:00Z",
        "request_text": "Delete my personal data.", **overrides,
    })


@pytest.mark.parametrize("operation", list(OPERATIONS))
def test_all_allowed_operation_contracts(operation):
    assert step(operation).operation == operation


@pytest.mark.parametrize("changes", [
    {"step_no": True}, {"step_no": "1"}, {"step_no": 0}, {"state": "ACTIVE"},
    {"phase": "FINDING"}, {"operation": "INVENTED"}, {"unexpected": "x"},
    {"resource_id": " "}, {"system_id": ""}, {"evidence_id": "  "},
])
def test_invalid_output_step_schema(changes):
    with pytest.raises(ValidationError):
        step(**changes)


def test_canonical_order_follows_official_operations_then_system_resource():
    unsorted = [step("VERIFY_RESTORE_BLOCKED"), step("DELETE_RECORD", evidence_id=""),
                step("BLOCK_RESTORE", evidence_id=""), step("DISABLE_DATA_FLOW", evidence_id=""),
                step("REPORT_RESTORE_RISK"), step("REPORT_REMAINING_RECORD", system_id="z"),
                step("REPORT_REMAINING_RECORD", system_id="a", resource_id="z"),
                step("REPORT_REMAINING_RECORD", system_id="a", resource_id="a")]
    ordered = canonical_steps(unsorted)
    assert [s.step_no for s in ordered] == list(range(1, 9))
    assert [(s.system_id, s.resource_id) for s in ordered[:3]] == [("a", "a"), ("a", "z"), ("z", "record_x")]
    assert [s.operation for s in ordered[3:]] == ["REPORT_RESTORE_RISK", "DISABLE_DATA_FLOW",
                                                "BLOCK_RESTORE", "DELETE_RECORD", "VERIFY_RESTORE_BLOCKED"]
    assert unsorted[0].step_no == 1


@pytest.mark.parametrize("status,steps", [
    ("NOT_APPLICABLE", [step()]), ("COMPLETE", []), ("INCOMPLETE", []),
    ("COMPLETE", [step(evidence_id="")]), ("COMPLETE", [step("REPORT_REMAINING_RECORD")]),
    ("COMPLETE", [step(step_no=2)]), ("INCOMPLETE", [step("REPORT_REMAINING_RECORD")]),
    ("COMPLETE", canonical_steps([step(), step()])),
])
def test_invalid_row_status_and_steps(status, steps):
    with pytest.raises(ValidationError):
        OutputRow(case_id="fixture_case", deletion_status=status, steps=steps)


def test_incomplete_citation_rules_and_valid_three_phase_row():
    steps = canonical_steps([step("REPORT_REMAINING_RECORD"),
                             step("DELETE_RECORD", evidence_id=""), step(evidence_id="")])
    row = OutputRow(case_id="fixture_case", deletion_status="INCOMPLETE", steps=steps)
    assert row.steps[-1].evidence_id == ""
    invalid = [s.model_dump() for s in steps]
    invalid[-1]['evidence_id'] = "fixture_file"
    with pytest.raises(ValidationError):
        OutputRow(case_id="fixture_case", deletion_status="INCOMPLETE", steps=invalid)


def test_unsorted_steps_are_rejected_without_silent_repair():
    steps = [step("VERIFY_RESTORE_BLOCKED"), step("VERIFY_RECORD_ABSENT", step_no=2)]
    with pytest.raises(ValidationError, match="canonical"):
        OutputRow(case_id="fixture_case", deletion_status="COMPLETE", steps=steps)


def test_output_roundtrip_is_byte_deterministic_and_exact_schema(tmp_path):
    row = OutputRow(case_id="fixture_case", deletion_status="COMPLETE", steps=[step()])
    path = tmp_path / "output.csv"
    write_output(path, [row], [request()])
    before = path.read_bytes()
    assert read_output(path) == [row]
    write_output(path, [row], [request()])
    assert path.read_bytes() == before
    assert before.startswith(b'case_id,deletion_status,steps_json\n')
    with path.open(newline='', encoding='utf-8') as stream:
        serialized = json.loads(next(csv.DictReader(stream))['steps_json'])
    assert set(serialized[0]) == set(OutputStep.model_fields)


def test_failed_validation_does_not_replace_existing_output(tmp_path):
    path = tmp_path / "output.csv"
    path.write_text("existing", encoding="utf-8")
    with pytest.raises(ValueError):
        write_output(path, [], [request()])
    assert path.read_text() == "existing"


def test_duplicate_and_missing_cases_are_rejected():
    row = OutputRow(case_id="fixture_case", deletion_status="NOT_APPLICABLE", steps=[])
    for rows in ([], [row, row]):
        with pytest.raises(ValueError):
            validate_output(rows, [request()])


def test_unknown_and_future_citations(context):
    index = EvidenceIndex(parse_json({"resource_id": "record_x", "observed_at": "2026-01-05T00:00:00Z"}, context))
    row = OutputRow(case_id="fixture_case", deletion_status="COMPLETE", steps=[step()])
    with pytest.raises(ValueError, match="future"):
        validate_output([row], [request()], index)
    other = row.model_copy(update={"steps": [step(evidence_id="missing_file")]})
    with pytest.raises(ValueError, match="unknown"):
        validate_output([other], [request()], index)


def test_future_nested_resource_cannot_use_earlier_envelope_as_citation(context):
    items = parse_json({"captured_at": "2026-01-02T00:00:00Z", "records": [
        {"resource_id": "record_x", "observed_at": "2026-01-05T00:00:00Z"}]}, context)
    row = OutputRow(case_id="fixture_case", deletion_status="COMPLETE", steps=[step()])
    with pytest.raises(ValueError, match="resource observation"):
        validate_output([row], [request()], EvidenceIndex(items))


@pytest.mark.parametrize('payload', [
    {'resource_id': 'unrelated'},
    {'captured_at': '2026-01-02T00:00:00Z', 'records': [{'resource_id': 'unrelated'}]},
    {'resource_id': 'record_x', 'system': 'other_service'},
])
def test_citation_exclusively_about_another_resource_is_rejected(context, payload):
    row = OutputRow(case_id='fixture_case', deletion_status='COMPLETE', steps=[step()])
    with pytest.raises(ValueError, match='unrelated'):
        validate_output([row], [request()], EvidenceIndex(parse_json(payload, context)))


@pytest.mark.parametrize('fields', ['rows=0', 'result=NOT_FOUND', 'http_status=404'])
def test_negative_lookup_needs_no_physical_record(context, fields):
    items = parse_text('2026-01-02T10:00:00Z INFO service=account_service '
                       f'event=lookup_completed resource_id=record_x {fields}', context)
    row = OutputRow(case_id='fixture_case', deletion_status='COMPLETE', steps=[step()])
    checks = validate_output([row], [request()], EvidenceIndex(items))
    assert checks[0].resource_support == 'linked'
    assert checks[0].state_support == 'unverified'


def test_trace_citation_and_future_resource_link(context):
    # Separate citation IDs in the same grounded file/service trace.
    started = parse_text('2026-01-02T10:00:00Z INFO service=account_service '
                         'trace_id=trace-x email=person@example.invalid', context)[0]
    finished = parse_text('2026-01-04T10:00:00Z INFO service=account_service '
                          'trace_id=trace-x resource_id=record_x rows=0', context)[0]
    finished = finished.model_copy(update={'provenance': finished.provenance.model_copy(
        update={'evidence_id': 'other_citation'})})
    row = OutputRow(case_id='fixture_case', deletion_status='COMPLETE', steps=[step()])
    with pytest.raises(ValueError, match='resource observation.*after audit_at'):
        validate_output([row], [request()], EvidenceIndex([started, finished]))
    checks = validate_output([row], [request(audit_at='2026-01-05T00:00:00Z')],
                             EvidenceIndex([started, finished]))
    assert checks[0].resource_support == 'linked'


def test_generic_text_does_not_silently_claim_semantic_support(context):
    index = EvidenceIndex(parse_text('An uninterpreted business artifact.', context))
    row = OutputRow(case_id='fixture_case', deletion_status='COMPLETE', steps=[step()])
    checks = validate_output([row], [request()], index)
    assert checks[0].resource_support == 'unknown'
    assert checks[0].state_support == 'unverified'


def test_schema_validation_cannot_be_bypassed_with_mutated_step_list():
    row = OutputRow(case_id="fixture_case", deletion_status="COMPLETE", steps=[step()])
    row.steps.append(step(step_no=3, resource_id="other"))
    with pytest.raises(ValueError):
        validate_output([row], [request()])


@pytest.mark.parametrize("payload", ['{}', 'null', '[{"step_no": "1"}]', 'not-json'])
def test_read_output_rejects_non_array_or_malformed_steps(tmp_path, payload):
    path = tmp_path / "output.csv"
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['case_id', 'deletion_status', 'steps_json'])
        writer.writerow(['fixture_case', 'COMPLETE', payload])
    with pytest.raises(ValueError):
        read_output(path)
