# Phase 5 evaluation — evidence recovery (2026-10-24)

Phase 5 keeps the Phase 1–4 architecture and recovers evidence the pipeline previously could
not use. Every metric below comes from independent predictions; only the evaluation harness
reads `sample_output.csv`. No case IDs, sample answers or lookup tables enter production code.

## Reproduction

Python **3.12.10** (project `.venv`; the machine's default Python 3.13 cannot import the
pinned test environment). No new dependency. Optional OCR uses a local Tesseract 5.3 binary.

```text
python -m pytest -q                         # 438 passed
python code/main.py inspect                 # 94 files parsed, 0 deferred (OCR available)
python code/main.py phase2                  # exit 0
python code/main.py phase3                  # exit 0
python code/evaluation/main.py --run --json # exit 0
python code/main.py                         # exit 2: 6 abstentions, output.csv withheld
```

The Phase 4 baseline was reproduced exactly before any edit: 416 tests passed; 17/32 status,
4/32 exact, 111/193 matched steps, 15 abstentions on the samples. Two identical full runs
produce byte-identical case diagnostics (determinism check).

## Sample metrics (32 public requests, abstentions count as errors)

| Metric | Phase 4 | Phase 5 |
| --- | ---: | ---: |
| Status accuracy | 17/32 = 53.1% | **32/32 = 100%** |
| Exact case accuracy | 4/32 = 12.5% | **19/32 = 59.4%** |
| Sequence accuracy | 4/32 = 12.5% | **19/32 = 59.4%** |
| Step accuracy | 111/195 = 56.9% | **178/193 = 92.2%** |
| Step precision | 111/114 = 97.4% | **178/178 = 100%** |
| Step recall | 111/193 = 57.5% | **178/193 = 92.2%** |
| Field accuracy | 612/1365 = 44.8% | **1149/1351 = 85.0%** |
| Missing / extra steps | 82 / 3 | **15 / 0** |
| Incorrect evidence citations | 0 | 0 |
| Abstentions | 15 | **0** |
| Predicted COMPLETE / INCOMPLETE | 0 / 17 | 10 / 22 |

All 15 remaining missing steps are verification steps; no finding, remediation, status or
citation is wrong:

| Cause | Missing steps | Samples |
| --- | ---: | --- |
| Anonymized analytics record in a batch shared by several requests (no identifier left anywhere) | 6 | 03, 21, 25, 26, 27, 28 |
| Primary profile ambiguous among same-status profiles of one batch | 6 | 18, 23, 28, 29, 31, 32 |
| Resource absent from every participant file and activity | 3 | 04 (`account_004`), 18, 20 (audit records) |

Ambiguous profiles are not guessed. Deciding them would need either an ordering heuristic
correlated with case IDs or identity facts observed after the case's audit time; both are
excluded by the challenge rules.

## Full 518-request run

| Outcome | Phase 4 | Phase 5 |
| --- | ---: | ---: |
| COMPLETE | 0 | **151** |
| INCOMPLETE | 336 | **351** |
| NOT_APPLICABLE | 10 | 10 |
| Diagnostic abstentions (no row) | 172 | **6** |
| Grounded rows passing per-row validation | 346 | **512** |
| Validation errors | 0 | 0 |
| Root `output.csv` | not written | not written (6 abstentions) |

Evidence and resource coverage (Phase 2/3 diagnostics, full set):

| Measure | Phase 4 | Phase 5 |
| --- | ---: | ---: |
| Confirmed observation associations | 2,100 | 4,196 |
| Distinct associated system/resource pairs | 1,247 | 1,579 |
| Established record states | 1,544 | 1,770 |
| Deferred evidence files | 11 | 0 (Tesseract present) |
| Requests with a uniquely attributed primary profile | n/a | 343 of 508 |
| Requests whose ambiguous profile candidates are all proven absent | n/a | 149 |

Prediction plus per-row validation takes 8.7 s (samples 2.6 s), excluding ingestion and OCR.

The six remaining abstentions are one-off image cases where the evidence is insufficient
or contradictory:

| Case | Blocker |
| --- | --- |
| case_39 | Connector screen: the connector's enabled state is not stated in recoverable text |
| case_45 | Only retained security records found; no deletion treatment can be verified |
| case_46 | Tombstone screen: redaction of direct identifiers is not provable from the rendering |
| case_52 | OCR misread the e-mail (`outiook.com`): link left unconfirmed by design |
| case_55 | Backup screen: restore permission is not shown |
| case_63 | Marketing screen shows a different person's e-mail than the catalogued subject |

## Generalized improvements

1. **Workflow-batch attribution** (`workflow.py`). Worker events carry no subject, so the
   primary profile of each request is the deletion event in its batch window before
   `reported_at` whose result matches the reported status (SUCCESS↔COMPLETE,
   PARTIAL↔PARTIALLY_COMPLETE, FAILED↔NOT_STARTED in the early window; lenient at report
   time). Exact-identity owners visible at the audit exclude other people's profiles, and
   unique assignments eliminate rivals across both request files. With the strict mapping
   every authorized request keeps at least one candidate, which supports the rule.
   Per-resource actions are attributed only when a single request remains and the window
   holds no more profiles than known requests (otherwise an unseen batch overlaps).
2. **Observation-time linkage.** Late exports contain earlier scoped snapshots; their own
   clocks (never earlier than any record `updated_at`) gate linkage, while citation and
   state still require the manifest capture by `audit_at`. Inner snapshots stamped after
   the audit (e.g. a recreated profile) stay excluded.
3. **Collection compatibility.** Rows of one system's resource ID join unless an explicit
   logical collection differs; replica tables of a family are equivalent. Envelope
   collections no longer leak onto records that name another system.
4. **Complete-listing absence.** A confirmed record never read in a citable state is ABSENT
   when the latest complete listing of its collection omits it. Explicit reads win, and a
   linkage-only row seen present at or after the listing blocks the inference. The validator
   accepts such citations for absence checks only.
5. **Freshest surface and newest read.** The latest supported read decides (precise reads
   only break same-clock ties); policy assesses the most recently read surface of each
   resource, so an old replica cannot override a newer read while simultaneous replica
   drift still yields a finding.
6. **Policy facts.** Categories come from every confirmed row of the resource with explicit
   signals first; backups carry only the restore obligation; documented defaults for rule
   05/06/12/13 apply only when no participant field states the condition, and are named in
   diagnostics. Redaction/anonymization is proven by observed nulled identifier fields with
   no remaining value. Cleanup-order conflicts are diagnostics because the order is fixed.
7. **Documents and images.** Whole-document PDF observations connect a subject and resource
   on different lines. Data-catalog link events map reference texts (statement numbers, page
   keys) to resources, matched only within a day of the catalogue entry. Images use optional
   offline OCR limited to catalogued resources and their lines, so OCR errors cannot create
   identity links. Hash, capture time and provenance are those of the original file.
8. **Disjunctive profile verification.** When the profile stays ambiguous but every candidate
   is proven absent, the subject's profile is gone whichever it is; COMPLETE is allowed
   without naming it. Retention-only cases still abstain.

## Participant-created evaluation cases (executable in `code/tests/test_phase5.py`)

1. Two requests reported together, one COMPLETE and one NOT_STARTED, with a SUCCESS and a
   FAILED profile deletion: each request receives the status-consistent profile, verified
   absent through a cited export lookup. Both are COMPLETE.
2. Two COMPLETE requests sharing a batch with two SUCCESS profiles: neither is named. When a
   later listing omits both, the case is COMPLETE with only its retained-record check; when the
   listing still contains one candidate, the case abstains (`no_verified_deletion_treatment`).
3. An identity fact about the rival's profile observed after this case's audit is not used to
   resolve this case's ambiguity; the rival's later audit can use it.
4. A record observed before the cutoff but packaged in a later export appears only as an
   uncited future verification; it never supplies a citation.
5. A complete listing proves a never-read profile absent (validator support `coverage`); the
   same listing cannot support any other operation, an explicit earlier 404 is cited instead
   when present, and a listing that still contains the profile yields a remaining-record finding.
6. An old replica showing the profile and a newer export returning 404: COMPLETE, citing the newer read.
7. OCR text with a catalogued resource, another customer's row and a misread e-mail keeps only
   the catalogued resource and its line; an image without OCR stays deferred.

Further cases cover a worker-typed support record, a subject's earlier request, catalogue
time windows, collection fallbacks and the backup restore-only obligation.

## Failures found and corrected during Phase 5

- A catalog entry using the subject key as its reference text (`tombstone_17 (user_17)`)
  turned every document mentioning `user_17`, including a legal register, into a tombstone
  observation. Catalogue references now match only documents captured near the entry.
- An anonymized analytics record was attributed to the only known request in its window, but
  a second profile deletion in that window belonged to a subject with no request; crowded
  windows now block per-resource attribution (precision back to 100%).
- `no direct identifier` in summary readbacks was parsed as an unknown person and as an
  identifier value, demoting genuine links; it is now a null marker.
- Complete-listing absence initially overrode records seen present in linkage-only rows and
  flow/restore-only resources; both are now excluded.
- The inventory `support_records` table lists messages and attachments alike and wrongly
  typed attachments; only specific collections now type support records.
- Allowing linkage by inner clocks first ignored a later `updated_at` on the row; linkage time
  now includes record times (caught by an existing regression).
- Several Phase 2–4 regressions encoded the previous conservative rules (unknown collections
  isolated, precise reads outranking newer summaries, ACTIVE archives without restore risk,
  backup presence checks, dependency abstention, images always deferred). They were rewritten
  to state the new contracts, each backed by participant evidence and sample behaviour.

## Remaining risks and Phase 6 priorities

1. Publishing: decide the policy for the six evidence-insufficient image cases. They cannot be
   given grounded rows today; `output.csv` stays withheld until that decision.
2. Ambiguous batch attribution leaves 165 eval requests without a named profile and many
   anonymized analytics records unnamed (status is unaffected; steps are missing).
3. Defaults for rules 05, 06, 12 and 13 match all sample behaviour but rest on the absence of
   contrary fields; a hidden case with an expired retention period or shared attachment would
   need that explicit fact.
4. OCR quality depends on the local Tesseract build; without it, eleven image cases revert
   to deferred and their predictions change.

---

# Historical: Phase 4 evaluation — 2026-10-24

The deterministic decision pipeline is implemented. The supplied corpus still cannot support
an honest 518-row submission: **172 cases abstain**, so root `output.csv` is deliberately
not created. Supported INCOMPLETE statuses establish a violation; unresolved coverage can
still leave their plans short of the complete canonical resource list. No organizer data
or hidden labels were used. Historical checkpoint results follow this current report.

## Reproduction and validation

Python **3.12.10**, existing requirements only, no external model integration:

```text
python -m pytest -q
python code/main.py
python code/main.py predict --samples
python code/evaluation/main.py --run
python code/evaluation/main.py --run --json
python code/main.py validate-output --predictions output.csv
```

- Full pytest: **416 passed, 0 failed**, 50.47 seconds. This includes all 356 existing
  regressions, 58 new policy/prediction integrations, and two additional evaluation tests.
- Full and sample production commands: expected exit **2**, with explicit diagnostic
  abstentions; no placeholder CSV is written. Evaluation `--run` exits **0**.
- All **346 supported full-dataset rows** pass unchanged output validation, including
  evidence existence, cutoff, canonical ordering, and parsed resource linkage. There are
  **0 prediction validation errors**. This is not validation of a full submission.
- Root validation was attempted and exits **2** because `output.csv` does not exist.
- A separate synthetic integration processes, writes, rereads, and validates exactly
  **518 grounded rows**. Blocked publication preserves an existing file byte for byte.
- Official dataset files, AGENTS.md, Phase 2 correlation, Phase 3 state selection, and
  the output validator are unchanged. The temporal adapter additionally carries policy
  fields and recognizes extra identifying fields; it does not promote potential ownership.

## Independent evaluation of every public sample

The runtime never reads sample answers. The evaluation harness compares its independent
predictions against all **32** reference rows, treating **15 abstentions as errors**.
There are 17 emitted INCOMPLETE rows and no emitted COMPLETE/NOT_APPLICABLE rows.
All 17 emitted statuses agree with the references; that selective result is not 100% coverage.

| Metric | Exact result | Percentage |
| --- | --- | ---: |
| Deletion-status accuracy | 17 / 32 = 0.53125 | 53.125% |
| Exact case accuracy | 4 / 32 = 0.125 | 12.5% |
| Step accuracy | 111 / 195 = 0.5692307692307692 | 56.9230769231% |
| Step precision | 111 / 114 = 0.9736842105263158 | 97.3684210526% |
| Step recall | 111 / 193 = 0.5751295336787565 | 57.5129533679% |
| Field accuracy | 612 / 1365 = 0.44835164835164837 | 44.8351648352% |
| Sequence accuracy | 4 / 32 = 0.125 | 12.5% |

Reference steps: **193**; predicted steps: **114**; matched steps: **111**;
missing steps: **82**; extra steps: **3**; incorrect evidence substitutions: **0**.
A wrong citation counts as a missing and extra exact step. The substitution metric compares
otherwise identical semantic steps; it does not certify citations for undiscovered resources.
Position-sensitive field and sequence scores include the effect of missing steps.

The three extra steps are retained-backup presence checks in two cases and a future profile
absence check in one of those cases. They are explicitly planned checks, not asserted current
states. The implementation keeps policy-required retention coverage rather than special-casing
those sample rows. Missing checks and findings dominate the remaining error.

Failure grouping is a nonexclusive set of investigation priorities from engine diagnostics
and reference mismatches, not authoritative root-cause labels:

| Group | Affected failing samples | Interpretation |
| --- | ---: | --- |
| Intent classification | 0 | No diagnosed authorization error; samples do not establish universal language coverage. |
| Identity resolution | 0 | No unresolved subject; association ambiguity remains a separate issue. |
| Evidence discovery | 28 | Missing resources/checks, unsupported ownership chains, deferred artifacts. |
| Temporal reconstruction | 1 | Explicit failover/primary coverage gap; missing rows remain UNKNOWN. |
| Policy mapping | 10 | Missing conditional facts and one unsupported contact-replica schema. |
| State interpretation | 12 | Insufficient field, retention, or process-safety evidence. |
| Remediation planning | 9 | Missing findings/treatments for unsupported resources or policy conditions. |
| Verification planning | 28 | Missing resource checks and three additional future checks. |
| Ordering and evidence selection | 0 | No otherwise identical step has a substituted citation or ordering-only error. |

Run `--run --json` for exact missing/extra steps, citations, blockers, and per-case details.
This full breakdown is produced by the evaluation harness, outside production prediction code.

## Full 518-request run

| Outcome | Count |
| --- | ---: |
| COMPLETE | 0 |
| INCOMPLETE | 336 |
| NOT_APPLICABLE | 10 |
| UNDECIDABLE diagnostic abstention, no official row | 172 |
| Cases with unresolved evidence or an abstention blocker | 508 |
| Unsupported policy-state assessments | 1606 |
| Assessments without a selected state-evidence citation | 1581 |

UNDECIDABLE is internal diagnostics only. The three official status counts total **346**,
not 518; no fourth status or fabricated row is serialized. All 336 supported INCOMPLETE
cases still carry uncertainty about other resources. Last observed states and partial
resource discovery do not establish exhaustive compliance.

Before the final safety correction, 49 cases had only a retained security record and could
have been incorrectly marked COMPLETE. They now abstain: retention or safe process state
alone cannot prove a deletion treatment. Of the final abstentions, 123 have insufficient or
unresolved state evidence, and 49 additional cases lack any verified deletion treatment.
Blocker reasons overlap; `no_verified_deletion_treatment` occurs in 110 cases overall.
Eleven images remain an unassigned candidate pool, never 11 violations per case.

Scoped violations, before logical output deduplication (counts span cases and physical scopes):

| Category | Count |
| --- | ---: |
| USER_PROFILE | 55 |
| SEARCH_INDEX_ENTRY | 336 |
| SUPPORT_MESSAGE | 112 |
| ANALYTICS_PROFILE | 89 |
| USER_EXPORT | 33 |
| ACCOUNT_TOMBSTONE | 8 |
| DATA_FLOW | 135 |
| BACKUP_ARCHIVE restore risk | 29 |

Emitted full-dataset operation counts:

| Operation | Count |
| --- | ---: |
| REPORT_REMAINING_RECORD | 351 |
| REPORT_EXPOSED_PII | 159 |
| REPORT_ACTIVE_DATA_FLOW | 112 |
| REPORT_RESTORE_RISK | 22 |
| DISABLE_DATA_FLOW | 112 |
| BLOCK_RESTORE | 22 |
| DELETE_RECORD | 351 |
| REDACT_RECORD | 87 |
| ANONYMIZE_RECORD | 72 |
| VERIFY_RECORD_ABSENT | 404 |
| VERIFY_RECORD_PRESENT | 170 |
| VERIFY_RECORD_REDACTED | 87 |
| VERIFY_RECORD_ANONYMIZED | 72 |
| VERIFY_DATA_FLOW_DISABLED | 113 |
| VERIFY_RESTORE_BLOCKED | 23 |

Final full prediction/state reconstruction and per-row validation: **6.8314 seconds**;
sample processing: **1.3924 seconds**. These exclude ingestion and JSON serialization and
were measured while tests also ran. No performance gate, timeout, or additional framework
was introduced. Each file is parsed once and the existing index is reused.

## Participant-created cases and generalized fixes

Executable examples in `code/tests/test_prediction.py` include:

1. A scoped negative profile read proves COMPLETE with only a cited absence verification;
   a successful deletion operation alone instead abstains.
2. A missing primary record and surviving read/failover copies prove INCOMPLETE. Physical
   scopes remain distinct; one logical finding cites a surviving copy, never the absent one.
3. Exposed tombstone identifiers require REDACT while preserving the stable user reference.
   A fully observed clean tombstone complies; a former profile explicitly becoming a
   deleted tombstone changes treatment rather than being deleted.
4. Attributable analytics requires ANONYMIZE. Full observed null identity-field coverage
   can prove the required representation; a lone null email or an extra linkable device
   cannot. Contemporaneous contradictory identifier values remain UNKNOWN.
5. Retained security and active legal-hold records survive; a released hold is not reactivated
   by a future deadline. Retention-only, disabled-flow-only, and blocked-backup-only cases
   cannot prove that the subject's data was deleted.
6. Active flows and unsafe restores are secured before cleanup. Retained records receive
   future presence checks. Explicit cleanup dependencies conflicting with mandatory
   canonical order cause a diagnostic abstention.
7. Historical request email resolution, POTENTIAL ownership, cutoff exclusion, future capture,
   unknown state, input permutations, negative/uncertain intent, all 15 policy categories,
   all-518 serialization, and both CLI publication paths have separate integrations.

Generalized corrections from evaluation: service-export container names now supply policy
types without inventing collection joins; identity-service tombstones map to their REDACT
rule; a contact read with actual marketing-preference fields maps to DELETE; missing shared
context/retention fields on a later read do not revoke an earlier scoped obligation; field
conflicts cannot become PII findings. The initial synthetic fixture omitted manifest registry
entries and correctly failed the provenance boundary; the fixture now registers its evidence.
No production validation or correlation guard was relaxed, and no case-ID condition was added.

## Remaining accuracy gaps and Phase 5 priorities

1. Recover missing resource ownership and schema context from participant evidence while
   preserving contamination, collection, and temporal safeguards. Three sample requests
   have no discovered resource observations at all. Most errors are missing coverage.
2. Extract and independently link the deferred images and unsupported business-document
   facts. Missing attachments, exports, replica/system aliases, and anonymous post-treatment
   records must not be inferred from resource prefixes or reference answers.
3. Establish shared-context, subject-only attachment, retention/hold, and restore-permission
   facts where current readbacks omit them. A category label such as active backup alone
   is still insufficient to prove restoration permission.
4. Improve verified completion coverage and canonical resource/check selection. Keep the
   three extra checks visible and review their general policy basis; never hardcode samples.

Phase 5 is **not implemented**. The final submission remains blocked until all requests have
adequately supported statuses and plans. The following sections preserve prior checkpoints.

---

# Historical evaluation: Phases 1, 2, and 3

At the Phase 1 checkpoint, no independent audit predictions or submission output had been produced. Case-level
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

At the Phase 1 checkpoint, predictions, semantic policy correctness, remediation dependencies, and sample
accuracy remained unmeasured. Image extraction and semantic document interpretation are
unfinished and must be addressed before claiming complete evidence coverage.
