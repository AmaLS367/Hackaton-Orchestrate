"""Policy decisions and abstentions are separate from the official output schema."""

from typing import Literal

from pydantic import Field

from .models import StrictModel
from .output import OutputRow
from .phase2_models import ObservationLink
from .temporal_models import ResourceScope


class PolicyAssessment(StrictModel):
    scope: ResourceScope
    dimension: Literal['record', 'flow', 'restore']
    category: str | None
    rule_id: str | None = None
    required_action: Literal['DELETE', 'REDACT', 'ANONYMIZE', 'RETAIN', 'DISABLE', 'BLOCK'] | None = None
    required_state: str | None = None
    observed_state: str
    compliance: Literal['COMPLIANT', 'VIOLATION', 'UNKNOWN']
    evidence: list[ObservationLink] = Field(default_factory=list)
    condition_evidence: list[ObservationLink] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class CaseDecision(StrictModel):
    case_id: str
    prediction: OutputRow | None
    assessments: list[PolicyAssessment]
    unresolved: list[str]
    blockers: list[str]
    # The official contract has no abstention label. None never enters output.csv.
    decision: Literal['COMPLETE', 'INCOMPLETE', 'NOT_APPLICABLE', 'UNDECIDABLE']


class PredictionRun(StrictModel):
    cases: list[CaseDecision]
    elapsed_seconds: float
    validation_errors: list[str] = Field(default_factory=list)

    @property
    def predictions(self) -> list[OutputRow]:
        return [case.prediction for case in self.cases if case.prediction is not None]

    @property
    def publishable(self) -> bool:
        return bool(self.cases) and all(case.prediction is not None for case in self.cases) and not self.validation_errors
