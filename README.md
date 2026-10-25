# Ghost Data Still Exists

Offline deletion-audit pipeline for HackerRank Orchestrate October 2026. It reads only
participant files in `dataset/`, resolves current and historical identifiers, reconstructs
resource state at `audit_at`, applies the supplied policies, and builds ordered plans.

## Release status (recovery round, 2026-10-25)

The final measured run processes 518 requests: **22 COMPLETE, 332 INCOMPLETE,
10 NOT_APPLICABLE, and 154 abstentions**. A root `output.csv` is **not available**:
not every case has a justified prediction. Exit code **2** is the expected publication
block, not an unofficial submission status. Partial decisions remain in
`code/evaluation/full_prediction_diagnostics.json`; they are not a submission CSV.
Every abstention's root causes are in `code/evaluation/abstention_diagnostics.json`.

On 32 public samples: 21 predictions, 65.625% status accuracy, 6/32 exact cases,
100% step precision and 61.140% recall. These are sample measurements, not hidden-test
accuracy. See [the evaluation report](code/evaluation/evaluation_report.md).

## Setup

Use Python **3.12**; `.python-version` selects it. Preferred workflow:

```text
uv sync --frozen
uv run python -m pytest -q
uv run python code/main.py inspect
uv run python code/main.py phase2
uv run python code/main.py phase3
uv run python code/evaluation/main.py --check-reference
uv run python code/evaluation/main.py --run --json
uv run python code/main.py
```

`uv sync` is also supported. No runtime credentials, model service, Gemini dependency,
or paid API is required. Dependencies are Pydantic and pypdf; pytest is for development.

Pip fallback on Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r code/requirements.txt
python -m pytest -q
python code/main.py
```

On Linux/macOS, use `python3.12 -m venv .venv` and `source .venv/bin/activate`, then the
same pip and Python commands. Install dependencies before working offline. Run tests
from the repository root. Dataset/output paths otherwise resolve from the source root;
`--dataset PATH` selects another supplied participant dataset. The dataset is not bundled.

## Evidence boundaries

- `ingestion.py`, `extraction.py`, and `sql.py` read the participant allowlist, preserving
  file IDs, SHA-256 digests, capture/source clocks, resource scope, and raw text. SQL is
  executed only in a restricted in-memory SQLite connection. Source files are read only.
- `identity.py`, `index.py`, and `correlation.py` resolve exact current/historical aliases
  and follow scoped traces and explicit resources. Other subjects and POTENTIAL matches
  do not authorize findings or future verification steps.
- `workflow.py` supplies timing-based search candidates. Its windows/status heuristics
  are **not ownership evidence** and are not an exhaustive account inventory. Independent
  linkage is required. All-candidates-absent alone cannot establish COMPLETE.
- `temporal.py` separates states from claims and retains physical replicas. A newer
  observation of a different scope cannot erase a surviving copy. A fact counts only from
  its `known_at` time (the latest of its observation, record, capture/packaging and
  catalogue-link clocks): evidence captured after `audit_at` neither links ownership nor
  supplies state, however early its internal timestamps are.
- Listing absence requires an explicit `complete_listing: true` assertion, a matching
  known collection, no filter/truncation/pagination, and a citable capture. An empty array,
  schema, snapshot label, or row count alone is insufficient. Current SQL exports do not
  provide this assertion and are not used as negative inventory proof. A 404, NOT_FOUND
  or zero-row read proves absence only when it names the resource and declares no
  subject/collection query scope or filter.
- Documents are scoped per section (a "Continued" page extends the previous one); a
  section naming several subjects is narrowed to the lines naming the resource.
- `policy.py` requires supplied conditions for shared support context, subject-only
  attachments, retention, and legal holds. Missing facts stay UNKNOWN. Required retention
  is preserved; an unknown condition does not authorize deletion or a compliance claim.
  Partial null projections do not establish full redaction/anonymization. Explicit
  independent treatment readbacks can establish treatment if observed fields agree.
- `planning.py` orders official operations and checks explicit dependencies. A conflict
  between dependency order and the official order blocks publication. INCOMPLETE diagnostic
  plans can still contain unresolved obligations; they are not proof of exhaustive discovery.
- `output.py` strictly validates the seven step fields, operations, ordering, numbering,
  request coverage, and citation availability/linkage. Schema/linkage checks alone do not
  prove semantic correctness. Prediction additionally requires supported policy assessments.

Only `code/evaluation/` reads `sample_output.csv`; production never reads reference labels
or organizer files. Identifiers and outcomes are not derived from case IDs or filenames.

## Optional local OCR

Install Tesseract separately and put it on PATH, or set `GHOST_AUDIT_TESSERACT` to its
executable path. Windows also checks `C:\Program Files\Tesseract-OCR\tesseract.exe`.
Set `GHOST_AUDIT_OCR=0` to disable OCR. A missing/invalid executable leaves images deferred;
other evidence still runs. No Python imaging package is required.

OCR uses default text segmentation and alternate PSM 11 TSV coordinates for isolated
right-side detail panels. It never repairs spelling from an expected identity. Only
catalogued resource references are emitted; an OCR identity needs independent structured
resource linkage, and conflicting owners stay unconfirmed. Original text, method, digest,
and timestamps remain available. Screens lacking required fields remain unresolved.

## Output and diagnostics

```text
uv run python code/main.py --diagnostics path/to/diagnostics.json
uv run python code/main.py phase3 --case-id CASE_ID
uv run python code/main.py validate-output --predictions output.csv
```

The last command applies only when a complete prediction file exists. `dataset/output.csv`
is the untouched blank template, not the root submission. Publication never writes a partial
CSV and does not replace an existing file when the run is blocked. Diagnostics contain
fictional participant evidence and should be handled separately from source archives.

Each prediction run also writes `abstention_diagnostics.json` beside the diagnostics file:
one identifier-only record per unsupported case (confirmed and candidate resources, proven
and unknown states, verified treatment, missing policy conditions, account attribution,
listing coverage, unlinked readbacks, post-audit evidence IDs, unresolved obligations,
root causes and the earliest failing stage of EXTRACT → ASSOCIATE → INTERPRET →
APPLY_POLICY → PLAN → VALIDATE). It never contains names, emails, phones, hashes or text.
Candidate resources and unlinked readbacks are leads, not confirmed ownership.

## Submission artifacts

```text
uv run python code/package_submission.py
```

This creates and checks `code.zip` deterministically: source, tests, README, pip requirements,
pyproject, lockfile, Python version, and reports. Reports are included both at their source
locations and at the challenge-required archive paths `evaluation/evaluation_report.md` and
`evaluation/usage_report.md`. Dataset, virtual environments, caches, traces, credentials,
output files, and nested archives are excluded. Runtime model usage is zero; development
assistant usage is separate in the usage report.

`log.txt` is the append-only chat transcript. `agent-trace.zip` currently contains eight
available earlier structured traces (six Codex, two Claude Code); the active Phase 6 session
is deliberately excluded, so this archive is **incomplete**.

To finish traces, follow [agent_trace_instructions.md](agent_trace_instructions.md):

1. In relevant Claude Code sessions, run `/export` and save the readable exports separately.
2. Finish this chat, then quit Codex and Claude Code so their traces are flushed.
3. In a separate terminal at the checkout root, run
   `py -3.12 code/package_traces.py` (or `python3.12 code/package_traces.py`).
   This refreshes the ZIP with all matching local structured sessions, retaining original
   paths and JSONL format. Obvious credentials and account metadata are redacted.
4. Open the ZIP and inspect it for personal information/secrets before sharing. Add the
   readable Claude exports under `agent-trace/claude-code/` if required. The script cannot
   export a live Claude conversation or certify that every personal detail was removed.

The trace archive is separate from `code.zip`. No HackerRank submission is performed.
The release remains blocked by evidence/ownership/policy gaps documented in the report;
there is no fabricated 518-row fallback. An independent code review follows Phase 6.
