"""Reusable Phase 2 services and privacy-conscious diagnostics."""

from collections import Counter, defaultdict
from datetime import datetime

from ghost_audit.domain.association_models import AssociatedObservation, CaseEvidenceBundle
from ghost_audit.domain.correlation import EvidenceCorrelator
from ghost_audit.domain.dataset import Dataset
from ghost_audit.domain.evidence_index import EvidenceIndex
from ghost_audit.domain.identity import IdentityResolver
from ghost_audit.domain.intent import IntentClassifier
from ghost_audit.domain.models import DeletionRequest, Observation
from ghost_audit.domain.workflow_attribution import WorkflowAttribution


class EvidenceAssociationService:
    """Coordinate identity, bounded discovery and per-case evidence bundles."""

    def __init__(self, dataset: Dataset, index: EvidenceIndex | None = None):
        self.dataset = dataset
        self.index = (
            index
            if index is not None
            else EvidenceIndex(dataset.observations, registry=dataset.registry)
        )
        self.resolver = IdentityResolver(dataset.identities, dataset.identity_changes)
        self.classifier = IntentClassifier()
        self.correlator = EvidenceCorrelator(self.index, self.resolver)
        universe = getattr(dataset, "workflow_requests", None) or dataset.requests
        self.workflow = WorkflowAttribution(
            universe, self.index, self.resolver, self.correlator, self.classifier
        )
        self.by_subject = defaultdict(list)
        for other in self.workflow.requests:
            self.by_subject[self.workflow.users[other.case_id]].append(other)

    def prior_audit(self, request: DeletionRequest, user: str | None) -> datetime | None:
        """Latest audit of an earlier authorized request by the same subject."""
        earlier = [
            r.audit_at
            for r in self.by_subject.get(user, ())
            if r.case_id != request.case_id and r.audit_at < request.requested_at
        ]
        return max(earlier, default=None)

    def analyze(self, request: DeletionRequest) -> CaseEvidenceBundle:
        identity = self.resolver.resolve(request)
        observations, resources, ambiguities = self.correlator.correlate(
            identity,
            request.audit_at,
            workflow_seeds=self.workflow.attributed(request),
            prior_audit=self.prior_audit(request, identity.user_id),
        )
        deferred = sorted(
            (
                entry
                for entry in self.index.registry.entries.values()
                if entry.parsing_status == "deferred"
                and entry.captured_at is not None
                and entry.captured_at <= request.audit_at
            ),
            key=lambda e: e.evidence_id,
        )
        visible = sum(
            o.kind != "identity"
            and o.available_at is not None
            and o.available_at <= request.audit_at
            for o in self.index.observations
        )
        evidence_ids = {
            o.observation.provenance.evidence_id
            for o in observations
            if o.association == "CONFIRMED"
        }
        evidence_ids.update(a.audit_id for a in identity.aliases if a.audit_id)
        return CaseEvidenceBundle(
            case_id=request.case_id,
            audit_at=request.audit_at,
            intent=self.classifier.classify(request),
            identity=identity,
            user_id=identity.user_id,
            aliases=identity.aliases,
            observations=observations,
            resources=resources,
            supporting_evidence_ids=sorted(evidence_ids),
            deferred_evidence=deferred,
            ambiguities=sorted({*identity.ambiguities, *ambiguities}),
            limitations=[
                "Associations do not establish record state or policy compliance.",
                "Deferred files are an unassigned candidate pool; contents and subject are unknown.",
                "Unmatched documents and unsupported relationships require further interpretation.",
            ],
            unrelated_observation_count=visible - len(observations),
            primary_profile_candidates=sorted(
                (
                    r
                    for i in self.workflow.primary_candidates(request)
                    for r in self.index.observations[i].resources
                ),
                key=lambda r: (r.system_id or "", r.resource_id),
            ),
        )

    @staticmethod
    def association_for(
        bundle: CaseEvidenceBundle, observation: Observation
    ) -> AssociatedObservation:
        """Query omitted observations explicitly, without duplicating the corpus per case."""
        for item in bundle.observations:
            if item.observation == observation:
                return item
        return AssociatedObservation(
            observation=observation,
            association="UNRELATED",
            reason="no_supported_association_at_cutoff",
        )


def diagnostics(bundles: list[CaseEvidenceBundle]) -> dict:
    def confirmed(b):
        return any(o.association == "CONFIRMED" for o in b.observations)

    def potential(b):
        return any(o.association == "POTENTIAL" for o in b.observations)

    additional = [
        b.case_id
        for b in bundles
        if b.intent.fallback_recommended
        or b.identity.status != "RESOLVED"
        or b.ambiguities
        or not confirmed(b)
        or b.deferred_evidence
    ]
    intent_counts: Counter[str] = Counter(b.intent.decision for b in bundles)
    identity_counts: Counter[str] = Counter(b.identity.status for b in bundles)
    return {
        "cases": len(bundles),
        "intent": {
            key: intent_counts[key] for key in ("DELETE_INTENT", "NO_DELETE_INTENT", "UNCERTAIN")
        },
        "identity": {key: identity_counts[key] for key in ("RESOLVED", "AMBIGUOUS", "UNRESOLVED")},
        "cases_with_confirmed_associations": sum(confirmed(b) for b in bundles),
        "cases_with_potential_associations": sum(potential(b) for b in bundles),
        "cases_without_confirmed_associations": sum(not confirmed(b) for b in bundles),
        "correlated_observations": sum(
            o.association == "CONFIRMED" for b in bundles for o in b.observations
        ),
        "distinct_correlated_observations": len(
            {
                (o.observation.provenance.evidence_id, o.observation.provenance.locator)
                for b in bundles
                for o in b.observations
                if o.association == "CONFIRMED"
            }
        ),
        "distinct_resources": len(
            {(r.reference.system_id, r.reference.resource_id) for b in bundles for r in b.resources}
        ),
        "deferred_files_available": len(
            {e.evidence_id for b in bundles for e in b.deferred_evidence}
        ),
        "cases_with_unassigned_deferred_evidence": sum(bool(b.deferred_evidence) for b in bundles),
        "deferred_files_confirmed_by_content": 0,
        "unresolved_cases": [b.case_id for b in bundles if b.identity.status == "UNRESOLVED"],
        "ambiguous_identity_cases": [
            b.case_id for b in bundles if b.identity.status == "AMBIGUOUS"
        ],
        "potentially_ambiguous_cases": [b.case_id for b in bundles if b.ambiguities],
        "uncertain_intent_cases": [b.case_id for b in bundles if b.intent.decision == "UNCERTAIN"],
        "cases_requiring_additional_interpretation": additional,
        "cases_requiring_additional_interpretation_count": len(additional),
        "prediction_accuracy": "not measured; Phase 2 does not produce state verdicts",
    }
