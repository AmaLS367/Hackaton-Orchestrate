"""Submission use case: best-supported official answer per participant request."""

from ghost_audit.application.submission.evidence import SubmissionEvidence
from ghost_audit.application.submission.records import SubmissionRecords
from ghost_audit.application.submission.workflow import WorkflowAssignment
from ghost_audit.domain.dataset import Dataset
from ghost_audit.domain.models import DeletionRequest
from ghost_audit.domain.output_contract import FINDINGS as FINDING
from ghost_audit.domain.output_contract import (
    OPERATIONS,
    REMEDIATION,
    VERIFICATION,
    DeletionStatus,
    Operation,
    OutputRow,
    OutputStep,
    canonical_steps,
)
from ghost_audit.domain.submission_models import CasePrediction, Resource, ResourceAssessment
from ghost_audit.domain.submission_semantics import prefix


class SubmissionPredictor:
    """Coordinate best-supported official predictions using separate collaborators."""

    def __init__(self, dataset: Dataset) -> None:
        self.evidence = SubmissionEvidence(dataset)
        self.workflow = WorkflowAssignment(self.evidence)
        self.records = SubmissionRecords(self.evidence)

    def resources_for(
        self, request: DeletionRequest, user: str
    ) -> tuple[dict[str, Resource], list[str]]:
        """Collect supported ownership and unique batch assignments, recording ambiguous leads."""
        audit_at = request.audit_at
        resources: dict[str, Resource] = {}
        notes = []

        def add(resource_id, method):
            system = self.evidence.system_of(resource_id)
            if system is None:
                return
            resources.setdefault(resource_id, Resource(resource_id, system)).methods.add(method)

        accounts = self.workflow.account_candidates.get(request.case_id, set())
        batch_account = next(iter(accounts)) if len(accounts) == 1 else None
        for resource_id, owners in self.evidence.explicit.items():
            links = owners.get(user)
            if not links:
                continue
            strong = [at for at, kind in links if kind != "lookup"]
            if prefix(resource_id) == "account" and not strong:
                other = self.workflow.batch_owner.get(resource_id)
                if (
                    other
                    and other != request.case_id
                    or batch_account
                    and batch_account != resource_id
                ):
                    notes.append("ignored_lookup_only_account:" + resource_id)
                    continue
            retained = prefix(resource_id) in {"audit_record", "legal_hold"}
            if (
                not retained
                and all(at < request.requested_at for at, _ in links)
                and not any(
                    request.requested_at <= f.captured_at <= audit_at
                    for f in self.records.facts(resource_id, user)[0]
                )
            ):
                # Seen only before the request: earlier context, not the state the request changed.
                notes.append("pre_request_context_only:" + resource_id)
                continue
            early = any(at <= audit_at for at, _ in links)
            add(resource_id, "explicit_identifier" if early else "explicit_identifier_after_audit")
        if batch_account:
            add(batch_account, "workflow_batch_unique")
        elif accounts:
            notes.append("ambiguous_workflow_account:" + ",".join(sorted(accounts)))
        for resource_id in self.workflow.direct_reports.get(request.case_id, ()):
            report_owners = self.evidence.owners(resource_id, strong=True)
            if not report_owners or user in report_owners:
                add(resource_id, "workflow_direct_report")
        for resource_id in self.workflow.downstream.get(request.case_id, ()):
            add(resource_id, "workflow_batch_downstream")
        ambiguous = self.workflow.downstream_ambiguous.get(request.case_id, set()) - set(resources)
        if ambiguous:
            notes.append("ambiguous_workflow_downstream:" + ",".join(sorted(ambiguous)))
        return resources, notes

    def predict_case(self, request: DeletionRequest) -> CasePrediction:
        """Build one official result while preserving attribution and confidence diagnostics."""
        intent = self.evidence.classifier.classify(request)
        if intent.decision == "NO_DELETE_INTENT":
            return CasePrediction(
                request.case_id,
                OutputRow(case_id=request.case_id, deletion_status="NOT_APPLICABLE", steps=[]),
                None,
                {},
                [],
                [],
            )
        user, identity_note = self.evidence.user_for(request)
        notes = [n for n in (identity_note,) if n]
        if intent.decision != "DELETE_INTENT":
            notes.append("uncertain_intent_treated_as_deletion")
        if user is None:
            raise ValueError(
                f"{request.case_id}: subject cannot be identified from participant data"
            )
        resources, resource_notes = self.resources_for(request, user)
        notes.extend(resource_notes)
        assessments = self._assess_resources(request, user, resources, notes)
        violations = [a for a in assessments if a.verdict == "VIOLATION"]
        low = [a.resource.resource_id for a in assessments if a.verdict == "UNKNOWN"]
        flips = self._ambiguous_status_risks(request, user, resources, notes)
        if flips and not violations:
            notes.append("status_depends_on_ambiguous_attribution:" + ",".join(flips))
            low.extend(flips)
        row = self._build_row(request, assessments, violations)
        return CasePrediction(
            request.case_id,
            row,
            user,
            {a.resource.resource_id: sorted(a.resource.methods) for a in assessments},
            notes,
            low,
        )

    def _assess_resources(
        self, request: DeletionRequest, user: str, resources: dict[str, Resource], notes: list[str]
    ) -> list[ResourceAssessment]:
        audit_at = request.audit_at
        assessments = []
        gathered = {
            r.resource_id: self.records.facts(r.resource_id, user) for r in resources.values()
        }
        case_files = {f.evidence_id for facts, _ in gathered.values() for f in facts}
        for resource in sorted(resources.values(), key=lambda r: (r.system_id, r.resource_id)):
            facts, signals = gathered[resource.resource_id]
            category = self.records.category(resource.resource_id, signals)
            action = self.records.required.get(category)
            if action is None:
                notes.append("unsupported_category:" + resource.resource_id)
                continue
            if action == "DELETE":
                # Snapshot contents prove absence only in a file that captured this case's
                # other records; a file about unrelated subjects is not a full inventory.
                listed = self.records.listing_facts(resource.resource_id, resource.system_id)
                own = [f for f in listed if f.evidence_id in case_files]
                if not own and not facts:
                    own = listed
                    if own:
                        notes.append("absence_from_unlinked_snapshot:" + resource.resource_id)
                facts = facts + own
            # The request is judged on what was observed after it was made, up to audit_at.
            visible = [
                f
                for f in facts
                if request.requested_at <= f.captured_at <= audit_at and f.at <= audit_at
            ]
            verdict, fact = self.records.assess(action, visible)
            assessments.append(ResourceAssessment(resource, category, action, verdict, fact, facts))
        if assessments and all(a.verdict == "UNKNOWN" for a in assessments):
            # Nothing observed since the request: the latest state known by audit_at is the
            # best available evidence of what the request still has to change.
            for a in assessments:
                a.verdict, a.fact = self.records.assess(
                    a.action, [f for f in a.facts if f.captured_at <= audit_at and f.at <= audit_at]
                )
            notes.append("state_from_pre_request_evidence")
        return assessments

    def _ambiguous_status_risks(
        self, request: DeletionRequest, user: str, resources: dict[str, Resource], notes: list[str]
    ) -> list[str]:
        """Keep ambiguous ownership out of steps while exposing possible status flips."""
        audit_at = request.audit_at
        candidates = sorted(
            {
                c
                for n in notes
                if n.startswith("ambiguous_workflow_")
                for c in n.split(":", 1)[1].split(",")
            }
            - set(resources)
        )
        flips = []
        for resource_id in candidates:
            facts, signals = self.records.facts(resource_id, user)
            action = self.records.required.get(self.records.category(resource_id, signals))
            if action is None:
                continue
            visible = [
                f
                for f in facts
                if request.requested_at <= f.captured_at <= audit_at and f.at <= audit_at
            ]
            if self.records.assess(action, visible)[0] == "VIOLATION":
                flips.append(resource_id)
        return flips

    def _build_row(
        self,
        request: DeletionRequest,
        assessments: list[ResourceAssessment],
        violations: list[ResourceAssessment],
    ) -> OutputRow:
        steps = []
        if violations:
            status: DeletionStatus = "INCOMPLETE"
            for assessment in violations:
                resource, action, fact = assessment.resource, assessment.action, assessment.fact
                assert fact is not None, "A violation requires its supporting fact"
                steps.append(self.step(resource, FINDING[action], fact.evidence_id))
                steps.append(self.step(resource, REMEDIATION[action]))
            for assessment in assessments:
                resource, action = assessment.resource, assessment.action
                steps.append(self.step(resource, VERIFICATION[action]))
        else:
            proven = [a for a in assessments if a.verdict == "COMPLIANT"]
            if not proven:
                raise ValueError(f"{request.case_id}: no provable resource state at audit_at")
            status = "COMPLETE"
            for assessment in proven:
                resource, action, fact = assessment.resource, assessment.action, assessment.fact
                assert fact is not None, "A compliant verdict requires its supporting fact"
                steps.append(self.step(resource, VERIFICATION[action], fact.evidence_id))
        row = OutputRow(
            case_id=request.case_id,
            deletion_status=status,
            steps=canonical_steps(self.unique(steps)),
        )
        return row

    @staticmethod
    def unique(steps: list[OutputStep]) -> list[OutputStep]:
        """Keep the first supporting step for each operation/system/resource identity."""
        seen: dict[tuple[str, str, str], OutputStep] = {}
        for s in steps:
            seen.setdefault((s.operation, s.system_id, s.resource_id), s)
        return list(seen.values())

    @staticmethod
    def step(resource: Resource, operation: Operation, evidence_id: str = "") -> OutputStep:
        """Construct an official operation only for an assessment with known system scope."""
        phase, state = OPERATIONS[operation]
        return OutputStep(
            step_no=1,
            phase=phase,
            system_id=resource.system_id,
            resource_id=resource.resource_id,
            operation=operation,
            state=state,
            evidence_id=evidence_id,
        )


def predict_submission(dataset: Dataset) -> list[CasePrediction]:
    """One prediction per request, sorted by case_id. Raises if any case is unsupported."""
    predictor = SubmissionPredictor(dataset)
    cases, unresolved = [], []
    for request in sorted(dataset.requests, key=lambda r: r.case_id):
        try:
            cases.append(predictor.predict_case(request))
        except ValueError as exc:
            unresolved.append(str(exc))
    if unresolved:
        raise ValueError(
            f"{len(unresolved)} cases cannot be represented without unsupported findings or "
            "verifications: " + "; ".join(unresolved)
        )
    return cases


def submission_diagnostics(cases: list[CasePrediction]) -> dict:
    """Identifier-only provenance of every prediction: attribution methods, ambiguity and
    low-confidence resources. Kept separate from the official CSV."""
    from collections import Counter

    statuses: Counter[str] = Counter(c.row.deletion_status for c in cases)
    notes = Counter(n.split(":", 1)[0] for c in cases for n in c.notes)
    methods = Counter(m for c in cases for values in c.resources.values() for m in values)
    return {
        "summary": {
            "cases": len(cases),
            "status_counts": {s: statuses[s] for s in ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")},
            "steps": sum(len(c.row.steps) for c in cases),
            "attribution_methods": dict(sorted(methods.items())),
            "inference_notes": dict(sorted(notes.items())),
            "cases_with_low_confidence_resources": sum(bool(c.low_confidence) for c in cases),
            "status_depends_on_ambiguous_attribution": sorted(
                c.case_id
                for c in cases
                if any(n.startswith("status_depends_on_ambiguous") for n in c.notes)
            ),
        },
        "cases": [
            {
                "case_id": c.case_id,
                "status": c.row.deletion_status,
                "user_id": c.user_id,
                "resources": c.resources,
                "notes": c.notes,
                "low_confidence": sorted(set(c.low_confidence)),
            }
            for c in cases
        ],
    }
