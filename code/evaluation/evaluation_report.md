# Offline pipeline evaluation: Phases 1 and 2

No independent audit predictions or submission output have been produced. Case-level
deletion-status accuracy, step accuracy, field accuracy, sequence accuracy, and exact-case
accuracy on the public samples are **not yet measured**. These metrics must be reported
from independent engine predictions in a later phase. Hidden evaluation labels are not used.

The provided 32 sample answers pass strict schema validation and exact sample request
coverage. This is a reference-contract check, not 100% prediction accuracy.

Validation used Python 3.12 with Pydantic v2, pytest, and pypdf. The complete corpus loads
518 evaluation requests and 94 evidence files: 83 parsed and 11 images deferred. It yields
9,690 indexed observations, including identity history and activity claims. SHA-256 checks
confirm all 103 dataset files remain unchanged. No root prediction output was created.
The Phase 1 baseline `python -m pytest -q` run passed **96 tests**.

## Phase 2 evaluation

Phase 2 adds deterministic intent classification, historical identity resolution, bounded
evidence correlation, and strict case evidence bundles. It does not predict deletion states,
apply policy, plan remediation, or generate `output.csv`. All accuracy metrics above remain
unmeasured. Sample intent tests interpret request text directly; sample answers are not used
by any production component.

Validation on Python 3.12.10:

```text
python -m pytest -q
python code/main.py inspect
python code/main.py inspect --samples
python code/evaluation/main.py --check-reference
python code/main.py phase2
python code/main.py phase2 --samples
python code/main.py phase2 --samples --case-id case_02
```

The complete suite passes **225 tests, 0 failures**, including all 96 existing tests.
Inspection retains 9,690 observations, 83 parsed files, and 11 deferred images. Reference
validation still accepts exactly 32 sample rows without claiming prediction accuracy.
The single-case diagnostic emits a typed bundle, including cases without supported evidence
associations. Aggregate commands emit counts and case IDs without raw personal information.

Full-dataset and sample diagnostics:

| Metric | 518 requests | 32 sample requests |
| --- | ---: | ---: |
| DELETE_INTENT | 508 | 32 |
| NO_DELETE_INTENT | 10 | 0 |
| UNCERTAIN | 0 | 0 |
| Resolved identities | 518 | 32 |
| Ambiguous / unresolved identities | 0 / 0 | 0 / 0 |
| Cases with confirmed evidence associations | 509 | 29 |
| Cases with potential associations / explicit ambiguities | 69 | 4 |
| Cases without confirmed associations | 9 | 3 |
| Confirmed observation associations across cases | 2,857 | 172 |
| Distinct confirmed observations | 2,856 | 172 |
| Distinct system/resource pairs | 1,247 | 78 |
| Available unassigned deferred files | 11 | 11 |
| Cases with available unassigned deferred files | 488 | 32 |
| Cases flagged for additional interpretation | 488 | 32 |

All 508 authorized full-dataset requests have at least one confirmed observation association.
The nine full-dataset requests without such associations are non-deletion requests.
The one repeated observation association concerns two requests for the same resolved user;
it does not merge two users. Potential associations coexist with confirmed links and are
excluded from the confirmed resource totals. The CLI lists potentially ambiguous case IDs.

Additional-interpretation flags include unresolved identities, uncertain intent, explicit
ambiguities, missing associations, or an available deferred file pool. The 488 flags do
**not** imply that 488 cases concern those images: no image has a confirmed subject or
interpreted content. No retrieval statistic measures record-discovery completeness or
deletion-state accuracy.

### Phase 2 regression cases and architectural decisions

- `test_intent.py` exercises account/personal-data deletion, prior-request verification,
  English/Spanish/French and recurring Portuguese/Japanese/Korean expressions, negation,
  cancellation, marketing scope, access/export/correction/support, quoted/hypothetical
  instructions, conflicting clauses, and fallback recommendations.
- `test_identity.py` constructs consecutive email changes, old/new phone and supplied-hash
  aliases, timestamped provenance, unknown emails, collisions, discontinuous histories,
  simultaneous conflicting updates, future changes, and future snapshots. Indexes are built
  once; original values and known interval boundaries are retained. A snapshot cannot prove
  that its values existed earlier. Names never resolve identity, and no hash is derived.
- `test_correlation.py` constructs direct identifiers, historical aliases, scoped two-event
  traces, trace reuse, JSON/SQL rows and replicas, unknown systems, foreign subjects, similar
  identifiers, future/untimed observations, explicit resource references, terminal expansion,
  and deferred images. Every confirmed association retains its observation locator and chain.
  Multiple retrieval paths deduplicate associations without dropping versions or replicas.
- `test_phase2.py` processes all 518 requests and the 32 public sample requests, validates
  cutoffs and complete supporting chains, round-trips typed bundles, verifies deterministic
  output and no analysis-time file reads, and exercises CLI diagnostics. Source observations
  and resource metadata are reused from Phase 1. No new dependency or external AI call is needed.

The implementation separates identity association from state interpretation. A resource link
proves an association only; activity results and negative lookup claims remain source payloads.
Expansion is limited to exact identity anchors, one scoped trace hop, one supported explicit
resource-reference hop, and terminal collection for established system/resource pairs. It never
propagates through new subjects, whole-file membership, names, or system IDs alone.

### Phase 2 failures corrected and remaining risks

Early tests exposed Unicode decomposition breaking Korean phrase matching and a missing
remaining-personal-data expression. Normalization now recomposes Hangul, and action/object
rules cover those requests. Additional regressions guard cancellation, negated desire,
marketing-only deletion, hypothetical questions, multiple subjects in one record, and
unrecognized subject references. Conflicting aliases and trace reuse remain potential
associations rather than becoming ownership proof.

Remaining limitations:

- Rules provide practical language coverage, not a general semantic parser. Unusual idioms,
  indirect speech, or untested negation scope can still be misclassified; unmatched requests
  stay `UNCERTAIN`. Rule confidence is not measured statistical accuracy.
- Historical resolution uses only visible facts. Missing earlier snapshots/history can cause
  unresolved identities or unknown intervals. Reassigned/shared aliases and mixed-subject
  records are handled conservatively and can suppress otherwise valid evidence links.
- Longer relationship chains, unscoped resource references, unsupported free-text links,
  and unknown systems need additional evidence. No prefix-based system guessing occurs.
- Eleven images remain deferred. Parsed PDF/text lines without explicit identifiers or
  supported links can also remain unassociated. No evidence is invented for missing resources.
- Current/previous alias status is an identity-history fact, not a reconstruction of resource
  state. Resource versions and replicas are preserved for the future temporal engine.

Preparation for Phase 3: review potential associations and unknown systems; extract and
correlate deferred document/image facts with their original locators; then design temporal
resource reconstruction over these bundles, keeping claims separate from observed state.
Policy evaluation and remediation planning require their own later implementation and
independent prediction evaluation. Phase 3 has not been implemented here.

## Local metric definitions

The testing-only scorer evaluates every reference case, including missing predictions:

- Status accuracy: matching deletion statuses / reference cases.
- Step accuracy: multiset matches of six step fields excluding `step_no`, divided by the
  sum over cases of `max(predicted step count, reference step count)`.
- Step precision and recall: the same matched-step count divided by predicted and
  reference step counts, respectively.
- Field accuracy: matching fields in position-aligned steps / seven times the sum of
  maximum step counts. Missing and extra steps contribute seven incorrect fields each.
- Sequence accuracy: cases whose complete ordered step arrays match / reference cases.
- Exact-case accuracy: cases whose status and ordered steps match / reference cases.

When no steps exist on either side, step/field metrics equal one only if every reference
case was supplied. Otherwise a zero denominator scores zero. Unknown and duplicate case
IDs are rejected. These transparent local metrics do not claim to reproduce the hidden grader.

## Participant-created evaluation cases

These fictional cases are executable in `code/tests/test_evaluation.py`; their constructed
answers test the scorer, not the unimplemented audit engine:

1. `fictional_export_only`: a valid NOT_APPLICABLE row with no steps. Matching it yields
   status, step, and sequence accuracy of 1. Output-model tests reject nonempty steps.
2. `fictional_deletion`, incorrect citation: one COMPLETE verification has the correct
   resource and operation but cites `wrong_file`. Status accuracy is 1, field accuracy
   is 6/7, and step, sequence, and exact-case accuracy are 0.
3. `fictional_deletion`, missing prediction: no row is supplied for a reference case.
   Missing-case count is 1; status, step, and field accuracy are 0. Nothing is filled in.

Additional temporal/provenance cases cover nested future observations, independent sibling
snapshot scopes, offset normalization, business deadlines, and log trace collisions. SQL
tests cover empty primary tables alongside populated replicas, embedded JSON, snapshot
scope times, and blocked external database/extension operations. PDF tests cover both
extractable text and blank pages requiring OCR. The full participant corpus is ingested
and indexed in integration tests; repeated case lookups are checked to perform no file I/O.

## Failures found and improvements

- Initial restricted SQL execution rejected indexes created by the supplied snapshots.
  The in-memory authorizer now permits table/index construction and reindexing, while
  continuing to reject ATTACH, extension loading, writable schema, and virtual tables.
- A test helper raised KeyError before testing an unknown operation. It now passes the
  invalid value to Pydantic so rejection is exercised at the actual schema boundary.
- Scoped extraction keeps future sibling snapshots from delaying unrelated records;
  future record observations cannot borrow an earlier envelope as a valid citation.

All predictions, semantic policy correctness, remediation dependencies, and final sample
accuracy remain unmeasured. Image extraction and semantic document interpretation are
unfinished and must be addressed before claiming complete evidence coverage.
