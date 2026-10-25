# Ghost Data Still Exists

An offline deletion-audit agent for HackerRank Orchestrate, October 2026. It resolves
current and historical identities, attributes participant evidence, reconstructs state
at each request's `audit_at`, applies deletion policy and produces ordered findings,
remediation and verification steps.

Python **3.12** is the supported development/runtime version. There is no model API,
credential or paid service dependency. Only participant-facing inputs under `dataset/`
are read. The dataset is distributed separately from `code.zip`.

## Install

```text
uv sync --frozen
```

This installs the editable Python package and development tools from `uv.lock`.
For runtime-only installation use `uv sync --frozen --no-dev`.

Pip fallback:

```text
python -m venv .venv
python -m pip install -r code/requirements.txt
python code/main.py
```

Activate the environment first: `.venv\Scripts\Activate.ps1` on PowerShell or
`source .venv/bin/activate` on Linux/macOS. Use `py -3.12` / `python3.12` when necessary.
For pip-based quality checks also install the project and tools:
`python -m pip install -e . ruff mypy import-linter`.

## Predict and inspect

```text
uv run python code/main.py
uv run python code/main.py validate-output --predictions output.csv
uv run python code/main.py inspect
uv run python code/main.py phase2 --case-id CASE_ID
uv run python code/main.py phase3 --case-id CASE_ID
```

The default **submission predictor** writes the complete root `output.csv`: 518 rows,
152 COMPLETE, 356 INCOMPLETE, 10 NOT_APPLICABLE and 3,071 steps on the supplied dataset.
It chooses the best-supported official answer and records heuristic assumptions and
low-confidence resources separately. `phase2` and `phase3` are historical CLI names
for evidence association and temporal reconstruction; internal modules use those
responsibility names.

The distinct **strict audit engine** retains uncertainty:

```text
uv run python code/main.py --strict --predictions strict-output.csv --diagnostics strict-diagnostics.json
```

On the supplied dataset it has 364 grounded predictions and 154 abstentions. Exit 2
means publication was blocked; an existing destination is preserved. Diagnostic JSON
still contains the strict decisions. The official CSV has no abstention status.

`--dataset PATH` selects participant inputs. Paths otherwise resolve from the checkout
root, independent of the current directory. `--samples` selects public sample requests
without loading their answers. `--predictions PATH` and `--diagnostics PATH` select
artifact locations outside the read-only dataset. Prediction always validates the
entire result before atomically replacing its CSV.

## Evaluate and check

```text
uv run python -m pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run lint-imports
uv run python code/evaluation/main.py --run --json
uv run python code/evaluation/main.py --run --engine strict --json
uv run python code/evaluation/main.py --predictions sample_predictions.csv --json
uv run python code/evaluation/main.py --check-reference
```

Generate an independent sample file with
`uv run python code/main.py --samples --predictions sample_predictions.csv` before
scoring it. Only the evaluation package reads `sample_output.csv`. Sample status
accuracy is 32/32; exact/sequence accuracy is 21/32, precision 100%, recall 93.782%
and field accuracy 87.935%. These are public-sample measurements, not hidden accuracy.

For an exact local golden-master comparison, keep the protected capture outside the
checkout and use:

```text
uv run python code/regression.py ../candidate --baseline ../protected-baseline
```

The command checks CSV bytes, ordered steps, strict decisions, abstentions, confidence,
sample results, CLI compatibility and unchanged dataset hashes. See
[baseline instructions](docs/baseline.md) and [testing](docs/testing.md).

## Optional local OCR

Install Tesseract and put it on PATH, or set `GHOST_AUDIT_TESSERACT` to its executable.
Windows also checks `C:\Program Files\Tesseract-OCR\tesseract.exe`.
`GHOST_AUDIT_OCR=0` disables it. Images without a usable executable remain deferred;
other evidence still runs. OCR uses original text and spatial detail panels, never
expected identities to repair spelling.

The reference run used Tesseract with all 94 manifest files parsed. Exact output
regression requires the same inputs and extraction environment; a different OCR
installation can change observations and must be investigated, not snapshot-approved.

## Package

```text
uv run python code/package_submission.py
```

The deterministic `code.zip` includes runtime code, tests and fixtures, configuration,
lockfile, pip requirements, this README, developer docs and the required reports at
`evaluation/evaluation_report.md` and `evaluation/usage_report.md`. It excludes dataset,
outputs, environments, caches, diagnostics, credentials, transcripts and nested archives.
After extraction, install dependencies and supply `--dataset PATH`; see
[development](docs/development.md) for a smoke-test command. No submission is performed.

The append-only `log.txt` is the separate chat transcript. To package raw local agent
traces after sessions have closed, follow [agent trace instructions](agent_trace_instructions.md).

## Developer documentation

- [Architecture and dependency rules](docs/architecture.md)
- [Data flow](docs/data-flow.md)
- [Evidence model and uncertainty](docs/evidence-model.md)
- [Development and packaging](docs/development.md)
- [Tests and regression strategy](docs/testing.md)
- [Protected baseline](docs/baseline.md)
- [Refactor release evidence](docs/refactor-report.md)
- [Official evaluation report](code/evaluation/evaluation_report.md)
- [Runtime and development usage](code/evaluation/usage_report.md)
