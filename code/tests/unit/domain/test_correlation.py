from collections.abc import Sequence
from dataclasses import replace
from itertools import permutations

import pytest
from ghost_audit.domain.association_models import AssociatedObservation, AssociatedResource
from ghost_audit.domain.correlation import EvidenceCorrelator
from ghost_audit.domain.evidence_index import EvidenceIndex, EvidenceRegistry
from ghost_audit.domain.identity import IdentityResolver
from ghost_audit.domain.models import (
    EvidenceDocument,
    EvidenceFile,
    Identity,
    IdentityChange,
    Observation,
    ResourceRef,
)
from ghost_audit.domain.time import parse_timestamp
from ghost_audit.infrastructure.parsers.sql_snapshot import parse_sql
from ghost_audit.infrastructure.parsers.structured import ExtractionContext, parse_json, parse_text
from pydantic import JsonValue

from tests.fixtures.identity_cases import T1, T2, T3, T4, change, snapshot


def correlate(
    items: Sequence[Observation],
    *,
    identities: list[Identity] | None = None,
    changes: Sequence[IdentityChange] = (),
    cutoff: str = T4,
) -> tuple[list[AssociatedObservation], list[AssociatedResource], list[str]]:
    resolver = IdentityResolver(
        identities if identities is not None else [snapshot(at=T1)], changes
    )
    identity = resolver.resolve("new@example.invalid", cutoff)
    result = EvidenceCorrelator(EvidenceIndex(items), resolver).correlate(
        identity, parse_timestamp(cutoff)
    )
    return result


def confirmed(items: list[AssociatedObservation]) -> list[AssociatedObservation]:
    return [x for x in items if x.association == "CONFIRMED"]


def test_direct_id_and_historical_email_and_phone_hash(context: ExtractionContext) -> None:
    items = parse_json(
        [
            {"resource_id": "record_a", "user_id": "user_one"},
            {"resource_id": "record_b", "email": "OLD@example.invalid"},
            {"resource_id": "record_c", "phone": "+44 (20) 1234-5678"},
            {"resource_id": "record_d", "email_hash": "OLD_HASH"},
        ],
        context,
    )
    changes = [
        change("a", "old@example.invalid", "new@example.invalid", at=T1),
        change("b", "+442012345678", "+1 (202) 555-0100", "phone", at=T1),
        change("c", "old_hash", "HASH_SUPPLIED", "email_hash", at=T1),
    ]
    result, resources, issues = correlate(items, changes=changes)
    assert len(confirmed(result)) == 4
    assert len(resources) == 4
    assert issues == ["resource_system_unknown"]
    link = next(x.links[0] for x in result if x.observation.payload.get("email"))
    assert link.method == "DIRECT_IDENTIFIER"
    assert link.alias_origins[0].audit_id == "a"
    assert link.supporting_observations[0].locator == "$[1]"


def test_trace_start_and_result_keep_both_locators(context: ExtractionContext) -> None:
    items = parse_text(
        "2026-01-02T10:00:00Z service=store trace_id=abc event=start email=new@example.invalid\n"
        "2026-01-02T10:01:00Z service=store trace_id=abc event=result resource_id=record_a rows=0",
        context,
    )
    result, resources, _ = correlate(items)
    assert len(confirmed(result)) == 2
    trace_link = next(link for link in result[1].links if link.method == "SCOPED_TRACE")
    assert [ref.locator for ref in trace_link.supporting_observations] == ["line:1", "line:2"]
    assert resources[0].reference.system_id == "store"
    # rows=0 is a claim and never turned into an absence/deletion verdict.
    assert result[1].observation.payload["rows"] == "0"


def test_trace_is_scoped_to_file_and_service(context: ExtractionContext) -> None:
    first = parse_text(
        "2026-01-02T10:00:00Z service=store trace_id=same email=new@example.invalid", context
    )
    wrong_service = parse_text(
        "2026-01-02T10:00:00Z service=other trace_id=same resource_id=other_a", context
    )
    other_context = replace(
        context,
        manifest=context.manifest.model_copy(
            update={"file_id": "other_file", "file_path": "evidence/logs/other.log"}
        ),
    )
    wrong_file = parse_text(
        "2026-01-02T10:00:00Z service=store trace_id=same resource_id=other_b", other_context
    )
    result, resources, _ = correlate([*first, *wrong_service, *wrong_file])
    assert len(result) == 1
    assert resources == []


def test_trace_reuse_across_users_is_potential(context: ExtractionContext) -> None:
    items = parse_text(
        "2026-01-02T10:00:00Z service=store trace_id=same email=new@example.invalid\n"
        "2026-01-02T10:00:00Z service=store trace_id=same email=other@example.invalid\n"
        "2026-01-02T10:01:00Z service=store trace_id=same resource_id=unproven",
        context,
    )
    identities = [
        snapshot(at=T1),
        snapshot(
            "user_two", "other@example.invalid", T1, phone="+22222222222", email_hash="other_hash"
        ),
    ]
    result, resources, issues = correlate(items, identities=identities)
    assert len(confirmed(result)) == 1
    assert result[-1].association == "POTENTIAL"
    assert "ambiguous_trace_scope" in issues
    assert not resources


def test_json_rows_are_separate_no_file_wide_matching(context: ExtractionContext) -> None:
    items = parse_json(
        {
            "system": "store",
            "records": [
                {"resource_id": "mine", "email": "new@example.invalid"},
                {"resource_id": "other", "email": "other@example.invalid"},
                {"resource_id": "similar", "email": "newish@example.invalid"},
                {"resource_id": "prefix", "user_id": "user_one_more"},
            ],
        },
        context,
    )
    result, resources, _ = correlate(items)
    assert [r.reference.resource_id for r in resources] == ["mine"]
    assert len(result) == 1


def test_email_substring_is_not_a_match(context: ExtractionContext) -> None:
    items = parse_text(
        "Contact anew@example.invalid or new@example.invalid.other for help.", context
    )
    assert correlate(items)[0] == []


def test_mixed_subject_record_is_potential_and_never_seeds_resources(
    context: ExtractionContext,
) -> None:
    items = parse_json(
        [
            {
                "resource_id": "shared",
                "people": [{"email": "new@example.invalid"}, {"user_id": "unknown_user"}],
            },
            {"resource_id": "shared", "note": "no identity"},
        ],
        replace(context, system="store"),
    )
    result, resources, issues = correlate(items)
    assert len(result) == 1
    assert result[0].association == "POTENTIAL"
    assert not resources
    assert issues == ["unsupported_subject_reference"]


def test_unknown_second_email_prevents_document_cooccurrence_proof(
    context: ExtractionContext,
) -> None:
    items = parse_json(
        {
            "resource_id": "mixed",
            "email": "new@example.invalid",
            "other_person": {"email": "unknown@example.invalid"},
        },
        context,
    )
    result, resources, _ = correlate(items)
    assert result[0].association == "POTENTIAL"
    assert not resources


def test_shared_phone_cannot_merge_users(context: ExtractionContext) -> None:
    items = parse_json({"resource_id": "ambiguous", "phone": "+12025550100"}, context)
    result, resources, _ = correlate(
        items, identities=[snapshot(at=T1), snapshot("user_two", "other@example.invalid", T1)]
    )
    assert result[0].association == "POTENTIAL"
    assert not resources


def test_name_only_and_system_only_are_unrelated(context: ExtractionContext) -> None:
    items = parse_json(
        {
            "system": "store",
            "records": [
                {"resource_id": "a", "name": "Fictional Person"},
                {"resource_id": "b", "result": "gone"},
            ],
        },
        context,
    )
    assert correlate(items)[0] == []


def test_future_manifest_and_nested_record_and_unknown_time_excluded(
    context: ExtractionContext,
) -> None:
    future = replace(
        context, manifest=context.manifest.model_copy(update={"captured_at": parse_timestamp(T4)})
    )
    items = parse_json({"resource_id": "a", "user_id": "user_one"}, future)
    items += parse_json({"resource_id": "b", "user_id": "user_one", "updated_at": T4}, context)
    item = parse_json({"resource_id": "c", "user_id": "user_one"}, context)[0]
    items.append(
        item.model_copy(
            update={"provenance": item.provenance.model_copy(update={"captured_at": None})}
        )
    )
    assert correlate(items, cutoff=T3)[0] == []


def test_future_trace_anchor_cannot_link_earlier_result(context: ExtractionContext) -> None:
    items = parse_text(
        "2026-01-04T00:00:00Z service=store trace_id=same email=new@example.invalid\n"
        "2026-01-02T00:00:00Z service=store trace_id=same resource_id=record_a",
        context,
    )
    assert correlate(items, cutoff=T3)[0] == []


def test_resource_versions_replicas_and_metadata_preserved(context: ExtractionContext) -> None:
    scoped = replace(
        context, system="store", collection="profiles", physical_table="primary_replica"
    )
    first = parse_json({"resource_id": "record_a", "email": "new@example.invalid"}, scoped)
    second = parse_json(
        {"resource_id": "record_a", "email": None},
        replace(scoped, physical_table="failover_replica"),
        "$.replica",
    )
    result, resources, _ = correlate([*first, *second])
    assert len(confirmed(result)) == 2
    assert (
        len(
            {
                (r.observation.provenance.evidence_id, r.observation.provenance.locator)
                for r in result
            }
        )
        == 2
    )
    assert {r.reference.physical_table for r in resources} == {
        "primary_replica",
        "failover_replica",
    }
    assert all(r.reference.collection == "profiles" for r in resources)
    assert all(r.observation.provenance.sha256 == context.sha256 for r in result)
    assert any(link.method == "RESOURCE" for link in result[1].links)


def test_resource_id_collision_across_systems_is_excluded(context: ExtractionContext) -> None:
    first = parse_json(
        {"resource_id": "same", "user_id": "user_one"}, replace(context, system="store")
    )
    other = parse_json(
        {"resource_id": "same", "result": "exists"}, replace(context, system="other"), "$.other"
    )
    assert len(correlate([*first, *other])[0]) == 1


def test_unknown_resource_system_is_only_potential(context: ExtractionContext) -> None:
    first = parse_json(
        {"resource_id": "same", "user_id": "user_one"}, replace(context, system="store")
    )
    other = parse_json({"resource_id": "same", "result": "exists"}, context, "$.unknown")
    result, _, _ = correlate([*first, *other])
    assert result[-1].association == "POTENTIAL"


def test_resource_with_foreign_subject_does_not_merge(context: ExtractionContext) -> None:
    items = parse_json(
        [
            {"resource_id": "same", "email": "new@example.invalid"},
            {"resource_id": "same", "user_id": "user_foreign"},
        ],
        replace(context, system="store"),
    )
    result, _, _ = correlate(items)
    assert len(confirmed(result)) == 1
    assert result[-1].association == "POTENTIAL"


def test_explicit_references_are_one_hop_and_resource_expansion_is_terminal(
    context: ExtractionContext,
) -> None:
    items = parse_json(
        [
            {"resource_id": "a", "user_id": "user_one", "target_resource_id": "b"},
            {"resource_id": "b", "target_resource_id": "c"},
            {"resource_id": "c", "target_resource_id": "d"},
            {"resource_id": "d"},
        ],
        replace(context, system="store"),
    )
    result, resources, _ = correlate(items)
    assert {r.reference.resource_id for r in resources} == {"a", "b"}
    assert any(link.method == "EXPLICIT_RESOURCE_REFERENCE" for link in result[1].links)
    assert len(result) == 2


def test_sql_decoded_records_and_replica_provenance(context: ExtractionContext) -> None:
    sql = """CREATE TABLE replica(resource_id TEXT, origin_system TEXT, collection_name TEXT, record_json TEXT);
    INSERT INTO replica VALUES ('record_a','store','profiles','{"email":"new@example.invalid"}');"""
    result, resources, _ = correlate(parse_sql(sql, context))
    assert len(confirmed(result)) == 1
    assert resources[0].reference == ResourceRef(
        resource_id="record_a", system_id="store", collection="profiles", physical_table="replica"
    )
    decoded = result[0].observation.payload["decoded_record"]
    assert isinstance(decoded, dict)
    assert decoded["email"] == "new@example.invalid"


def test_ambiguous_identity_has_no_confirmed_links(context: ExtractionContext) -> None:
    items = parse_json({"resource_id": "record_a", "email": "new@example.invalid"}, context)
    result, resources, issues = correlate(
        items, identities=[snapshot(at=T1), snapshot("user_two", at=T1)]
    )
    assert result == []
    assert resources == []
    assert issues == ["identity_not_uniquely_resolved"]


def test_registry_keeps_deferred_images_without_interpreted_facts() -> None:
    manifest = EvidenceFile.model_validate(
        {
            "file_id": "image",
            "file_path": "evidence/images/image.png",
            "origin": "screen",
            "captured_at": T1,
        }
    )
    registry = EvidenceRegistry(
        documents=[
            EvidenceDocument(manifest=manifest, sha256="a" * 64, status="deferred", observations=[])
        ]
    )
    index = EvidenceIndex([], registry=registry)
    resolver = IdentityResolver([snapshot(at=T1)], [])
    assert (
        EvidenceCorrelator(index, resolver).correlate(
            resolver.resolve("new@example.invalid", T3), parse_timestamp(T3)
        )[0]
        == []
    )
    entry = registry.get("image")
    assert entry is not None and entry.parsing_status == "deferred"


@pytest.mark.parametrize("field", ["lookup_key", "match_key", "subject_key"])
@pytest.mark.parametrize("foreign", ["unknown@example.invalid", "user_unknown"])
def test_unknown_subject_contaminates_trace_without_erasing_direct_evidence(
    context: ExtractionContext, field: str, foreign: str
) -> None:
    scoped = replace(context, system="store", collection="profiles")
    items = parse_json(
        [
            {"trace_id": "t1", "lookup_key": "new@example.invalid", "resource_id": "mine"},
            {"trace_id": "t1", field: foreign},
            {"trace_id": "t1", "resource_id": "record_b", "target_resource_id": "downstream"},
            {"resource_id": "record_b"},
            {"resource_id": "downstream"},
        ],
        scoped,
    )
    result, resources, issues = correlate(items)
    assert [o.observation.provenance.locator for o in confirmed(result)] == ["$[0]"]
    assert {r.reference.resource_id for r in resources} == {"mine"}
    assert all(
        o.association == "POTENTIAL"
        for o in result
        if o.observation.trace_id == "t1" and o.observation != items[0]
    )
    assert "ambiguous_trace_scope" in issues
    assert not any(o.observation == items[3] or o.observation == items[4] for o in result)


@pytest.mark.parametrize("known_foreign", [False, True])
def test_mixed_free_text_subjects_do_not_seed_confirmed_links(
    context: ExtractionContext, known_foreign: bool
) -> None:
    identities = [snapshot(at=T1)]
    if known_foreign:
        identities.append(
            snapshot(
                "user_two",
                "other@example.invalid",
                T1,
                phone="+22222222222",
                email_hash="other_hash",
            )
        )
    items = parse_text(
        "Contact new@example.invalid and other@example.invalid about this record.", context
    )
    result, resources, _ = correlate(items, identities=identities)
    assert result[0].association == "POTENTIAL"
    assert not resources


def test_owned_aliases_in_lookup_fields_keep_trace_safe(context: ExtractionContext) -> None:
    items = parse_json(
        [
            {"trace_id": "t1", "lookup_key": "old@example.invalid"},
            {"trace_id": "t1", "match_key": "new@example.invalid"},
            {"trace_id": "t1", "resource_id": "mine"},
        ],
        replace(context, system="store"),
    )
    result, resources, issues = correlate(
        items, changes=[change("a", "old@example.invalid", "new@example.invalid", at=T1)]
    )
    assert len(confirmed(result)) == 3
    assert {r.reference.resource_id for r in resources} == {"mine"}
    assert not issues


def test_future_trace_conflict_does_not_contaminate_visible_trace(
    context: ExtractionContext,
) -> None:
    items = parse_json(
        [
            {"trace_id": "t1", "lookup_key": "new@example.invalid", "updated_at": T1},
            {"trace_id": "t1", "lookup_key": "unknown@example.invalid", "updated_at": T4},
            {"trace_id": "t1", "resource_id": "mine", "updated_at": T2},
        ],
        replace(context, system="store"),
    )
    result, _, issues = correlate(items, cutoff=T3)
    assert len(confirmed(result)) == 2
    assert not issues


def test_resource_join_rejects_explicitly_different_logical_collection(
    context: ExtractionContext,
) -> None:
    first = parse_json(
        {"resource_id": "123", "user_id": "user_one"},
        replace(context, system="store", collection="profiles"),
    )
    other = parse_json(
        {"resource_id": "123"}, replace(context, system="store", collection="exports"), "$.other"
    )
    result, resources, _ = correlate([*first, *other])
    assert len(confirmed(result)) == 1
    assert {r.reference.collection for r in resources} == {"profiles"}


@pytest.mark.parametrize(
    "anchor_collection, collection",
    [("profiles", None), (None, None), (None, "profiles"), ("profiles", "profiles_replica")],
)
def test_one_system_resource_id_joins_when_no_collection_contradicts(
    context: ExtractionContext, anchor_collection: None | str, collection: None | str
) -> None:
    # Phase 5: an export row without a collection (or a replica table of the same family)
    # names the same record of the same system; only a different collection blocks it.
    first = parse_json(
        {"resource_id": "123", "user_id": "user_one"},
        replace(context, system="store", collection=anchor_collection),
    )
    other = parse_json(
        {"resource_id": "123"}, replace(context, system="store", collection=collection), "$.other"
    )
    result, _, _ = correlate([*first, *other])
    assert len(confirmed(result)) == 2


def test_independent_cross_collection_evidence_is_preserved(context: ExtractionContext) -> None:
    items = parse_json(
        [
            {"resource_id": "123", "collection": "profiles", "user_id": "user_one"},
            {"resource_id": "123", "collection": "exports", "user_id": "user_one"},
        ],
        replace(context, system="store"),
    )
    assert len(confirmed(correlate(items)[0])) == 2


@pytest.mark.parametrize(
    "cutoff, expected",
    [(T2, {"$.mine", "$.before"}), (T3, {"$.mine", "$.before"}), (T4, {"$.mine", "$.before"})],
)
def test_resource_reassignment_stops_ownership_propagation(
    context: ExtractionContext, cutoff: str, expected: set[str]
) -> None:
    scoped = replace(
        context,
        system="store",
        collection="profiles",
        manifest=context.manifest.model_copy(update={"captured_at": parse_timestamp(T1)}),
    )
    items = []
    for locator, at, owner in [
        ("$.mine", T1, "user_one"),
        ("$.before", T2, None),
        ("$.foreign", T3, "user_two"),
        ("$.after", T4, None),
    ]:
        items += parse_json(
            {"resource_id": "123", "updated_at": at, "user_id": owner}, scoped, locator
        )
    identities = [
        snapshot(at=T1),
        snapshot(
            "user_two", "other@example.invalid", T1, phone="+22222222222", email_hash="other_hash"
        ),
    ]
    result, _, _ = correlate(items, identities=identities, cutoff=cutoff)
    assert {o.observation.provenance.locator for o in confirmed(result)} == expected


@pytest.mark.parametrize(
    "fields, expected_system",
    [
        ({"related_system": "archive"}, "archive"),
        ({"related_system": "archive", "relationship_direction": "downstream"}, "archive"),
        ({"relationship_direction": "upstream"}, "source"),
        ({"relationship_direction": "downstream"}, "target"),
        ({}, None),
        ({"relationship_direction": "unknown"}, None),
    ],
)
def test_related_resource_system_requires_explicit_direction(
    context: ExtractionContext, fields: dict[str, JsonValue], expected_system: None | str
) -> None:
    anchor = parse_json(
        {
            "resource_id": "anchor",
            "user_id": "user_one",
            "source_system": "source",
            "target_system": "target",
            "related_resource_id": "123",
            **fields,
        },
        replace(context, system="controller", collection="jobs"),
    )
    items = [*anchor]
    for system in ["source", "target", "archive"]:
        items += parse_json(
            {"resource_id": "123"},
            replace(context, system=system, collection="records"),
            f"$.{system}",
        )
    result, resources, _ = correlate(items)
    assert {r.reference.system_id for r in resources if r.reference.resource_id == "123"} == (
        {expected_system} if expected_system else set()
    )
    for item in result:
        if item.observation.resources[0].resource_id == "123":
            assert any(link.method == "EXPLICIT_RESOURCE_REFERENCE" for link in item.links)
            assert item.links[0].supporting_observations[0].locator == "$"


def test_explicit_reference_needs_collection_when_id_collides(context: ExtractionContext) -> None:
    items = parse_json(
        {
            "resource_id": "anchor",
            "user_id": "user_one",
            "target_system": "store",
            "target_resource_id": "123",
        },
        replace(context, system="controller"),
    )
    for collection in ["profiles", "exports"]:
        items += parse_json(
            {"resource_id": "123"},
            replace(context, system="store", collection=collection),
            f"$.{collection}",
        )
    assert len(confirmed(correlate(items)[0])) == 1
    items[0] = items[0].model_copy(
        update={"payload": {**items[0].payload, "target_collection": "exports"}}
    )
    result, resources, _ = correlate(items)
    assert len(confirmed(result)) == 2
    assert {r.reference.collection for r in resources if r.reference.resource_id == "123"} == {
        "exports"
    }


def test_repeating_anchor_resource_id_is_not_an_explicit_cross_collection_link(
    context: ExtractionContext,
) -> None:
    items = parse_json(
        {
            "resource_id": "123",
            "user_id": "user_one",
            "source_system": "store",
            "source_resource_id": "123",
        },
        replace(context, system="store", collection="profiles"),
    )
    items += parse_json(
        {"resource_id": "123"}, replace(context, system="store", collection="exports"), "$.export"
    )
    result, resources, _ = correlate(items)
    assert len(confirmed(result)) == 1
    assert {r.reference.collection for r in resources} == {"profiles"}


def test_observation_permutations_preserve_associations_and_provenance(
    context: ExtractionContext,
) -> None:
    items = parse_json(
        [
            {"trace_id": "t1", "lookup_key": "new@example.invalid", "resource_id": "a"},
            {"trace_id": "t1", "resource_id": "b"},
            {"resource_id": "b"},
            {"resource_id": "a", "collection": "exports"},
        ],
        replace(context, system="store", collection="profiles"),
    )
    expected = correlate(items)
    for permuted in permutations(items):
        assert correlate(permuted) == expected


def test_structural_json_keys_and_integrity_seals_are_not_subjects(
    context: ExtractionContext,
) -> None:
    items = parse_json(
        {
            "resource_id": "mine",
            "user_id": "user_one",
            "record_json": '{"user_id":"user_one"}',
            "integrity_seal": "sha256:" + "a" * 64,
        },
        context,
    )
    result, resources, _ = correlate(items)
    assert len(confirmed(result)) == 1
    assert {r.reference.resource_id for r in resources} == {"mine"}


def test_serialized_subject_field_names_are_not_subject_identifiers(
    context: ExtractionContext,
) -> None:
    items = parse_json(
        {
            "resource_id": "mine",
            "user_id": "user_one",
            "record_json": '{"user_reference":"user_one"}',
        },
        context,
    )
    assert len(confirmed(correlate(items)[0])) == 1


def test_structured_record_type_and_resource_names_are_not_extra_subjects(
    context: ExtractionContext,
) -> None:
    items = parse_json(
        {
            "resource_id": "user_record",
            "user_id": "user_one",
            "record_type": "USER_DOCUMENT",
            "lookup_key": "user_record",
            "text": "USER_DOCUMENT user_record user_one",
        },
        context,
    )
    assert len(confirmed(correlate(items)[0])) == 1


def test_mixed_subjects_inside_one_lookup_field_are_ambiguous(context: ExtractionContext) -> None:
    items = parse_json(
        {"resource_id": "mixed", "lookup_key": "new@example.invalid unknown@example.invalid"},
        context,
    )
    result, resources, _ = correlate(items)
    assert result[0].association == "POTENTIAL"
    assert not resources


def test_future_resource_cannot_explain_unknown_trace_selector(context: ExtractionContext) -> None:
    items = parse_json(
        [
            {"trace_id": "t1", "lookup_key": "new@example.invalid"},
            {"trace_id": "t1", "lookup_key": "customer_unknown"},
            {"trace_id": "t1", "resource_id": "unproven"},
            {"resource_id": "customer_unknown", "updated_at": T4},
        ],
        replace(context, system="store"),
    )
    result, resources, _ = correlate(items, cutoff=T3)
    assert len(confirmed(result)) == 1
    assert not resources


def test_resource_can_return_to_original_owner_without_crossing_foreign_interval(
    context: ExtractionContext,
) -> None:
    scoped = replace(
        context,
        system="store",
        collection="profiles",
        manifest=context.manifest.model_copy(update={"captured_at": parse_timestamp(T1)}),
    )
    items = []
    for locator, at, owner in [
        ("$.foreign", T1, "user_two"),
        ("$.before", T2, None),
        ("$.mine", T3, "user_one"),
        ("$.after", T4, None),
    ]:
        items += parse_json(
            {"resource_id": "123", "updated_at": at, "user_id": owner}, scoped, locator
        )
    result, _, _ = correlate(items)
    # T2 still follows the foreign owner's claim; the T3 anchor cannot backfill it.
    assert {o.observation.provenance.locator for o in confirmed(result)} == {"$.mine", "$.after"}
