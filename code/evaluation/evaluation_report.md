# Offline pipeline evaluation: Phases 1, 2, and 3

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

The stabilized complete suite passes **293 tests, 0 failures**, including all 225 pre-stabilization tests.
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
| Cases with potential associations | 421 | 25 |
| Cases without confirmed associations | 9 | 3 |
| Confirmed observation associations across cases | 2,100 | 122 |
| Distinct confirmed observations | 2,099 | 122 |
| Distinct system/resource pairs | 1,247 | 78 |
| Available unassigned deferred files | 11 | 11 |
| Cases with available unassigned deferred files | 488 | 32 |
| Cases flagged for additional interpretation | 514 | 32 |

All 508 authorized full-dataset requests have at least one confirmed observation association.
The nine full-dataset requests without such associations are non-deletion requests.
The one repeated observation association concerns two requests for the same resolved user;
it does not merge two users. Potential associations coexist with confirmed links and are
excluded from the confirmed resource totals. The CLI lists potentially ambiguous case IDs.

Additional-interpretation flags include unresolved identities, uncertain intent, explicit
ambiguities, missing associations, or an available deferred file pool. Of the 514 flagged
full-dataset cases, 488 have available deferred files. These flags do
**not** establish that any case concerns those images: no image has a confirmed subject or
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
resource-reference hop, and terminal collection for established system/resource/collection scopes. It never
propagates through new subjects, whole-file membership, names, or system IDs alone.

### Phase 2 failures corrected and remaining risks

Critical stabilization against reviewed commit `4ff1455e2ba7959597606d614cc4f3ab30e33d49`:

- P0-01: subject extraction now covers `lookup_key`, `match_key`, nested identity fields,
  and mixed-subject prose. Unknown foreign subjects contaminate the entire visible scoped trace.
  Trace-only candidates stay potential, and only independently confirmed paths can seed further
  expansion. Direct evidence survives contamination elsewhere in the trace. Typed resource names,
  record categories, JSON field names, and integrity hashes are not mistaken for extra people.
- P0-02: automatic joins require known compatible logical collections. Replica physical tables
  and provenance stay separate. Explicit references with reused IDs require unambiguous collection
  scope; repeating the anchor's own ID cannot establish a cross-collection relationship. Foreign
  ownership claims stop propagation through an interval, including anonymous observations between
  a foreign owner's last claim and the subject's subsequent ownership. Future claims remain excluded.
- P1-01: English past-tense negation, French `ne ... plus`, Spanish past negation, contradictory
  clauses, and deletion pending future approval have parameterized regressions. Independent valid
  authorizations continue to pass; ordinary scheduling after an export is not future approval.
- P1-02: an explicit personal deletion history and affirmative residual-data audit request cover
  backups, replicas, archives, search indexes, and restored records in either sentence order.
  Policy questions, third-party history, and negated verification do not authorize this audit.
- P1-03: related references prefer `related_system`; documented `relationship_direction` or
  `direction` values `upstream` / `downstream` select `source_system` / `target_system`. Missing or
  unrecognized directions remain unscoped potential links, retaining their original supporting chain.

The full baseline was reproduced before edits: 518 resolved identities, 508 `DELETE_INTENT`,
10 `NO_DELETE_INTENT`, and 2,857 confirmed observation associations. Identity and intent counts
are unchanged. Comparing evidence ID and locator per case shows **905 formerly confirmed joins
downgraded to potential because collection metadata is missing**, plus **148 newly confirmed
direct associations** where null/redacted subject fields previously caused spurious conflicts.
The resulting total is `2857 - 905 + 148 = 2100`. No formerly confirmed observation disappears
from its case bundle, and distinct system/resource pairs remain 1,247. The sample total changes
from 172 to 122. Cases with confirmed evidence remain 509 overall / 29 samples.

These changes remove unsupported confirmations; they do not establish how many prior links were
actually false positives, nor measure canonical answer accuracy. Missing collection metadata can
suppress genuine associations. Counts are observed diagnostics, never labels or thresholds.

The 68 added regressions cover unknown and mixed trace subjects, independent direct anchors,
future trace conflicts, cross-collection and unknown-collection collisions, physical replicas,
time-dependent ownership changes, directed and ambiguous related resources, repeated anchor IDs,
input-order permutations including complete provenance chains, and the intent cases above.
The complete pytest suite and both Phase 2 CLI runs pass on Python 3.12.10. Phase 1 `inspect`,
`inspect --samples`, and public sample schema validation (`--check-reference`) also pass.
Official datasets and `AGENTS.md` are unchanged. No dependencies, external AI calls, or Phase 3
implementation were added. Identity CSV row locators and expanded diagnostics remain deferred.

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
  unknown systems or logical collections, and ambiguous ownership intervals need additional
  evidence. No prefix-based system guessing occurs. Ownership guards concern association only,
  not a full temporal reconstruction of record state.
- Eleven images remain deferred. Parsed PDF/text lines without explicit identifiers or
  supported links can also remain unassociated. No evidence is invented for missing resources.
- Current/previous alias status is an identity-history fact, not a reconstruction of resource
  state. Resource versions and replicas are preserved for the future temporal engine.

Phase 2 handoff to Phase 3: review potential associations and unknown systems; extract and
correlate deferred document/image facts with their original locators; then design temporal
resource reconstruction over these bundles, keeping claims separate from observed state.
Policy evaluation and remediation planning require their own later implementation and
independent prediction evaluation. The Phase 3 implementation and its measured coverage
are described below; these earlier Phase 2 results remain the regression baseline.

## Phase 3 evaluation

Phase 3 consumes Phase 2 bundles without changing intent, identity, or correlation modules.
It reconstructs resource observations and source scopes, not deletion-policy outcomes. Case-level
deletion-status, step-level, field-level, sequence, and exact-case prediction accuracy remain
**not measured**. No root `output.csv`, policy engine, or remediation plan is generated.

Validation on Python 3.12.10 runs the full pytest suite, Phase 1 `inspect` (full and samples),
sample-reference schema checks, Phase 2 (full, samples, and single case), and Phase 3 (full,
samples, and single case). Phase 2 retains exactly 2,100 / 122 confirmed associations.
The complete suite passes **356 tests, 0 failures**, retaining all 293 Phase 1/2 regressions.
The 63 Phase 3 tests include constructed cases, participant-format parsing, all-518 integration,
serialization round trips, privacy of aggregates, and full/sample/single-case CLI checks.

Measured discovery coverage, per-case resource/source scopes (not unique global resources):

| Metric | 518 requests | 32 sample requests |
| --- | ---: | ---: |
| Authorized deletion intent | 508 | 32 |
| Cases with established record states | 498 | 26 |
| Resource/source scopes | 2,703 | 153 |
| Established record selections (`PROVEN`) | 1,544 | 77 |
| `PRESENT` / `ABSENT` | 1,429 / 113 | 68 / 9 |
| `REDACTED` / `ANONYMIZED` | 2 / 0 | 0 / 0 |
| `UNKNOWN` record selections | 1,159 | 76 |
| Record selections `CLAIM_ONLY` / `CONFLICTED` | 0 / 0 | 0 / 0 |
| Observations `PROVEN` / `CLAIM_ONLY` / `UNKNOWN` | 1,557 / 13 / 1,133 | 79 / 2 / 72 |
| Conflicting observation citations | 0 | 0 |
| Supported replica disagreements | 0 | 0 |
| Replica coverage gaps | 0 | 1 |
| Active / inactive flows | 135 / 39 | 6 / 3 |
| Allowed / blocked restore permissions | 29 / 39 | 2 / 3 |
| Authorized cases with incomplete evidence | 504 | 32 |

Measured final full Phase 3 CLI time was 8.92 seconds, including ingestion and correlation; samples
took 2.97 seconds on this development machine. Timing is descriptive, not a performance gate.
The lack of proven conflicts in this corpus is not evidence of complete deletion. Conservative
Phase 2 associations leave many replica and anonymous-record candidates potential. The sample
gap is a known sibling primary table without a confirmed row, alongside a populated failover
table; it remains unknown because export completeness is not established.

Participant-created temporal evaluation cases (executable in `code/tests/test_temporal.py`):

1. Present snapshot, scoped 404, then recreated record: history stays `PRESENT -> ABSENT ->
   PRESENT`; selecting an earlier cutoff excludes both future observations and late captures.
2. Older snapshot packaged after a newer resource readback: chronology uses the scoped snapshot
   clock, not export time or row `updated_at`; the newer authoritative read establishes absence.
3. Successful deletion claim with a present snapshot: the claim is retained but cannot erase
   direct evidence. A summary label likewise cannot override precise contents.
4. Primary absent, failover/read replica present: independent scopes yield a supported state
   disagreement. Missing rows instead produce unknown coverage; regional/reporting scopes,
   explicit generic-table logical collections, reused IDs across collections, and field drift
   have separate tests. Different observation times are marked as possible temporal skew.
5. Redacted tombstone, analytics with all-null fields, analytics with direct identifiers, and
   retained security reference: exact field representations survive. Nulls do not establish
   anonymization, and a stable reference does not imply a policy violation.
6. Connector enabled/disabled after account absence, and present archive with allowed/blocked
   restoration: independent state dimensions survive, including SQLite integer booleans.
7. Same-time contradictory readbacks remain unknown/conflicted. A later resolution does not
   delete historical conflict evidence. Reordering input observations preserves the full result.
8. Potential ownership, missing/future anchors, unregistered evidence, failed reads, negative
   searches lacking resource scope, cache misses, and unavailable downloads cannot establish
   definitive absence or ownership.

Failures found and corrections during implementation:

- SQLite uses integer boolean values; adapters explicitly decode 0/1 while preserving originals.
- Service-export JSON can establish presence without HTTP fields; scoped observed contents and
  identifiers are handled separately from operation claims.
- Missing logical collections initially allowed source-local joining; these observations are now
  isolated, while known SQL schema relationships retain safe cross-table comparison.
- Earlier simultaneous conflicts could disappear from conflict diagnostics after a later read;
  histories now retain the conflicting citations and reasons independently of latest selections.
- The unknown-collection regression fixture originally reused an identical file/line locator for
  two different lines; it now uses distinct source locators to exercise the intended boundary.
- A mismatched search document could fall through to generic presence inference; search responses
  now require their own resource-scoped semantics. HTTP 200 with zero rows establishes an empty
  result, not contradictory presence. Restore-configuration conflicts remain separate from archive
  existence, and simultaneous field differences retain their own conflict evidence.

Remaining uncertainty: eleven images remain deferred; unsupported PDF/text semantics, missing
logical collections, bounded correlation, and potential ownership can leave real resources
undiscovered or unresolved. Last observed state does not prove continuous state through `audit_at`.
Null-only analytics records intentionally remain present with field evidence; irreversible
anonymization has not been independently established. Unspecified service origins/regions are
independent surfaces, not assumed SQL replicas. Future extraction must preserve these boundaries.

Phase 4 should consume `TemporalStateEngine(phase2.index).analyze(case_bundle)`, apply policy to
the field evidence and independent record/flow/restore selections, and explicitly handle unknown
or conflicted support. Preserve resource collection identity and ownership chains in citations.
Implement remediation ordering and output generation separately; do not use these diagnostic
coverage numbers as labels, accuracy claims, or automatic completion gates.

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
