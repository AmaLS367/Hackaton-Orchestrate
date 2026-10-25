# Evaluation report

## Current accepted release

Full participant dataset (518 requests), submission predictor at commit `bf707f8` and every
later commit: **154 COMPLETE / 354 INCOMPLETE / 10 NOT_APPLICABLE, 3,067 steps**, root
`output.csv` SHA-256 `1bc68692b30cfc7d23efb502c8ad6ba03bfecf75452415d11eae0d4639c3666c`.
Public-sample metrics are identical to the tables below (status 32/32, exact/sequence 21/32,
step precision 100%, recall 93.782%, 12 missing and 0 extra steps). The strict engine is
unchanged: 364 grounded predictions, 154 abstentions, publication exits 2.

| Release stage | Commit | COMPLETE / INCOMPLETE / NOT_APPLICABLE | Steps |
| --- | --- | ---: | ---: |
| Original submission baseline | `4476d26` | 152 / 356 / 10 | 3,071 |
| First temporal correctness fix | `2d85859` | 154 / 354 / 10 | 3,067 |
| Policy cutoff fix | `59ba4a1` | 154 / 354 / 10 | 3,067 |
| Support-category fallback | `bf707f8` | 154 / 354 / 10 | 3,067 |
| **Current accepted release** | `bf707f8` and later | **154 / 354 / 10** | **3,067** |

Full hashes and per-stage changes are in `docs/baseline.md`; case-level differentials are in
`policy_cutoff_differential.md` and `support_inference_differential.md`. The dated rounds
below keep the figures measured at the time. Full-dataset counts of 152 / 356 and 3,071 steps
in them belong to the original submission baseline `4476d26`, not to the current release.

## Submission round — 2026-10-25 (original submission baseline)

**Submission-ready.** A separate submission predictor produces a validated 518-row root
`output.csv`; the strict audit engine is unchanged and kept as `--strict` plus diagnostics.
Base commit `122b834`; tests 491 → **499 passing** (8 added in `code/tests/e2e/test_submission.py`).

### Metrics

| Metric (32 public samples) | Strict engine | Submission predictor |
| --- | ---: | ---: |
| Predicted cases | 21/32 | 32/32 |
| Case-level status accuracy | 65.625% | **100%** |
| Step-level accuracy | 61.140% | **93.782%** |
| Step precision | 100% | **100%** |
| Step recall | 61.140% | **93.782%** |
| Field-level accuracy | 46.928% | **87.935%** |
| Sequence accuracy | 18.750% | **65.625%** |
| Exact cases | 6/32 | **21/32** |
| Missing / extra steps | 75 / 0 | **12 / 0** |
| Incorrect evidence references | 0 | 0 |

| Full dataset (518 requests), baseline `4476d26` | Strict engine | Submission predictor |
| --- | ---: | ---: |
| Predictions | 364 | **518** |
| COMPLETE / INCOMPLETE / NOT_APPLICABLE | 22 / 332 / 10 | 152 / 356 / 10 |
| Abstentions | 154 | 0 |
| Steps | n/a | 3,071 |

On all 364 cases the strict engine predicts, the submission predictor gives the same status
and contains every strict step (zero strict-only steps). Two full runs are byte-identical;
`validate-output` accepts all 518 rows with 0 citations of unknown support.

### What changed (failures found and improvements made)

1. **Account association (127 ASSOCIATE failures).** The deletion worker submits one
   primary profile per request 45-75 minutes before `reported_at`, and its reported result
   mirrors `reported_status` (COMPLETE/SUCCESS, PARTIALLY_COMPLETE/PARTIAL,
   NOT_STARTED/FAILED); all 24 generated public samples fit. This is solved as a constrained
   matching: explicit owners veto candidates, a post-request lookup by the subject's key
   settles a request, and settled accounts are removed from other candidates. 392 accounts
   are uniquely attributed; 104 requests keep 2-3 viable candidates and get **no** account
   step. Within-batch time order was tested against explicitly linked batches and is
   uninformative (23 agree, 23 disagree), so it is not used.
2. **Downstream workflow resources.** "Policy action completed" (4-35 min before
   `reported_at`) and final results/status checks (30-125 min after) attribute 753
   resources when exactly one request of the batch lacks an explicitly owned record of that
   kind; otherwise they stay unattributed (211 requests carry such candidates).
3. **Identifiers.** Historical emails appear as SHA-256 hashes (sample case_12); hashes of
   every current and historical email are identifiers. Full names count only if no other
   subject ever used them. A lookup by key that found nothing does not establish ownership.
4. **Policy (26 APPLY_POLICY failures).** Required actions are read from
   `deletion_rules.csv`; a source-declared `record_type` is authoritative. Support records
   with a file, `ticket_attachment` storage, an attachment PII scan, a PDF rendering or an
   "attachment belongs only to" catalogue link are attachments (DELETE); conversations are
   REDACT. A stable internal reference is allowed under REDACT and tombstones but not under
   ANONYMIZE. A message body containing the subject's email or name exposes the subject.
   Backup archive existence and restore permission are separate; a restorable archive is a
   REPORT_RESTORE_RISK/BLOCK_RESTORE. Console screens state connector status in words
   ("Healthy", "Continuous sync" means active).
5. **State and coverage (40 unlinked readbacks, 30 late-evidence cases).** State is taken
   from the latest evidence file captured between `requested_at` and `audit_at` (every
   public sample citation lies in that window); any violating replica in that file wins.
   SQL snapshot tables and JSON collection snapshots are point-in-time contents, so
   omission proves absence, but only in a file that also captured the case's other records
   (a later unrelated inventory did not override a failover-replica copy in sample
   case_05). Records seen only before the request are earlier context and are dropped
   (retained audit records excepted).
6. **Publication.** `main.py` writes the submission CSV by default; `--strict` keeps the
   abstaining rule. Unsupported cases block publication and are named; none remain.

### Inference assumptions (also in `submission_diagnostics.json`)

- Workflow cadence and result/status mirroring identify a request's batch submission.
- Ownership links may come from evidence captured after `audit_at` (224 resources). Such
  evidence is never cited and never decides a state; it only adds a future verification
  step to an INCOMPLETE plan (public sample case_09 expects this for a retained audit
  record).
- 25 accounts with no direct readback are verified absent from a snapshot that does not
  also contain the case's other records (`absence_from_unlinked_snapshot`).

### Low-confidence cases and remaining gaps

- 104 requests have ambiguous primary-profile candidates; 211 have ambiguous downstream
  candidates. Only `case_369` would change status under some viable assignment.
- 138 requests contain at least one attributed resource whose state is not provable in the
  request window (verified as future work only).
- Sample misses (12 steps): 7 ambiguous anonymized analytics records, 3 ambiguous
  accounts, 2 audit records absent from all participant data, 1 hand-written account with
  no workflow or evidence link.

### Additional evaluation cases (created by the team)

`code/tests/e2e/test_submission.py` adds regression cases built for this pathway: an old
lookup by the subject's key touching another request's account must not override the
request's own batch submission; batch candidates with no distinguishing evidence are never
attributed; a replica copy in the case's own file outranks a later unrelated inventory; a
stable reference is allowed under redaction while a message body containing the subject's
email is exposure. The 24 adversarial synthetic cases below still run against the strict
engine.

## Recovery round (fix rounds 1–3) — 2026-10-25

**Still not submission-ready.** 518 requests processed; 364 grounded predictions
(22 COMPLETE, 332 INCOMPLETE, 10 NOT_APPLICABLE) and 154 abstentions. Publication
exits 2 and writes no root `output.csv`. Base commit `2faccc2`; tests 465 → **491 passing**.

### Before / after

| Metric | Phase 6 (2faccc2) | This round |
| --- | ---: | ---: |
| Sample predicted cases | 21/32 | 21/32 |
| Sample status accuracy | 65.625% | 65.625% |
| Sample exact cases | 6/32 | 6/32 |
| Sample step precision | 100% | 100% |
| Sample step recall | 61.658% | 61.140% |
| Sample field accuracy | 47.446% | 46.928% |
| Sample sequence accuracy | 18.750% | 18.750% |
| Sample missing / extra steps | 74 / 0 | 75 / 0 |
| Full COMPLETE / INCOMPLETE / NOT_APPLICABLE | 8 / 332 / 10 | 22 / 332 / 10 |
| Full predictions (coverage) | 350 (67.57%) | 364 (70.27%) |
| Full abstentions | 168 | 154 |
| Confirmed associations (Phase 2) | 4020 | 3020 |
| Distinct confirmed resources (Phase 2) | 1435 | 1247 |
| Cases with POTENTIAL associations | 143 | 174 |
| Resource scopes (Phase 3) | 3268 | 2665 |
| Scopes with established record state | 1562 | 1553 |
| Scopes with unknown record state | 1706 | 1112 |

### Workstream A — temporal availability and diagnostics

*A1.* The correlator, workflow pins and temporal engine counted an ownership fact from its
internal source clock even when the file carrying it was captured after `audit_at`
(`linkage_time`). The official contract decides each case only from information
available at its cutoff, so retrospective attribution is **not** justified. A new
`known_at` (latest of observed, effective/record, captured/packaging and catalogue-link
clocks) now gates linkage exactly like citation; `time_profile` exposes all four clocks.
Catalogue-derived document references carry a `catalogued_at` source timestamp, so a
catalogue link made after the audit cannot reveal an earlier document's resource.

Effects, all explained: 1000 late-file associations and 603 late-only scopes disappeared.
14 cases became **COMPLETE** (`case_79`, `case_80`, `case_113`, `case_117`, `case_121`,
`case_164`, `case_167`, `case_170`, `case_323`, `case_327`, `case_374`, `case_375`,
`case_378`, `case_380`): each has a pre-audit exact readback proving the account absent
and a retained audit record, and was blocked only by UNKNOWN scopes from files captured
after its audit. 47 INCOMPLETE plans each lost one future verification (46 account
`VERIFY_RECORD_ABSENT`, one legal-hold `VERIFY_RECORD_PRESENT` in `case_432`): the only link
to the subject was a post-audit export (example: `case_09`'s `account_3960` is linked only
by a log exported 2026-09-18, after its 2026-09-16 audit). The sample reference contains
that step, so sample recall fell by one step; it is the contract-required loss. No status
changed and no step was added outside those 14 cases.

*A2.* `ghost_audit/abstention.py` writes one identifier-only record per abstention
(`code/evaluation/abstention_diagnostics.json`, byte-identical across runs, no emails,
phones, hashes or text). Root causes (overlapping, not additive), before → after:

| Root cause (stage) | Before | After |
| --- | ---: | ---: |
| policy_condition_missing (APPLY_POLICY) | 139 | 99 |
| account_ownership_unproven (ASSOCIATE) | 70 | 85 |
| primary_profile_candidates_ambiguous (ASSOCIATE) | 54 | 62 |
| readback_exists_but_unlinked (ASSOCIATE) | 34 | 40 |
| readback_uninterpreted (INTERPRET; late-capture scopes) | 67 | 1 |
| state_evidence_outside_audit_cutoff (INTERPRET) | 15 | 30 |
| no_state_readback / operation_claims_only (INTERPRET) | 2 / 1 | 2 / 1 |

| Earliest failing stage | Before | After |
| --- | ---: | ---: |
| ASSOCIATE | 112 | 127 |
| INTERPRET | 36 | 1 |
| APPLY_POLICY | 20 | 26 |
| EXTRACT / PLAN / VALIDATE | 0 | 0 |

Account attribution of the 154 abstentions: 34 confirmed, 54 single workflow candidate,
60 ambiguous workflow candidates, 6 no account reference. 42 cases have unlinked readbacks
(a provable state for a resource with no subject link); 66 have subject evidence available
only after their audit; 99 lack a policy condition.

### Workstream B — associations

Measured first: across all authorized cases, 149 associations are POTENTIAL; 145 are
deletion-worker seeds, 2 are an earlier request's evidence and 2 unsupported subject
references. None of the 145 seeds has an independent, pre-audit anchor (exact identifier,
scoped trace, explicit reference, catalogue link): 119 appear in no evidence file at all
and 26 only in readbacks whose identifiers are already null. A resource-centric second
pass would therefore confirm nothing, so none was added; candidates stay POTENTIAL and
are reported as `readback_exists_but_unlinked` or `account_ownership_unproven`.
**Newly confirmed associations: 0. Removed: 1000 (post-audit).**

*B3.* PDF resources inherited identifiers from the whole document. `section_text` now
scopes each resource to its section (a page headed "Continued" extends the previous one)
and narrows a section naming several subjects to the lines naming the resource. Current
participant PDFs are single-subject per section, so no prediction changed; the test suite
pins mixed sections and multi-subject registers.

### Workstream C — states and coverage

*C1.* After A1, one abstention fails first at INTERPRET and four INTERPRET causes remain
besides the 30 cases whose subject evidence exists only after their audit. Missing
deletion treatment is ownership (ASSOCIATE) or policy conditions (APPLY_POLICY), not
unreadable or misscoped state.
*C2.* Listings are explicit `Listing` records (system, logical collection, physical table,
observed time, filter scope, truncation, proof provenance). No participant file asserts
completeness; the 47 unresolved resources with any listing all lack a completeness proof,
and 324 have no known collection (workflow candidates). Absence-by-omission stays disabled
for real data; the validator's semantics are unchanged.
*C3.* A 404/NOT_FOUND/zero-row read now proves absence only when it names the resource and
declares no subject/collection `query_scope` or filter. All participant negatives already
name their resource, so no state changed.
*C4.* Replica scopes remain independent; tests pin a newer primary 404 beside a surviving
failover row (still a finding) and a replica gap that is never absence.

### Tests added (`code/tests/test_recovery.py`, 26 instances)

Late catalogue link; late document with earlier source clock; email reassigned between
users; legitimate historical alias with audit origin; interleaved multi-user batch;
ownership change over time; mixed-subject PDF sections and registers; cross-collection ID
collision; scoped trace with a foreign unknown subject; direct anchor surviving unrelated
ambiguity; exact 404; subject-scoped/filtered empty reads; read naming no resource;
complete listing; paginated/truncated/filtered listings; SQL replica coverage gap; newer
primary absence plus surviving replica; valid anonymization; partial redaction UNKNOWN;
future readback excluded; deterministic identifier-only diagnostics; and a participant-
style end-to-end run (CSV + log + late JSON bundle → COMPLETE at the cutoff, INCOMPLETE
once the bundle is available). Two Phase 5/temporal tests that asserted retrospective
linkage were rewritten to assert the stricter contract; no safety test was weakened.

### Remaining blockers and next rounds

- **Policy round:** 99 abstentions lack a supplied condition, mostly security-audit
  retention without `retention_until` and support conversations without `shared_context`.
- **Ownership:** 145 cases depend on workflow candidates that no participant evidence
  links to the subject. Under the current rules they stay unproven; a decision on
  whether request-batch attribution can ever count is needed before planning work.
- **Planning:** the official order versus dependency checks are unchanged this round.

## Phase 6 evaluation — 2026-10-24 (history)

## Release verdict

**Not submission-ready.** All 518 requests were processed, but 168 remain unsupported.
No root `output.csv` exists. The publication command exits **2** without creating or
replacing the CSV. There is no fourth submission status; abstentions exist only in
diagnostics. `dataset/output.csv` remains the original blank template.

The Phase 5 baseline was reproduced before editing: commit
`7fd4c9b97b47b75e6559688359ea45a06ba2ae7a`, local uv commit
`586ce05337bd6a669340ffd346d3db79b2f8d415`, 438 passing tests, 512 predicted rows and
six abstentions. The uv commit was pushed by ordinary fast-forward. No baseline count
was used as a production target. The Phase 6 test suite has **465 passing tests**.

## Public sample measurements

The evaluation harness alone reads `sample_output.csv`. Missing predictions count as
errors. Metrics are local sample measurements, **not hidden-test accuracy**.

| Metric | Reproduced Phase 5 | Final Phase 6 |
| --- | ---: | ---: |
| Predicted sample cases | 32/32 | 21/32 |
| Status accuracy | 100% | 65.625000% |
| Exact case accuracy | 19/32 (59.375%) | 6/32 (18.750%) |
| Step accuracy | 92.227979% | 61.658031% |
| Step precision | 100% | 100.000% |
| Step recall | 92.227979% | 61.658031% |
| Field accuracy | 85.048113% | 47.446336% |
| Sequence accuracy | 59.375% | 18.750% |
| Missing steps | 15 | 74 |
| Extra steps | 0 | 0 |
| Incorrect evidence references in scored sample steps | 0 | 0 |
| Sample abstentions | 0 | 11 |

There are 193 reference steps; Phase 6 emits 119 exact-matching steps and no extras.
Field accuracy compares seven fields at corresponding array positions, counting missing
slots as errors. Step accuracy ignores step position; sequence and exact-case accuracy
require the full ordered array. The scoring formula is in `code/evaluation/scoring.py`.

These are regressions in sample score and coverage, not an accuracy improvement claim.
Phase 6 removes unsupported ownership, coverage, policy, and treatment assumptions.
Preserving 100% precision applies to the emitted sample steps only; it does not certify
unseen data or exhaustive discovery.

## Full participant dataset

| Result | Phase 5 | Phase 6 |
| --- | ---: | ---: |
| Requests processed | 518 | 518 |
| COMPLETE | 151 | 8 |
| INCOMPLETE | 351 | 332 |
| NOT_APPLICABLE | 10 | 10 |
| Predicted rows | 512 | 350 |
| Abstentions | 6 | 168 |
| Prediction coverage | 98.84% | 67.57% |
| Prediction citation/schema validation errors | 0 | 0 |
| Validated root output.csv | No | No |

Full-dataset status/step accuracy cannot be measured: hidden answers are unavailable and
were not accessed. The validation numbers measure schema, citation timing, parsing, and
resource linkage, not hidden semantic accuracy. Some INCOMPLETE diagnostic plans still
contain unresolved obligations; discovery and the remediation plan are not certified
exhaustive. No partial diagnostic output should be submitted as `output.csv`.

## Six original blockers: complete investigation

Each case was traced through request intent, exact current/historical identity, catalog
links, all exact-identifier participant observations at/before `audit_at`, temporal state,
policy applicability, and planning. Original PNGs were visually inspected. No additional
historical aliases or structured readbacks resolved the five outstanding facts.

| Case | Evidence and decision |
| --- | --- |
| case_39 | `activity_4002` links `data_flow_1121` to the subject. Original `evidence_14` shows a healthy continuous connector and delivery history, but no explicit current enabled/disabled configuration or independent as-of-audit readback. Those indicators are not converted into a fabricated enabled field. Abstains; needs a scoped connector-state observation. |
| case_45 | `activity_4010`, PNG `evidence_37`, and PDF `evidence_55` establish a retained security journal record (`audit_record_003`). An account-closure journal event is not an independent read of the account or its deleted copies. The record precedes this deletion request. Abstains; needs actual deletion-treatment/readback evidence and scoped retention applicability. |
| case_46 | `evidence_67` independently proves profile `account_6523` absent. Catalog `activity_4011` and original `evidence_42` identify a retained customer reference, `tombstone_17`. The screen shows references/history, not name/email/phone/hash removal or an explicit tombstone schema/state. Abstains; needs the tombstone fields and permitted stable reference treatment. |
| case_52 | **Recovered INCOMPLETE.** `activity_4004` links `export_1260`; the default OCR misreads the email. Alternate PSM 11 TSV isolates the export detail panel and independently extracts the exact email visible in `evidence_23`, before cutoff. The observed export still exists. Original misread text remains a separate unconfirmed observation; no expected string or spelling repair is injected. |
| case_55 | `activity_4006` and original `evidence_32` establish archive `backup_9287`, size, encryption and retention metadata. The screen contains no restore permission/deletion block. Restore events name other backups. Abstains; needs an explicit authorization/block read for this archive. |
| case_63 | Catalog `activity_4008` names the request subject, but `evidence_60` visibly names another person's email and phone for `marketing_001`. Historical identity data does not reconcile the subjects. The screenshot remains POTENTIAL and cannot generate a finding/remediation/verification for this subject. Abstains; needs corrected ownership evidence or another scoped subject record. |

## Corrections to Phase 5 assumptions

1. **Workflow attribution:** timing windows and result/status consistency now retrieve
   POTENTIAL candidates. They cannot prove ownership. Independent exact identifiers,
   scoped traces, or catalog links are required for promotion. The 149 Phase 5
   all-candidates-absent diagnostics did not establish an exhaustive account universe;
   candidate absence no longer substitutes for verified deletion treatment or permits
   COMPLETE. Explicit conflicting ownership remains disqualifying.
2. **Policy conditions:** support conversations are not automatically treated as shared;
   attachment association is not exclusive ownership; absent retention/hold facts do not
   prove current compliance. Missing conditions remain UNKNOWN. Security/legal records
   are preserved as a precaution, never deleted by a guessed default. Contrary current
   facts (including contradictory conditions) cannot be replaced by a historical true flag.
3. **Replica state/type:** every independently observed physical scope is assessed.
   A newer primary read cannot remove a surviving replica finding. A tombstone conversion
   in one scope cannot retype a surviving profile in another. Incompatible treatments for
   a single output resource cause abstention.
4. **Coverage:** a schema, row count, empty array, or snapshot envelope is not a complete
   inventory assertion. Negative listing proof needs `complete_listing: true`, matching
   known collection, and no truncation, filtering or pagination. Structured filters remain
   on their envelope instead of disappearing during extraction. Current SQL exports do
   not assert this guarantee and therefore cannot prove absence by omission.
5. **Treatment and ordering:** one null field cannot prove all required identifiers are
   removed. Explicit supported treatment readbacks still count when fields agree.
   Dependency conflicts with the mandated serialization order now block unsafe plans.
6. **OCR:** alternate TSV panel extraction keeps original file ID, digest and clocks,
   excludes neighbouring table rows, and never repairs identifiers. OCR-only exact matches
   remain unconfirmed without independent structured resource linkage. Conflicting OCR
   extractions cannot create historical ownership transitions.

The affected Phase 5 tests were strengthened to assert rejection of these unsupported
behaviors. Positive listing tests now provide explicit completeness and independent
ownership facts. No test was removed or threshold lowered to restore the old scores.

## Original adversarial regression cases

`code/tests/test_phase6.py` adds 24 synthetic test instances. Examples created independently
of sample answers:

| Original scenario | Required and tested behavior |
| --- | --- |
| Older surviving read replica, newer primary 404 | Keep the surviving replica violation and cite its own evidence. |
| New tombstone in primary, older profile replica | Preserve per-scope types and abstain if one output resource requires incompatible actions. |
| Subject-only attachment flag omitted | Do not authorize deletion; adding independent linkage alone does not establish exclusivity. |
| Shared support/retention/legal condition omitted | Do not manufacture applicability or COMPLETE. |
| Current true/false ownership-condition conflict after earlier true | Do not fall back to the convenient old condition. |
| Empty, paginated or filtered collection export | Do not infer absence, even with a schema and row count. |
| Complete listing of the wrong/unknown collection | Reject use as absence evidence. |
| Tombstone has stable reference and only null email | Insufficient coverage; do not infer removal of omitted identifiers. |
| OCR wrong spelling plus independently read exact detail panel | Retain both raw observations; accept only the independently linked supported extraction. |
| OCR exact email with no independent resource link | Remain unconfirmed. |
| Catalog subject conflicts with screenshot owner | Do not attribute the other person's record. |
| Post-audit clean readback | Keep the earlier supported violation; never cite the future evidence. |
| Potential foreign resource alongside a real violation | Never add a future verification for that potential resource. |
| Connector/archive exists without safety fields | Do not infer enabled/restore authorization. |

Three packaging tests cover deterministic source archives, exclusions, structured trace
redaction, and exclusion of unrelated/active sessions. The existing temporal, policy,
output, intent, identity and integration tests continue to run.

## The fifteen original sample misses

The Phase 5 misses comprise six anonymous analytics resources, seven ambiguously attributed
primary profiles, and two security resources absent from participant evidence. Inspection
found shared-batch operation claims and anonymous readbacks with no explicit ownership
bridge. The resources `audit_record_6645` and `audit_record_5569` do not occur in participant
inputs outside sample answers. Neither missing records nor identifiers are invented.
The original misses remain; the stricter Phase 6 boundaries also withdraw unsupported
steps/cases. No production lookup uses the reference answer file.

## Verification and reproducibility

Python 3.12.10 and uv 0.9.16 were used. `uv sync` succeeded; an isolated Python 3.12 pip
installation from `code/requirements.txt` and imports also passed. Required commands ran:

```text
uv run python -m pytest -q
uv run python code/main.py inspect
uv run python code/main.py phase2
uv run python code/main.py phase3
uv run python code/evaluation/main.py --check-reference
uv run python code/evaluation/main.py --run --json
uv run python code/main.py
```

All diagnostic/evaluation commands return 0; full publication returns the expected 2.
`validate-output --predictions output.csv` is inapplicable because no CSV was produced;
per-prediction strict checks ran during prediction. No dataset file or AGENTS.md changed.

Two independent sample and two full prediction processes produce identical complete
case-decision diagnostics after excluding timing summaries:

- Sample SHA-256: `e6fa67b14927fd807b7a02523849b58417114c46b87439ebc315c9c8ebf7c845`
- Full SHA-256: `6ab30d7ceca0300b8fb0581c9ed57979e3c86c7f1d6478c5e060f05036d8de6a`

Optional OCR was tested enabled, disabled (`GHOST_AUDIT_OCR=0`), and with an invalid
`GHOST_AUDIT_TESSERACT` path. Disabled/missing both give 8 COMPLETE, 328 INCOMPLETE,
10 NOT_APPLICABLE and 172 abstentions (346 predictions), with zero validation errors.
Unit tests cover configuration, unsupported image extraction and provenance. No paid API,
Gemini service, or Python image-processing dependency is required.

## Artifacts and remaining actions

`code/package_submission.py` builds and verifies a source-only deterministic `code.zip`,
including both required archive-root `evaluation/` reports and the original code paths.
It excludes dataset, environments, caches, nested ZIPs, output and traces. The archive can
be recreated after checkout. `log.txt` preserves prior history; new contexts use runtime-
verified Codex Desktop / gpt-6.1-sol. All 30 pre-completion log entries have populated
harness/model context fields; historical entries are preserved, not rewritten.

`agent-trace.zip` contains eight available earlier structured traces, retaining directory
structure (six Codex and two Claude Code); credential strings/account metadata are
redacted. **It is incomplete:** the active Phase 6 session cannot be finalized while it
is running. Per `agent_trace_instructions.md`, finish/quit apps, run
`py -3.12 code/package_traces.py` from a separate terminal, export readable Claude transcripts
with `/export`, and inspect the resulting archive before sharing. The raw structured
files are retained; missing exports are not fabricated.

Remaining correctness risks: incomplete discovery, unknown condition applicability,
ambiguous/unverified workflow resources, observational gaps between readbacks, screenshot
field omissions, OCR errors, and incomplete diagnostic remediation obligations. A complete
518-row submission requires additional defensible evidence/associations. No automatic
HackerRank submission or final independent code review has been performed.

## All final abstentions

The Phase 6 case list is superseded. The current 154 abstentions, each with its blockers,
root causes and earliest failing stage, are in `code/evaluation/abstention_diagnostics.json`.


## Source archive execution check

The verified source archive contains 58 files. After extraction to an isolated temporary
folder, `uv sync --frozen` succeeds and the full prediction command, pointing explicitly
to the original read-only participant dataset, reproduces every final case decision.
It exits 2 and creates no CSV, matching the source checkout. ZIP member bytes, required
report paths, and CRCs are checked; repeated builds produce identical archive bytes.
The separate eight-file trace archive passes JSONL/CRC and credential-pattern checks,
but still requires the documented post-session refresh and manual privacy inspection.


## Structural refactor verification

The production-grade refactor preserves the final submission and all prior measured
metrics. All 499 original behavioral scenarios remain, with 527 total tests. Exact CSV,
strict decisions, abstentions, confidence and public metrics match the protected
`4476d26` baseline. See the repository-root file `docs/refactor-report.md` for gates,
architecture, source mapping and archive verification. No correctness correction or
changed prediction is hidden in the refactor.


## Final code quality verification (original submission baseline)

The final dependency/typing/documentation pass preserves all sample metrics, 518 official
rows, 3,071 ordered steps and the protected output SHA-256 of the original baseline `4476d26`
(superseded by the current accepted release above). The complete 99-file Python
tree, including tests and packaging utilities, passes mypy strict mode; all 527 tests
pass. See `docs/quality-pass.md` in the repository/archive for the exact configuration,
direct dependency installation, full coverage inventory and verification results. Existing submission
inference limitations and failure analysis remain applicable.
