"""Typed submission evidence, attributed resources and per-case results."""

from dataclasses import dataclass, field
from ghost_audit.domain.output_contract import OutputRow


@dataclass
class Fact:
    """One interpreted, time-bounded statement about a resource in one evidence file."""

    evidence_id: str
    at: object
    captured_at: object
    scope: str
    verdicts: dict  # action -> 'VIOLATION' | 'COMPLIANT'
    kind: str = "readback"


@dataclass
class Listing:
    evidence_id: str
    at: object
    captured_at: object
    system: str
    prefix: str
    scope: str
    ids: frozenset


@dataclass
class Resource:
    resource_id: str
    system_id: str
    methods: set = field(default_factory=set)


@dataclass
class CasePrediction:
    case_id: str
    row: OutputRow
    user_id: str | None
    resources: dict
    notes: list[str]
    low_confidence: list[str]
