# Phase 5 full-dataset run — 2026-10-24

`python code/main.py` processed all **518 requests** on Python **3.12.10**: 151 COMPLETE,
351 INCOMPLETE and 10 NOT_APPLICABLE grounded rows (512 pass per-row validation) and 6
diagnostic abstentions. It exited 2 and **did not write output.csv**, so this is the usage
of the final attempted run, not of a published submission.

## Runtime model usage (the solution itself)

| Measure | Final full-dataset run |
| --- | --- |
| Model providers | None |
| Runtime model names | None |
| Model-call count | 0 |
| Input / output / total tokens | 0 / 0 / 0 |
| Average tokens per request | 0 / 518 = 0 |
| Estimated total API cost | USD 0 |
| Estimated API cost per request | USD 0 / 518 = USD 0 |
| Per-model totals | Not applicable; no runtime model configured or called |
| Overall calls / tokens / cost | 0 / 0 / USD 0 |
| Local OCR | Tesseract 5.3.1 CLI, 11 image files, once per file digest per process; offline, no tokens or API cost |
| Prediction + per-row validation time | 8.69 s (excluding ingestion/OCR) |

The independent 32-sample run also used 0 model calls, 0 tokens and USD 0 (2.56 s).

**Gemini**: not used. No `GEMINI_API_KEY`/`GOOGLE_API_KEY` is configured, so availability and
model listing could not be checked. Deterministic OCR plus catalogue cross-checks recovered the
images with usable facts, and the six remaining abstentions involve contradictory or absent facts
that an unverified model extraction should not override. No adapter or SDK was added.

## Development-assistant usage (not runtime)

Phase 5 was developed with **Claude Code** using model **claude-opus-5-5**. That usage
belongs to development, not to any prediction run, and is excluded from the per-request
figures above. The assistant's own token counts and billing are not exposed to the project,
so they are not estimated here. No credentials were used or recorded.

---

# Historical: Phase 4 full-dataset attempt — 2026-10-24

The final measured offline attempt processed **518 requests** on Python **3.12.10** using
`python code/main.py`. It established 336 INCOMPLETE and 10 NOT_APPLICABLE predictions;
172 cases abstained. The command returned exit 2 and **did not create output.csv**.
This is usage for the final attempted run, not a claim that a successful final submission
run has occurred. A successful full submission run still requires resolution of the blockers.

| Measure | Final full-dataset attempt |
| --- | --- |
| Model providers | None |
| Runtime model names | None |
| Model-call count | 0 |
| Input tokens | 0 |
| Output tokens | 0 |
| Total tokens | 0 |
| Average model tokens per request | 0 / 518 = 0 |
| Estimated total model API cost | USD 0 |
| Estimated model API cost per request | USD 0 / 518 = USD 0 |
| Per-model totals | Not applicable; no runtime models configured or called |
| Overall calls / input / output / tokens / API cost | 0 / 0 / 0 / 0 / USD 0 |
| Prediction and row-validation processing time | 6.8314 seconds |
| Supported rows passing unchanged validation | 346 |
| Full-output validation | Blocked; 172 predictions are unsubstantiated |

The independent 32-sample production attempt and evaluation also used **0 model calls,
0 input/output tokens, and USD 0 model API cost**; sample processing took 1.3924 seconds.
Processing times exclude dataset ingestion and diagnostic serialization, with tests running
concurrently. Local compute and development-assistant usage are not model API usage and
are not measured by the solution. No credentials, external API SDK, pricing estimate,
or unrecorded fallback model is used. All policy decisions and ordering are deterministic.

These totals are written directly here so they remain visible without generated JSON files.
Historical preliminary usage reports follow and do not override this current run's results.

---

# Historical runtime usage: Phases 1, 2, and 3

No final full-dataset **prediction** run has occurred, and no `output.csv` has been
generated. The Phase 1 full-corpus ingestion/checks are offline. This is a preliminary
runtime report, not the required final submission-run usage report.

| Runtime measure | Phase 1 |
| --- | --- |
| Model providers / model names | None |
| Model calls | 0 |
| Input tokens | 0 |
| Output tokens | 0 |
| Total tokens | 0 |
| Average model tokens per ingested evaluation request | 0 (518 requests) |
| Estimated model API cost, total | USD 0 |
| Estimated model API cost per ingested evaluation request | USD 0 |
| Per-model totals | Not applicable; no runtime models configured |
| Overall model calls / tokens / cost | 0 / 0 / USD 0 |

Development-assistant usage is separate from solution runtime usage and is not measured
by the solution. No paid OpenAI access or external AI service is needed. Future optional
Gemini/free-provider adapters should record actual provider/model names, calls, token counts,
pricing assumptions, and per-model/overall totals. Replace this preliminary report with
measurements from the final run that actually produces the submission output; do not infer
usage or prediction results from the foundation inspection run.

## Phase 2 critical stabilization run

The final stabilization diagnostics processed all 518 requests and the 32 public sample
requests offline on Python 3.12.10. The full run resolves 518 identities, classifies
508 deletion and 10 non-deletion intents, and produces 2,100 confirmed observation
associations. It produces evidence bundles, not submission predictions or `output.csv`.

| Runtime measure | Final full-dataset Phase 2 diagnostics |
| --- | --- |
| Model providers / names | None |
| Model calls | 0 |
| Input / output / total tokens | 0 / 0 / 0 |
| Average total model tokens per request | 0 (518 requests) |
| Estimated total / per-request model API cost | USD 0 / USD 0 |
| Per-model totals | Not applicable |
| Overall calls / tokens / estimated cost | 0 / 0 / USD 0 |

The sample diagnostic run also uses zero model calls, tokens, and API cost. Development
assistant usage remains outside solution-runtime accounting. This report still requires
replacement with measured usage from the eventual run producing submission predictions.

## Phase 3 full-dataset reconstruction run

The final Phase 3 diagnostics processed all 518 requests (508 authorized) offline with the
existing Python 3.12 dependencies. The run established 1,544 record states across 2,703
discovered resource/source scopes; 1,159 record selections remained unknown. This was a
reconstruction diagnostic, not the final prediction run, and did not produce `output.csv`.

| Runtime measure | Full-dataset Phase 3 diagnostics |
| --- | --- |
| Model providers / names | None |
| Model-call count | 0 |
| Input / output / total tokens | 0 / 0 / 0 |
| Average total model tokens per request | 0 (518 requests) |
| Estimated total / per-request API cost | USD 0 / USD 0 |
| Per-model totals | Not applicable; no runtime models |
| Overall calls / tokens / estimated cost | 0 / 0 / USD 0 |

The sample-only and single-case runs also use no external calls, tokens, or API cost.
Development-assistant usage is not measured by this runtime report. Final submission-run
usage and prediction accuracy must be measured when the later policy/output engine exists.
