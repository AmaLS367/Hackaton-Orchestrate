"""Production pipeline. Sample answers are deliberately outside this module's imports."""

from collections import Counter
from time import perf_counter

from ghost_audit.application.abstention_diagnostics import diagnose, summarize
from ghost_audit.application.evidence_association import EvidenceAssociationService
from ghost_audit.application.temporal_service import TemporalStateEngine
from ghost_audit.domain.citation_validation import validate_output
from ghost_audit.domain.dataset import Dataset
from ghost_audit.domain.evidence_index import EvidenceIndex
from ghost_audit.domain.planning import plan_case
from ghost_audit.domain.policy import PolicyEvaluator
from ghost_audit.domain.policy_models import PredictionRun


class PredictionBlocked(ValueError):
    """Strict publication cannot represent every request with grounded evidence."""

    pass


def predict(dataset: Dataset, index: EvidenceIndex | None = None) -> PredictionRun:
    """Run the strict use case over every request, preserving undecidable cases."""
    started = perf_counter()
    association_service = EvidenceAssociationService(dataset, index)
    state_engine = TemporalStateEngine(association_service.index)
    policy = PolicyEvaluator(dataset.rules)
    cases = []
    validation_errors = []
    abstentions = []
    for request in sorted(dataset.requests, key=lambda r: r.case_id):
        evidence = association_service.analyze(request)
        bundle = state_engine.analyze(evidence)
        assessments = policy.evaluate(bundle) if bundle.intent.decision == "DELETE_INTENT" else []
        decision = plan_case(bundle, assessments)
        if decision.prediction is not None:
            try:
                checks = validate_output([decision.prediction], [request], association_service.index)
                if any(
                    check.resource_support == "unknown" or check.parsing_status != "parsed"
                    for check in checks
                ):
                    raise ValueError("prediction citation lacks parsed resource linkage")
            except ValueError as exc:
                message = f"{request.case_id}: {exc}"
                validation_errors.append(message)
                decision = decision.model_copy(
                    update={
                        "prediction": None,
                        "decision": "UNDECIDABLE",
                        "blockers": sorted({*decision.blockers, "prediction_validation_failed"}),
                    }
                )
        cases.append(decision)
        if decision.prediction is None:
            abstentions.append(diagnose(evidence, bundle, decision, association_service.index))
    return PredictionRun(
        cases=cases,
        elapsed_seconds=perf_counter() - started,
        validation_errors=validation_errors,
        abstentions=abstentions,
    )


def diagnostics(run: PredictionRun) -> dict:
    counts: Counter[str] = Counter(case.decision for case in run.cases)
    assessments = [a for c in run.cases for a in c.assessments]
    return {
        "cases_processed": len(run.cases),
        "status_counts": {s: counts[s] for s in ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")},
        "undecidable_cases": [c.case_id for c in run.cases if c.prediction is None],
        "undecidable_count": counts["UNDECIDABLE"],
        "cases_with_unresolved_evidence": sum(bool(c.unresolved or c.blockers) for c in run.cases),
        "unsupported_policy_states": sum(a.compliance == "UNKNOWN" for a in assessments),
        "missing_evidence_states": sum(not a.evidence for a in assessments),
        "policy_violations_by_category": dict(
            sorted(Counter(a.category for a in assessments if a.compliance == "VIOLATION").items())
        ),
        "operation_counts": dict(
            sorted(Counter(s.operation for r in run.predictions for s in r.steps).items())
        ),
        "unresolved_causes": dict(
            sorted(Counter(reason for c in run.cases for reason in c.unresolved).items())
        ),
        "blocker_causes": dict(
            sorted(Counter(reason for c in run.cases for reason in c.blockers).items())
        ),
        "abstention_root_causes": summarize(run.abstentions),
        "validation_errors": run.validation_errors,
        "validated_prediction_rows": len(run.predictions),
        "full_output_validation": "ready_to_publish"
        if run.publishable
        else "blocked_by_abstentions_or_validation_errors",
        "publishable": run.publishable,
        "runtime_seconds": round(run.elapsed_seconds, 4),
        "runtime_scope": "prediction and per-row validation; excludes dataset ingestion and diagnostic serialization",
        "runtime_model_usage": {
            "providers": [],
            "models": [],
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "average_tokens_per_request": 0,
            "estimated_total_cost_usd": 0,
            "estimated_cost_per_request_usd": 0,
        },
        "coverage": "Discovered evidence only. Unassigned deferred files are not attributed to any case.",
    }
