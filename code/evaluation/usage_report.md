# Phase 6 runtime usage — 2026-10-24

The final complete-dataset attempt processes all **518** requests. Publication is blocked
by unsupported cases: **no root output.csv was produced**. These measurements describe
that attempted final run, rather than a nonexistent successful submission export.

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

Two repeated full-dataset predictions and two sample evaluations were measured separately;
each also uses zero model calls and tokens. OCR-disabled and missing-binary full runs use
zero model calls/tokens as well. CPU/electricity/storage costs are not measured and are
not included in the zero **model API cost** claim.

## Development-assistant usage (separate)

This implementation session uses **Codex Desktop / gpt-6.1-sol**, confirmed from the local
session metadata and turn context. Earlier challenge development also used Codex and
Claude Code; available structured traces are packaged separately in `agent-trace.zip`.
Development-assistant token counts and billing were not collected as a reliable total;
they are **not claimed to be zero** and are excluded from the solution-runtime totals.
The active development trace still needs to be flushed and added after quitting Codex.
No credentials or sensitive configuration values belong in the submission artifacts.
