# Phases 1, 2, and 3 runtime usage

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
