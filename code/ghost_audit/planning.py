"""Grounded plans in official canonical order, with explicit dependency conflicts."""

from collections import defaultdict

from .output import OPERATIONS, OutputRow, OutputStep, canonical_steps
from .policy import supported_observations
from .policy_models import CaseDecision

REMEDIATION = {'DELETE': 'DELETE_RECORD', 'REDACT': 'REDACT_RECORD', 'ANONYMIZE': 'ANONYMIZE_RECORD',
               'DISABLE': 'DISABLE_DATA_FLOW', 'BLOCK': 'BLOCK_RESTORE'}
VERIFICATION = {'DELETE': 'VERIFY_RECORD_ABSENT', 'RETAIN': 'VERIFY_RECORD_PRESENT',
                'REDACT': 'VERIFY_RECORD_REDACTED', 'ANONYMIZE': 'VERIFY_RECORD_ANONYMIZED',
                'DISABLE': 'VERIFY_DATA_FLOW_DISABLED', 'BLOCK': 'VERIFY_RESTORE_BLOCKED'}
FINDINGS = {'DELETE': 'REPORT_REMAINING_RECORD', 'REDACT': 'REPORT_EXPOSED_PII',
            'ANONYMIZE': 'REPORT_EXPOSED_PII', 'DISABLE': 'REPORT_ACTIVE_DATA_FLOW', 'BLOCK': 'REPORT_RESTORE_RISK'}


def step(assessment, operation, evidence_id=''):
    phase, state = OPERATIONS[operation]
    return OutputStep(step_no=1, phase=phase, system_id=assessment.scope.system_id,
                      resource_id=assessment.scope.resource_id, operation=operation, state=state, evidence_id=evidence_id)


def deduplicate(steps):
    # Several physical scopes may prove one logical violation. Choose a deterministic
    # citation actually supporting that violation, never one proving a compliant replica.
    result = {}
    for s in sorted(steps, key=lambda s: (s.evidence_id, s.model_dump_json())):
        result.setdefault((s.operation, s.system_id, s.resource_id), s)
    return canonical_steps(list(result.values()))


def dependency_conflicts(bundle, steps):
    positions = {(s.system_id, s.resource_id): i for i, s in enumerate(steps)
                 if s.operation in {'DELETE_RECORD', 'REDACT_RECORD', 'ANONYMIZE_RECORD'}}
    conflicts = []
    for h in bundle.resource_histories:
        target = (h.scope.system_id, h.scope.resource_id)
        for o in supported_observations(h, bundle.audit_at):
            source = o.attributes.get('source_resource_id')
            system = o.attributes.get('source_system_id') or o.attributes.get('source_system')
            if source and not system:
                candidates = [key for key in positions if key[1] == source]
                if len(candidates) == 1:
                    system = candidates[0][0]
                elif len(candidates) > 1:
                    conflicts.append('cleanup_dependency_system_ambiguous:' + source)
            if source and system and target in positions and (system, source) in positions:
                if positions[target] >= positions[(system, source)]:
                    conflicts.append('cleanup_dependency_conflicts_with_official_order:' +
                                     system + ':' + source + '->' + ':'.join(target))
    return sorted(set(conflicts))


def plan_case(bundle, assessments):
    unresolved = sorted(set(reason for a in assessments if a.compliance == 'UNKNOWN' for reason in a.reasons))
    unresolved.extend(sorted({s.reason for s in bundle.unresolved_states
                             if s.reason != 'unassigned_deferred_evidence_requires_interpretation'}))
    if bundle.intent.decision == 'NO_DELETE_INTENT':
        return CaseDecision(case_id=bundle.case_id, decision='NOT_APPLICABLE',
            prediction=OutputRow(case_id=bundle.case_id, deletion_status='NOT_APPLICABLE', steps=[]),
            assessments=[], unresolved=[], blockers=[])
    blockers = []
    if bundle.intent.decision != 'DELETE_INTENT':
        blockers.append('unresolved_deletion_authorization')
    if bundle.identity.status != 'RESOLVED':
        blockers.append('unresolved_subject_identity')
    valid = [a for a in assessments if a.scope.system_id and a.required_action]
    violations = [a for a in valid if a.compliance == 'VIOLATION']
    if not violations:
        # Every confirmed resource must be proven compliant: an UNKNOWN assessment never
        # becomes absence. Potential associations and unassigned files are not the
        # subject's confirmed records and stay diagnostic (see `unresolved`).
        if not valid or any(a.compliance != 'COMPLIANT' for a in assessments):
            blockers.append('insufficient_evidence_for_complete_or_incomplete')
        # Retention or process safety alone never proves deletion. An ambiguous primary
        # profile counts only when every candidate the workflow could have targeted is
        # proven absent; it is then verified, but cannot be named in a step.
        if not any(a.dimension == 'record' and a.required_action in {'DELETE', 'REDACT', 'ANONYMIZE'}
                   and a.compliance == 'COMPLIANT' for a in valid) and not bundle.primary_profile_absence:
            blockers.append('no_verified_deletion_treatment')
    if blockers:
        return CaseDecision(case_id=bundle.case_id, decision='UNDECIDABLE', prediction=None,
                            assessments=assessments, unresolved=sorted(set(unresolved)), blockers=sorted(set(blockers)))
    incomplete = bool(violations)
    steps = []
    for a in violations:
        citation = min(link.evidence_id for link in a.evidence)
        steps.extend([step(a, FINDINGS[a.required_action], citation), step(a, REMEDIATION[a.required_action])])
    groups = defaultdict(list)
    for a in valid:
        groups[(a.scope.system_id, a.scope.resource_id, a.dimension)].append(a)
    for values in groups.values():
        actions = {a.required_action for a in values}
        if len(actions) != 1:
            blockers.append('incompatible_policy_treatments_for_one_output_resource')
            continue
        # Future verification also checks already-compliant retained resources and processes.
        if incomplete:
            steps.append(step(values[0], VERIFICATION[values[0].required_action]))
        elif all(a.compliance == 'COMPLIANT' for a in values):
            # Every physical scope must be compliant before one logical verification is emitted.
            # Its citation proves the named logical state; scope coverage stays in diagnostics.
            citations = [link.evidence_id for a in values for link in a.evidence]
            steps.append(step(values[0], VERIFICATION[values[0].required_action], min(citations)))
    steps = deduplicate(steps)
    # The problem statement fixes the order (operation, system, resource); flows and
    # restores already precede every record change. Explicit source links are recorded.
    unresolved.extend(dependency_conflicts(bundle, steps))
    if blockers:
        return CaseDecision(case_id=bundle.case_id, decision='UNDECIDABLE', prediction=None,
            assessments=assessments, unresolved=sorted(set(unresolved)), blockers=sorted(set(blockers)))
    status = 'INCOMPLETE' if incomplete else 'COMPLETE'
    return CaseDecision(case_id=bundle.case_id, decision=status,
        prediction=OutputRow(case_id=bundle.case_id, deletion_status=status, steps=steps),
        assessments=assessments, unresolved=sorted(set(unresolved)), blockers=[])
