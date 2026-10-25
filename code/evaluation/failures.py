"""Reference comparisons live exclusively in the evaluation harness.

Groups indicate investigation priorities inferred from observed mismatches and engine
diagnostics, not authoritative root causes or organizer truth.
"""

from collections import Counter

GROUPS = (
    "Intent classification",
    "Identity resolution",
    "Evidence discovery",
    "Temporal reconstruction",
    "Policy mapping",
    "State interpretation",
    "Remediation planning",
    "Verification planning",
    "Ordering and evidence selection",
)


def signature(step, *, evidence=True):
    """Compare official semantic step fields with optional citation inclusion."""
    data = step.model_dump()
    return tuple(
        data[k]
        for k in ("phase", "system_id", "resource_id", "operation", "state", "evidence_id")
        if evidence or k != "evidence_id"
    )


def failure_analysis(predictions, references, decisions=()):
    """Report missing, extra and citation-different sample steps without claiming hidden truth."""
    predicted = {p.case_id: p for p in predictions}
    decisions = {d.case_id: d for d in decisions}
    groups: dict[str, list[str]] = {key: [] for key in GROUPS}
    cases = []
    missing_total = extra_total = wrong_evidence_total = 0
    for target in sorted(references, key=lambda r: r.case_id):
        actual = predicted.get(target.case_id)
        if actual == target:
            continue
        steps = actual.steps if actual else []
        expected = Counter(signature(s) for s in target.steps)
        observed = Counter(signature(s) for s in steps)
        missing, extra = expected - observed, observed - expected
        # Match identical semantic steps first; count citation substitutions one-to-one.
        semantic_hits = sum(
            (
                Counter(signature(s, evidence=False) for s in steps)
                & Counter(signature(s, evidence=False) for s in target.steps)
            ).values()
        )
        exact_hits = sum((expected & observed).values())
        wrong_evidence = semantic_hits - exact_hits
        missing_total += sum(missing.values())
        extra_total += sum(extra.values())
        wrong_evidence_total += wrong_evidence
        priority = set()
        decision = decisions.get(target.case_id)
        reasons = decision.unresolved + decision.blockers if decision else []
        if (
            actual
            and (actual.deletion_status == "NOT_APPLICABLE")
            != (target.deletion_status == "NOT_APPLICABLE")
        ) or any("authorization" in r or "intent" in r for r in reasons):
            priority.add("Intent classification")
        if any(r == "unresolved_subject_identity" for r in reasons):
            priority.add("Identity resolution")
        if not actual or missing or any("no_confirmed" in r or "no_resource" in r for r in reasons):
            priority.add("Evidence discovery")
        if any(
            any(word in r for word in ("cutoff", "conflict", "replica", "state_unproven"))
            for r in reasons
        ):
            priority.add("Temporal reconstruction")
        if any("policy_" in r for r in reasons):
            priority.add("Policy mapping")
        if any(
            any(word in r for word in ("coverage", "unproven", "unestablished")) for r in reasons
        ):
            priority.add("State interpretation")
        for phase, group in [
            ("REMEDIATION", "Remediation planning"),
            ("VERIFICATION", "Verification planning"),
        ]:
            if any(key[0] == phase for key in (*missing, *extra)):
                priority.add(group)
        if wrong_evidence or actual and actual.steps != target.steps and not missing and not extra:
            priority.add("Ordering and evidence selection")
        for group in priority:
            groups[group].append(target.case_id)
        cases.append(
            {
                "case_id": target.case_id,
                "expected_status": target.deletion_status,
                "predicted_status": actual.deletion_status if actual else "ABSTAINED",
                "missing_steps": [
                    list(key) for key in sorted(missing) for _ in range(missing[key])
                ],
                "extra_steps": [list(key) for key in sorted(extra) for _ in range(extra[key])],
                "incorrect_evidence_references": wrong_evidence,
                "diagnostic_causes": reasons,
            }
        )
    return {
        "missing_steps": missing_total,
        "extra_steps": extra_total,
        "incorrect_evidence_references": wrong_evidence_total,
        "failure_groups": groups,
        "group_interpretation": "Nonexclusive investigation priorities, not confirmed root causes.",
        "cases": cases,
    }
