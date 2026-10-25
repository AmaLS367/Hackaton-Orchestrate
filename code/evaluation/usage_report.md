# Runtime usage — final submission run, 2026-10-25

The final full-dataset run (`uv run python code/main.py`) processed all **518** requests
and wrote the root `output.csv` (518 rows). It also runs the strict audit engine for its
diagnostics. Both are local deterministic Python; no model is called.

| Runtime item | Actual value |
| --- | ---: |
| External model providers | None |
| Model names | None |
| Model/API calls | 0 |
| Input tokens | 0 |
| Output tokens | 0 |
| Total tokens | 0 |
| Average tokens per request (518 requests) | 0 |
| Estimated total model cost (USD) | 0.00 |
| Estimated model cost per request (USD) | 0.00 |
| Overall totals across all runtime models | 0 calls, 0 tokens, USD 0.00 |

There is no per-model table because no model is called. Intent classification, identity
resolution, retrieval, policy evaluation, planning, and validation are local deterministic
Python code. PDFs use pypdf; optional local Tesseract (tested version 5.3.1.20230401) uses
no API and consumes no model tokens. Gemini is not a dependency. Installation/network
traffic for Python packages and Git is not model inference.

Two repeated full-dataset predictions (byte-identical output) and sample evaluations of both
engines were measured separately;
each also uses zero model calls and tokens. OCR-disabled and missing-binary full runs use
zero model calls/tokens as well. CPU/electricity/storage costs are not measured and are
not included in the zero **model API cost** claim.

## Development-assistant usage (separate)

The submission round (2026-10-25) was implemented with **Claude Code / claude-opus-5-5**;
its token usage is not exposed to the session and is not claimed. Earlier rounds:

This implementation session uses **Codex Desktop / gpt-6.1-sol**, confirmed from the local
session metadata and turn context. Earlier challenge development also used Codex and
Claude Code; available structured traces are packaged separately in `agent-trace.zip`.
Development-assistant token counts and billing were not collected as a reliable total;
they are **not claimed to be zero** and are excluded from the solution-runtime totals.
The active development trace still needs to be flushed and added after quitting Codex.
No credentials or sensitive configuration values belong in the submission artifacts.


## Refactor validation run

The final full-dataset default command again processed all 518 requests (SHA-256
`1bc68692b30cfc7d23efb502c8ad6ba03bfecf75452415d11eae0d4639c3666c` after the
temporal-state and audit-cutoff policy fixes and the support-category workflow fallback;
see `policy_cutoff_differential.md` and `support_inference_differential.md`).
Both pathways still use 0 providers, 0 models, 0 calls, 0 input/output/total tokens,
0 average tokens per request, and USD 0 total/per-request model cost. Refactor work
used Codex Desktop / gpt-6.1-sol, verified from session metadata; assistant token and
billing totals are not available and are not represented as zero.
