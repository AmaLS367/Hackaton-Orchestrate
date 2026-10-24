"""Transparent local metrics; these are not the hidden organizer scoring formula."""

from collections import Counter
from dataclasses import asdict, dataclass

from ghost_audit.output import OutputRow


@dataclass(frozen=True)
class EvaluationMetrics:
    reference_cases: int
    predicted_cases: int
    missing_cases: int
    status_accuracy: float
    step_accuracy: float
    step_precision: float
    step_recall: float
    field_accuracy: float
    sequence_accuracy: float
    exact_case_accuracy: float

    def markdown(self) -> str:
        return "\n".join(f"- {key}: {value}" for key, value in asdict(self).items())


def _step_signature(step):
    # Step accuracy ignores position; sequence accuracy below includes it.
    return tuple((key, value) for key, value in step.model_dump().items() if key != "step_no")


def evaluate(predictions: list[OutputRow], references: list[OutputRow]) -> EvaluationMetrics:
    predicted = {row.case_id: row for row in predictions}
    expected = {row.case_id: row for row in references}
    if len(predicted) != len(predictions) or len(expected) != len(references):
        raise ValueError("duplicate evaluation case_id")
    if not expected:
        raise ValueError("evaluation requires reference cases")
    if set(predicted) - set(expected):
        raise ValueError("predictions contain cases outside the reference set")
    status_hits = sequence_hits = exact_hits = step_hits = field_hits = 0
    predicted_steps = expected_steps = step_slots = field_slots = 0
    for case_id, target in expected.items():
        actual = predicted.get(case_id)
        actual_steps = actual.steps if actual else []
        expected_steps += len(target.steps)
        predicted_steps += len(actual_steps)
        slots = max(len(target.steps), len(actual_steps))
        step_slots += slots
        field_slots += slots * 7
        step_hits += sum((Counter(map(_step_signature, actual_steps)) &
                          Counter(map(_step_signature, target.steps))).values())
        for left, right in zip(actual_steps, target.steps):
            field_hits += sum(left.model_dump()[key] == value for key, value in right.model_dump().items())
        if actual is not None:
            status_hits += actual.deletion_status == target.deletion_status
            sequence_hits += actual.steps == target.steps
            exact_hits += actual == target
    count = len(expected)

    def ratio(hits, total):
        # No steps is perfect only when every reference case was supplied.
        return hits / total if total else float(
            predicted_steps == expected_steps == 0 and len(predicted) == count
        )

    return EvaluationMetrics(
        count, len(predicted), count - len(predicted), status_hits / count,
        ratio(step_hits, step_slots), ratio(step_hits, predicted_steps), ratio(step_hits, expected_steps),
        ratio(field_hits, field_slots), sequence_hits / count, exact_hits / count,
    )
