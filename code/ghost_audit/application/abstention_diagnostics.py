"""Actionable diagnostics for cases without a grounded prediction.

Records hold only case, resource, evidence and reason identifiers: never names, emails,
phones, hashes or evidence text. Candidate resources and unlinked readbacks are search
leads for investigation; none is the subject's record until independently linked.
"""

from collections import Counter
from collections.abc import Iterable
from datetime import datetime

from ghost_audit.application.observation_interpretation import interpret
from ghost_audit.domain.association_models import (
    AssociatedObservation,
    CaseEvidenceBundle,
    CorrelationLink,
    ObservationLink,
)
from ghost_audit.domain.diagnostic_models import AbstentionDiagnostic, Obligation
from ghost_audit.domain.evidence_index import EvidenceIndex
from ghost_audit.domain.models import ResourceRef
from ghost_audit.domain.observation_clocks import logical_collection
from ghost_audit.domain.policy_models import CaseDecision, PolicyAssessment
from ghost_audit.domain.temporal_models import CaseStateBundle, ResourceHistory, ResourceScope

STAGES = ("EXTRACT", "ASSOCIATE", "INTERPRET", "APPLY_POLICY", "PLAN", "VALIDATE")
# Root cause -> the pipeline stage where the case first fails for that cause.
CAUSE_STAGES = {
    "unparsed_candidate_evidence": "EXTRACT",
    "identity_not_resolved": "ASSOCIATE",
    "no_confirmed_resources": "ASSOCIATE",
    "account_ownership_unproven": "ASSOCIATE",
    "primary_profile_candidates_ambiguous": "ASSOCIATE",
    "readback_exists_but_unlinked": "ASSOCIATE",
    "resource_system_unknown": "ASSOCIATE",
    "no_state_readback": "INTERPRET",
    "operation_claims_only": "INTERPRET",
    "readback_uninterpreted": "INTERPRET",
    "conflicting_observations_or_replicas": "INTERPRET",
    "field_coverage_incomplete": "INTERPRET",
    "state_evidence_outside_audit_cutoff": "INTERPRET",
    "policy_condition_missing": "APPLY_POLICY",
    "policy_category_unknown": "APPLY_POLICY",
    "required_retained_record_missing": "APPLY_POLICY",
    "plan_dependency_or_treatment_conflict": "PLAN",
    "prediction_validation_failed": "VALIDATE",
}
FIELD_COVERAGE = {
    "anonymization_field_coverage_insufficient",
    "redaction_field_coverage_insufficient",
    "permitted_stable_reference_unproven",
    "conflicting_identifier_fields",
}


def label(ref: ResourceRef | ResourceScope) -> str:
    """Render a system/resource label without copying personal identity fields."""
    return f"{ref.system_id or '?'}:{ref.resource_id}"


def listing_coverage(
    index: EvidenceIndex, refs: Iterable[ResourceRef], cutoff: datetime
) -> dict[str, str]:
    """Per unresolved resource: whether any listing of its collection known by the cutoff
    could prove absence by omission, and if not, why not."""
    listings_by_collection = index.coverage_listings
    result = {}
    for ref in refs:
        collection = logical_collection(ref)
        if not collection:
            result[label(ref)] = "COLLECTION_UNKNOWN"
            continue
        listings = [
            item
            for item in listings_by_collection.get((ref.system_id, collection), ())
            if item.observed_at is not None
            and item.observed_at <= cutoff
            and item.surface.available_at is not None
            and item.surface.available_at <= cutoff
        ]
        result[label(ref)] = (
            "NO_LISTING_OF_COLLECTION"
            if not listings
            else "COMPLETE_LISTING_AVAILABLE"
            if any(item.complete for item in listings)
            else "LISTINGS_WITHOUT_COMPLETENESS_PROOF"
        )
    return dict(sorted(result.items()))


def readback_states(index: EvidenceIndex, ref: ResourceRef, cutoff: datetime) -> list[str]:
    """'evidence_id=STATE' for citable reads of one exact system resource, ignoring ownership."""
    found = set()
    for i in sorted(index.by_resource.get(ref.resource_id, ())):
        o = index.observations[i]
        entry = index.registry.get(o.provenance.evidence_id)
        if (
            o.kind != "evidence"
            or o.available_at is None
            or o.available_at > cutoff
            or entry is None
            or entry.parsing_status != "parsed"
        ):
            continue
        for r in o.resources:
            if r.resource_id == ref.resource_id and r.system_id == ref.system_id:
                item = AssociatedObservation(
                    observation=o,
                    association="CONFIRMED",
                    reason="diagnostic_only",
                    links=[
                        CorrelationLink(
                            method="RESOURCE", supporting_observations=[ObservationLink.of(o)]
                        )
                    ],
                )
                fact = interpret(item, r)
                if (
                    fact.support == "PROVEN"
                    and fact.record_state != "UNKNOWN"
                    and fact.observed_at <= cutoff
                ):
                    found.add(f"{o.provenance.evidence_id}={fact.record_state}")
    return sorted(found)


def late_evidence(
    index: EvidenceIndex, evidence: CaseEvidenceBundle, resources: Iterable[ResourceRef]
) -> list[str]:
    """Evidence naming the subject's identifiers or case resources, available only after the audit."""
    values = [a.normalized_value for a in evidence.aliases if a.field_name != "name"]
    late = set()
    for o in index.lookup(identifiers=values) if values else ():
        if (
            o.kind == "evidence"
            and o.available_at is not None
            and o.available_at > evidence.audit_at
        ):
            late.add(o.provenance.evidence_id)
    for ref in resources:
        for i in index.by_resource.get(ref.resource_id, ()):
            o = index.observations[i]
            if (
                o.kind == "evidence"
                and o.available_at is not None
                and o.available_at > evidence.audit_at
                and any(r.system_id == ref.system_id for r in o.resources)
            ):
                late.add(o.provenance.evidence_id)
    return sorted(late)


def assessment_causes(assessment: PolicyAssessment, histories: list[ResourceHistory]) -> list[str]:
    """Map unresolved assessment reasons to actionable diagnostic cause identifiers."""
    reasons = set(assessment.reasons)
    causes = set()
    if "policy_condition_unestablished_or_ambiguous" in reasons:
        causes.add("policy_condition_missing")
    if "policy_category_unknown" in reasons:
        causes.add("policy_category_unknown")
    if reasons & FIELD_COVERAGE:
        causes.add("field_coverage_incomplete")
    if reasons & {
        "required_preserved_record_absent",
        "required_retained_record_missing_no_supported_recreation_operation",
    }:
        causes.add("required_retained_record_missing")
    if reasons & {
        "no_confirmed_state_evidence",
        "record_state_unproven",
        "process_safety_unproven",
    }:
        observations = [
            o for h in histories for o in h.observations if o.association == "CONFIRMED"
        ]
        if any(o.support == "CONFLICTED" for o in observations) or any(
            getattr(h, assessment.dimension).support == "CONFLICTED" for h in histories
        ):
            causes.add("conflicting_observations_or_replicas")
        elif observations and all(o.support == "CLAIM_ONLY" for o in observations):
            causes.add("operation_claims_only")
        elif any(o.category == "UNINTERPRETED" or o.support == "UNKNOWN" for o in observations):
            causes.add("readback_uninterpreted")
        else:
            causes.add("no_state_readback")
    if assessment.scope.system_id is None:
        causes.add("resource_system_unknown")
    return sorted(causes) or ["policy_or_state_unknown"]


def diagnose(
    evidence: CaseEvidenceBundle,
    state: CaseStateBundle,
    decision: CaseDecision,
    index: EvidenceIndex,
) -> AbstentionDiagnostic:
    """decision: the planner's CaseDecision for this case."""
    cutoff = evidence.audit_at
    confirmed = {label(r.reference) for r in evidence.resources}
    potential: dict[str, tuple[ResourceRef, str]] = {}
    for item in evidence.observations:
        if item.association == "POTENTIAL":
            for r in item.observation.resources:
                if label(r) not in confirmed:
                    potential.setdefault(label(r), (r, item.reason))
    candidates = {label(r): r for r in evidence.primary_profile_candidates}
    proven: dict[str, list[str]] = {}
    unknown: dict[str, list[str]] = {}
    by_resource: dict[str, list[ResourceHistory]] = {}
    for h in state.resource_histories:
        key = label(h.scope)
        by_resource.setdefault(key, []).append(h)
        if h.record.support == "PROVEN" and h.record.state != "UNKNOWN":
            proven.setdefault(key, []).append(f"{h.scope.replica_scope}={h.record.state}")
        for dimension in ("flow", "restore"):
            selection = getattr(h, dimension)
            if selection.support == "PROVEN" and selection.state != "UNKNOWN":
                proven.setdefault(key, []).append(
                    f"{h.scope.replica_scope}:{dimension}={selection.state}"
                )
        if h.record.state == "UNKNOWN" and not any(
            getattr(h, d).support == "PROVEN" for d in ("flow", "restore")
        ):
            unknown.setdefault(key, []).append(f"{h.scope.replica_scope}:{h.record.reason}")
    unlinked = {}
    for key, ref in sorted({**{k: v[0] for k, v in potential.items()}, **candidates}.items()):
        states = readback_states(index, ref, cutoff)
        if states:
            unlinked[key] = states
    obligations, causes = [], set()
    missing_conditions = set()
    for a in decision.assessments:
        if a.compliance != "UNKNOWN":
            continue
        key = label(a.scope)
        found = assessment_causes(a, by_resource.get(key, []))
        if "policy_condition_missing" in found:
            missing_conditions.add(f"{key}:{a.category}")
        if not any(
            o.association == "CONFIRMED" and o.association_links
            for h in by_resource.get(key, [])
            for o in h.observations
        ):
            # Only the workflow candidate names this resource; ownership is unproven.
            found = sorted(
                {
                    *found,
                    "readback_exists_but_unlinked"
                    if key in unlinked
                    else "account_ownership_unproven",
                }
                - {"no_state_readback"}
            )
        causes.update(found)
        obligations.append(
            Obligation(
                resource=key,
                scope=a.scope.replica_scope,
                category=a.category,
                required_action=a.required_action,
                observed_state=a.observed_state,
                causes=found,
            )
        )
    treated = sorted(
        {
            label(a.scope)
            for a in decision.assessments
            if a.compliance == "COMPLIANT"
            and a.required_action in {"DELETE", "REDACT", "ANONYMIZE"}
        }
    )
    violations = sorted(
        {label(a.scope) for a in decision.assessments if a.compliance == "VIOLATION"}
    )
    accounts = sorted(k for k in confirmed if k.startswith("account_service:"))
    potential_accounts = sorted(
        k for k in [*potential, *candidates] if k.startswith("account_service:")
    )
    attribution = (
        "CONFIRMED"
        if accounts
        else "AMBIGUOUS_WORKFLOW_CANDIDATES"
        if len(candidates) > 1
        else "WORKFLOW_CANDIDATE_ONLY"
        if potential_accounts
        else "NO_ACCOUNT_REFERENCE"
    )
    if evidence.identity.status != "RESOLVED":
        causes.add("identity_not_resolved")
    elif not confirmed:
        causes.add("no_confirmed_resources")
    if "primary_profile_ownership_or_search_coverage_unproven" in decision.blockers:
        causes.add("primary_profile_candidates_ambiguous")
    if "no_verified_deletion_treatment" in decision.blockers and attribution != "CONFIRMED":
        causes.add(
            "readback_exists_but_unlinked"
            if set(potential_accounts) & set(unlinked)
            else "account_ownership_unproven"
        )
    if any(b.startswith(("cleanup_dependency", "incompatible_policy")) for b in decision.blockers):
        causes.add("plan_dependency_or_treatment_conflict")
    if "prediction_validation_failed" in decision.blockers:
        causes.add("prediction_validation_failed")
    late = late_evidence(
        index,
        evidence,
        [r.reference for r in evidence.resources]
        + [v[0] for v in potential.values()]
        + list(candidates.values()),
    )
    if late and causes & {
        "no_state_readback",
        "account_ownership_unproven",
        "no_confirmed_resources",
    }:
        causes.add("state_evidence_outside_audit_cutoff")
    if any(e.parsing_status == "deferred" for e in evidence.deferred_evidence):
        causes.add("unparsed_candidate_evidence")
    causes.discard("policy_or_state_unknown")
    stages = Counter(CAUSE_STAGES[c] for c in causes)
    earliest = next((s for s in STAGES if stages[s]), None)
    candidate_ids = sorted(
        {
            link.evidence_id
            for item in evidence.observations
            if item.association == "POTENTIAL"
            for chain in item.links
            for link in chain.supporting_observations
        }
        | {e.split("=")[0] for values in unlinked.values() for e in values}
    )
    return AbstentionDiagnostic(
        case_id=evidence.case_id,
        intent=evidence.intent.decision,
        identity=evidence.identity.status,
        confirmed_resources=sorted(confirmed),
        potential_resources=sorted(potential),
        primary_profile_candidates=sorted(candidates),
        proven_states=dict(sorted(proven.items())),
        unknown_states=dict(sorted(unknown.items())),
        verified_deletion_treatment=treated,
        violations=violations,
        missing_policy_conditions=sorted(missing_conditions),
        account_attribution=attribution,
        listing_coverage=listing_coverage(
            index,
            [
                *(
                    ResourceRef(
                        resource_id=h.scope.resource_id,
                        system_id=h.scope.system_id,
                        collection=h.scope.collection,
                    )
                    for h in state.resource_histories
                    if h.record.state == "UNKNOWN"
                    and not any(getattr(h, d).support == "PROVEN" for d in ("flow", "restore"))
                ),
                *(v[0] for v in potential.values()),
                *candidates.values(),
            ],
            cutoff,
        ),
        candidate_evidence_ids=candidate_ids,
        unlinked_readbacks=unlinked,
        late_evidence_ids=late,
        unresolved_obligations=sorted(obligations, key=lambda o: (o.resource, o.scope)),
        blockers=decision.blockers,
        root_causes=sorted(causes),
        earliest_failure_stage=earliest,
        stage_counts={s: stages[s] for s in STAGES if stages[s]},
    )


def summarize(records: list[AbstentionDiagnostic]) -> dict:
    """Aggregate counts. Causes overlap within a case, so cause counts do not sum to cases."""
    return {
        "abstentions": len(records),
        "earliest_failure_stage": {
            s: sum(r.earliest_failure_stage == s for r in records) for s in STAGES
        },
        "root_causes": dict(sorted(Counter(c for r in records for c in r.root_causes).items())),
        "account_attribution": dict(
            sorted(Counter(r.account_attribution for r in records).items())
        ),
        "cases_with_unlinked_readbacks": sum(bool(r.unlinked_readbacks) for r in records),
        "cases_with_late_evidence": sum(bool(r.late_evidence_ids) for r in records),
        "cases_with_missing_policy_conditions": sum(
            bool(r.missing_policy_conditions) for r in records
        ),
        "listing_coverage_of_unresolved_resources": dict(
            sorted(Counter(v for r in records for v in r.listing_coverage.values()).items())
        ),
        "note": "Candidate resources and unlinked readbacks are leads, not confirmed ownership.",
    }
