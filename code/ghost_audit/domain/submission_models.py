"""Typed submission evidence, attributed resources and per-case results."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from ghost_audit.domain.output_contract import OutputRow

Action = Literal["DELETE", "REDACT", "ANONYMIZE", "RETAIN", "DISABLE", "BLOCK"]
Verdict = Literal["VIOLATION", "COMPLIANT", "UNKNOWN"]
RecordSignals = dict[str, set[str]]


@dataclass
class Fact:
    """One interpreted, time-bounded statement about a resource in one evidence file."""

    evidence_id: str
    at: datetime
    captured_at: datetime
    scope: str
    verdicts: dict[Action, Verdict]
    kind: str = "readback"


@dataclass
class Listing:
    evidence_id: str
    at: datetime | None
    captured_at: datetime | None
    system: str | None
    prefix: str
    scope: str
    ids: frozenset[str]


@dataclass
class Resource:
    """A submission-attributed resource and the methods used to attribute it."""

    resource_id: str
    system_id: str
    methods: set[str] = field(default_factory=set)


@dataclass
class CasePrediction:
    """One submission row plus attribution, ambiguity and confidence diagnostics."""

    case_id: str
    row: OutputRow
    user_id: str | None
    resources: dict[str, list[str]]
    notes: list[str]
    low_confidence: list[str]


@dataclass
class ResourceAssessment:
    """Selected submission verdict plus its complete candidate fact history.

    A non-UNKNOWN verdict always names a supporting fact. Historical facts remain
    available for the existing all-unknown pre-request fallback.
    """

    resource: Resource
    category: str
    action: Action
    verdict: Verdict
    fact: Fact | None
    facts: list[Fact]
