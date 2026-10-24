# Phase 6 evaluation — 2026-10-24

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

Groups list every remaining case and its publication blockers. Missing evidence includes
independent resource ownership, actual deletion treatment, current physical-scope state,
policy applicability and/or exhaustive primary-account coverage. Inspect the existing
`full_prediction_diagnostics.json` and `phase3 --case-id CASE_ID` for scoped evidence.

- `insufficient_evidence_for_complete_or_incomplete`:
  `case_113`, `case_117`, `case_121`, `case_135`, `case_137`, `case_164`, `case_167`, `case_170`, `case_193`, `case_233`, `case_235`, `case_264`, `case_283`, `case_292`, `case_313`, `case_314`, `case_319`, `case_322`, `case_323`, `case_324`, `case_326`, `case_327`, `case_331`, `case_369`, `case_372`, `case_374`, `case_375`, `case_378`, `case_380`, `case_383`, `case_390`, `case_392`, `case_41`, `case_430`, `case_44`, `case_46`, `case_463`, `case_51`, `case_516`, `case_520`, `case_521`, `case_522`, `case_545`, `case_73`, `case_77`, `case_79`, `case_80`, `case_81`, `case_82`, `case_83`, `case_84`, `case_86`, `case_88`.

- `insufficient_evidence_for_complete_or_incomplete`, `no_verified_deletion_treatment`:
  `case_108`, `case_111`, `case_124`, `case_126`, `case_150`, `case_160`, `case_162`, `case_178`, `case_179`, `case_183`, `case_190`, `case_204`, `case_206`, `case_213`, `case_221`, `case_253`, `case_260`, `case_274`, `case_276`, `case_280`, `case_335`, `case_336`, `case_339`, `case_342`, `case_343`, `case_354`, `case_39`, `case_393`, `case_403`, `case_423`, `case_424`, `case_427`, `case_45`, `case_452`, `case_456`, `case_458`, `case_460`, `case_462`, `case_479`, `case_484`, `case_493`, `case_494`, `case_497`, `case_502`, `case_503`, `case_506`, `case_508`, `case_524`, `case_53`, `case_530`, `case_532`, `case_55`, `case_57`, `case_61`, `case_63`, `case_64`, `case_66`, `case_69`, `case_70`, `case_76`, `case_97`.

- `insufficient_evidence_for_complete_or_incomplete`, `no_verified_deletion_treatment`, `primary_profile_ownership_or_search_coverage_unproven`:
  `case_103`, `case_107`, `case_112`, `case_127`, `case_151`, `case_155`, `case_157`, `case_175`, `case_191`, `case_215`, `case_218`, `case_219`, `case_225`, `case_226`, `case_231`, `case_232`, `case_257`, `case_277`, `case_282`, `case_297`, `case_304`, `case_308`, `case_309`, `case_351`, `case_362`, `case_408`, `case_409`, `case_411`, `case_412`, `case_457`, `case_480`, `case_512`, `case_58`, `case_59`, `case_60`.

- `insufficient_evidence_for_complete_or_incomplete`, `primary_profile_ownership_or_search_coverage_unproven`:
  `case_265`, `case_267`, `case_464`, `case_467`, `case_470`, `case_543`, `case_547`, `case_549`.

- `no_verified_deletion_treatment`, `primary_profile_ownership_or_search_coverage_unproven`:
  `case_152`, `case_243`, `case_244`, `case_294`, `case_295`, `case_299`, `case_345`, `case_346`, `case_395`, `case_398`, `case_448`.


## Source archive execution check

The verified source archive contains 58 files. After extraction to an isolated temporary
folder, `uv sync --frozen` succeeds and the full prediction command, pointing explicitly
to the original read-only participant dataset, reproduces every final case decision.
It exits 2 and creates no CSV, matching the source checkout. ZIP member bytes, required
report paths, and CRCs are checked; repeated builds produce identical archive bytes.
The separate eight-file trace archive passes JSONL/CRC and credential-pattern checks,
but still requires the documented post-session refresh and manual privacy inspection.
