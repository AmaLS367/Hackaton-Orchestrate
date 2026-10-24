"""Production pipeline. Sample answers are deliberately outside this module's imports."""

import json
from collections import Counter
from pathlib import Path
from time import perf_counter

from .index import EvidenceIndex
from .output import validate_output, write_output
from .phase2 import Phase2Analyzer
from .planning import plan_case
from .policy import PolicyEvaluator
from .policy_models import PredictionRun
from .temporal import TemporalStateEngine


class PredictionBlocked(ValueError):
    pass


def predict(dataset, index: EvidenceIndex | None = None) -> PredictionRun:
    started = perf_counter()
    phase2 = Phase2Analyzer(dataset, index)
    phase3 = TemporalStateEngine(phase2.index)
    policy = PolicyEvaluator(dataset.rules)
    cases = []
    validation_errors = []
    for request in sorted(dataset.requests, key=lambda r: r.case_id):
        bundle = phase3.analyze(phase2.analyze(request))
        assessments = policy.evaluate(bundle) if bundle.intent.decision == 'DELETE_INTENT' else []
        decision = plan_case(bundle, assessments)
        if decision.prediction is not None:
            try:
                checks = validate_output([decision.prediction], [request], phase2.index)
                if any(check.resource_support == 'unknown' or check.parsing_status != 'parsed' for check in checks):
                    raise ValueError('prediction citation lacks parsed resource linkage')
            except ValueError as exc:
                message = f'{request.case_id}: {exc}'
                validation_errors.append(message)
                decision = decision.model_copy(update={'prediction': None, 'decision': 'UNDECIDABLE',
                    'blockers': sorted(set([*decision.blockers, 'prediction_validation_failed']))})
        cases.append(decision)
    return PredictionRun(cases=cases, elapsed_seconds=perf_counter() - started, validation_errors=validation_errors)


def diagnostics(run: PredictionRun) -> dict:
    counts = Counter(case.decision for case in run.cases)
    assessments = [a for c in run.cases for a in c.assessments]
    return {
        'cases_processed': len(run.cases),
        'status_counts': {s: counts[s] for s in ('COMPLETE', 'INCOMPLETE', 'NOT_APPLICABLE')},
        'undecidable_cases': [c.case_id for c in run.cases if c.prediction is None],
        'undecidable_count': counts['UNDECIDABLE'],
        'cases_with_unresolved_evidence': sum(bool(c.unresolved or c.blockers) for c in run.cases),
        'unsupported_policy_states': sum(a.compliance == 'UNKNOWN' for a in assessments),
        'missing_evidence_states': sum(not a.evidence for a in assessments),
        'policy_violations_by_category': dict(sorted(Counter(a.category for a in assessments
            if a.compliance == 'VIOLATION').items())),
        'operation_counts': dict(sorted(Counter(s.operation for r in run.predictions for s in r.steps).items())),
        'unresolved_causes': dict(sorted(Counter(reason for c in run.cases for reason in c.unresolved).items())),
        'blocker_causes': dict(sorted(Counter(reason for c in run.cases for reason in c.blockers).items())),
        'validation_errors': run.validation_errors,
        'validated_prediction_rows': len(run.predictions),
        'full_output_validation': 'ready_to_publish' if run.publishable else 'blocked_by_abstentions_or_validation_errors',
        'publishable': run.publishable,
        'runtime_seconds': round(run.elapsed_seconds, 4),
        'runtime_scope': 'prediction and per-row validation; excludes dataset ingestion and diagnostic serialization',
        'runtime_model_usage': {'providers': [], 'models': [], 'calls': 0, 'input_tokens': 0,
            'output_tokens': 0, 'total_tokens': 0, 'average_tokens_per_request': 0,
            'estimated_total_cost_usd': 0, 'estimated_cost_per_request_usd': 0},
        'coverage': 'Discovered evidence only. Unassigned deferred files are not attributed to any case.',
    }


def write_diagnostics(path: Path, run: PredictionRun) -> None:
    """Explicit diagnostic artifact, including partial predictions; never a submission CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {'summary': diagnostics(run), 'cases': [case.model_dump(mode='json') for case in run.cases]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def publish(path, run, dataset, index):
    if not run.publishable:
        raise PredictionBlocked(f'{len(run.cases) - len(run.predictions)} cases have no grounded prediction; '
                                'output was not written or replaced. See diagnostics for blockers.')
    write_output(path, run.predictions, dataset.requests, index)
