"""Typed envelopes for synthetic fixtures and the protected regression contract."""

from collections.abc import Mapping, Sequence
from typing import TypedDict

from pydantic import JsonValue, RootModel

SnapshotSection = tuple[str, str, str, Sequence[Mapping[str, object]]]


class JsonFixture(RootModel[JsonValue]):
    """Validate synthetic raw mappings before handing them to the JSON parser."""


class LookupFields(TypedDict, total=False):
    """Synthetic service readbacks with no envelope or scope overrides."""

    rows: int
    http_status: int
    result: str
    total_hits: int


class RecordFields(TypedDict, total=False):
    """Policy fields varied by the preservation test matrix."""

    retention_until: str
    enabled: bool
    restore_allowed: bool


class StepChanges(TypedDict, total=False):
    """Raw malformed step fields are validated by OutputStep in negative tests."""

    step_no: object
    state: object
    phase: object
    operation: str
    unexpected: object
    resource_id: object
    system_id: object
    evidence_id: object


class BaselineContract(TypedDict):
    """Checksums and public metrics only; never prediction inputs."""

    baseline_commit: str
    output_sha256: str
    strict_sha256: str
    submission_sha256: str
    dataset_sha256: str
    counts: dict[str, int]
    steps: int
    sample_metrics: dict[str, float | int]
    strict_sample_metrics: dict[str, float | int]
    scenario_renames: dict[str, str]
    original_scenarios: list[str]
