"""Assign uniquely constrained deletion-worker batches; never establish record state."""

from collections import defaultdict

from ghost_audit.application.submission.evidence import SubmissionEvidence
from ghost_audit.domain.models import Activity, DeletionRequest
from ghost_audit.domain.submission_semantics import (
    ACCOUNT_WINDOW,
    DIRECT_REPORT_WINDOW,
    FINAL_RESULT_WINDOW,
    POLICY_ACTION_WINDOW,
    WORKFLOW_RESULT,
    minutes,
    prefix,
)


class WorkflowAssignment:
    """Keep unique batch assignments separate from resource state evidence."""

    def __init__(self, evidence: SubmissionEvidence) -> None:
        """Solve batch candidates once against both participant request files."""
        self.evidence = evidence
        self._index_workflow()

    def _index_workflow(self) -> None:
        """Build constrained assignments; operation success never becomes record state."""
        deleting = [
            r
            for r in self.evidence.requests
            if self.evidence.classifier.classify(r).decision == "DELETE_INTENT"
        ]
        users = {r.case_id: self.evidence.user_for(r)[0] for r in self.evidence.requests}
        self.request_user = users
        worker = [
            a for a in self.evidence.dataset.activities if a.source_system == "deletion_worker"
        ]
        submissions = [a for a in worker if "submitted primary profile" in a.details]
        self.submitted = {a.resource_id for a in submissions}

        def explicit_kinds(r: DeletionRequest) -> set[str]:
            return {
                prefix(res)
                for res, owners in self.evidence.explicit.items()
                if users[r.case_id] in self.evidence.owners(res, r.audit_at, strong=True)
            }

        kinds = {r.case_id: explicit_kinds(r) for r in deleting}
        # 1. Primary profile submissions: one per request, ~1h before reported_at, with the
        # submission result mirroring the reported status. Solved as a constrained matching.
        self._match_accounts(deleting, users, submissions)
        self._match_direct_reports(deleting, worker)
        self._match_downstream(deleting, users, worker, submissions, kinds)

    def _match_accounts(
        self,
        deleting: list[DeletionRequest],
        users: dict[str, str | None],
        submissions: list[Activity],
    ) -> None:
        """Match reported cadence/result to primary submissions, then propagate singletons.

        Independent ownership excludes contradictions. A lookup-only historical key does
        not override the uniquely submitted account, and ambiguous options remain visible."""
        candidates = {}
        for r in deleting:
            options = set()
            for a in submissions:
                lag = minutes(r.reported_at - a.event_time)
                if not (ACCOUNT_WINDOW[0] <= lag <= ACCOUNT_WINDOW[1]):
                    continue
                if a.reported_result != WORKFLOW_RESULT.get(r.reported_status):
                    continue
                owners = self.evidence.owners(a.resource_id, strong=True)
                if owners and users[r.case_id] not in owners:
                    continue  # contradicted by an explicit owner
                options.add(a.resource_id)
            own: set[str] = set()
            user = users[r.case_id]
            for option in options:
                owners_for_resource = self.evidence.explicit.get(option)
                links = (
                    owners_for_resource.get(user, ())
                    if owners_for_resource is not None and user is not None
                    else ()
                )
                if any(kind != "lookup" or at >= r.requested_at for at, kind in links):
                    own.add(option)
            candidates[r.case_id] = own if len(own) == 1 else options
        self._propagate(candidates)
        self.account_candidates = candidates
        # An account submitted in some other request's batch is not this subject's merely
        # because an old lookup by this subject's key touched it.
        self.batch_owner = {next(iter(v)): k for k, v in candidates.items() if len(v) == 1}

    def _match_direct_reports(
        self, deleting: list[DeletionRequest], worker: list[Activity]
    ) -> None:
        """Attribute an explicit target report only when its reporting window is unique."""
        self.direct_reports = defaultdict(set)
        for a in worker:
            if "Target resource:" not in a.details:
                continue
            near = [
                r
                for r in deleting
                if DIRECT_REPORT_WINDOW[0]
                <= minutes(r.reported_at - a.event_time)
                <= DIRECT_REPORT_WINDOW[1]
            ]
            if len(near) == 1:
                self.direct_reports[near[0].case_id].add(a.resource_id)

    def _match_downstream(
        self,
        deleting: list[DeletionRequest],
        users: dict[str, str | None],
        worker: list[Activity],
        submissions: list[Activity],
        kinds: dict[str, set[str]],
    ) -> None:
        """Assign downstream worker actions only to a uniquely compatible batch.

        Explicit owners constrain the batch. Without an owner, an already-owned resource
        of the same kind removes a request from consideration; unresolved overlaps stay
        in diagnostics instead of generating unsupported findings."""
        self.downstream = defaultdict(set)
        self.downstream_operations: defaultdict[str, set[str]] = defaultdict(set)
        self.downstream_ambiguous = defaultdict(set)
        for a in worker:
            if a in submissions or "Target resource:" in a.details:
                continue
            if a.details.startswith("Policy action completed"):
                window = POLICY_ACTION_WINDOW
            elif "final result" in a.details or a.event_type in {
                "CHECK_DATA_FLOW",
                "CHECK_RESTORE_ACCESS",
            }:
                window = FINAL_RESULT_WINDOW
            else:
                continue
            batch = [
                r
                for r in deleting
                if window[0] <= minutes(r.reported_at - a.event_time) <= window[1]
            ]
            owners = self.evidence.owners(a.resource_id, strong=True)
            if owners:
                batch = [r for r in batch if users[r.case_id] in owners]
            else:
                # A request that already owns a record of this kind is not a candidate for
                # an unlabelled one; with no other candidate the record stays unattributed.
                batch = [r for r in batch if prefix(a.resource_id) not in kinds[r.case_id]]
            if len(batch) == 1:
                self.downstream[batch[0].case_id].add(a.resource_id)
                self.downstream_operations[batch[0].case_id].add(a.activity_id)
            else:
                for r in batch:
                    self.downstream_ambiguous[r.case_id].add(a.resource_id)

    @staticmethod
    def _propagate(candidates: dict[str, set[str]]) -> None:
        """Eliminate singleton accounts from other multi-option batches until stable."""
        changed = True
        while changed:
            changed = False
            for case_id, options in candidates.items():
                if len(options) != 1:
                    continue
                (account,) = options
                for other, values in candidates.items():
                    if other != case_id and account in values and len(values) > 1:
                        values.discard(account)
                        changed = True
