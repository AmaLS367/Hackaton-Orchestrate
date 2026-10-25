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
uv sync --locked
```

This installs the editable Python package and development tools from `uv.lock`.
For runtime-only installation use `uv sync --locked --no-dev`.

Pip fallback:

```text
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e . --group dev
python code/main.py
```

Activate the environment first: `.venv\Scripts\Activate.ps1` on PowerShell or
`source .venv/bin/activate` on Linux/macOS. Use `py -3.12` / `python3.12` when necessary.
Upgrade pip first for dependency-group support. The install command reads runtime
dependencies and the `dev` group directly from `pyproject.toml`, so the environment
supports tests and quality checks. For runtime-only pip installation use
`python -m pip install .`. Run these commands from the checkout or extracted archive
root. `uv.lock` pins uv's resolution; pip resolves the constraints in `pyproject.toml`.
After changing dependencies, run `uv lock` and verify `uv sync --locked`.

## Predict and inspect

```text
uv run python code/main.py
uv run python code/main.py validate-output --predictions output.csv
uv run python code/main.py inspect
uv run python code/main.py phase2 --case-id CASE_ID
uv run python code/main.py phase3 --case-id CASE_ID
```

The default **submission predictor** writes the complete root `output.csv`: 518 rows,
154 COMPLETE, 354 INCOMPLETE, 10 NOT_APPLICABLE and 3,067 steps on the supplied dataset
(SHA-256 `1bc68692b30cfc7d23efb502c8ad6ba03bfecf75452415d11eae0d4639c3666c`). The earlier
152 / 356 / 3,071 counts belong to the original submission baseline; see the release
lineage in [baseline](docs/baseline.md).
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

`uv run mypy` applies `strict = true` to all 99 Python files under `code/`, including
tests, fixtures, both packaging scripts and regression tools. No packages are excluded
or configured with weaker checks. See [development](docs/development.md) for the exact
configuration and installation workflow.

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

## Docker

The image bundles Python 3.12, the locked runtime dependencies from `pyproject.toml`
(`uv sync --locked --no-dev`) and Tesseract, and runs as an unprivileged user. It contains
no dataset, predictions, credentials or network requirement. Mount the participant
dataset read-only at `/data` and a writable directory at `/output`.

```text
docker build -t ghost-audit .
mkdir -p /tmp/ghost-audit-out
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD/dataset:/data:ro" -v /tmp/ghost-audit-out:/output ghost-audit
```

PowerShell:

```text
docker build -t ghost-audit .
New-Item -ItemType Directory -Force "$env:TEMP\ghost-audit-out"
docker run --rm --network none `
  -v "${PWD}\dataset:/data:ro" -v "$env:TEMP\ghost-audit-out:/output" ghost-audit
```

The default command is `--dataset /data --predictions /output/output.csv --diagnostics
/output/full_prediction_diagnostics.json`; it writes `output.csv` plus the three diagnostic
JSON files into `/output` (the code tree is read-only at runtime, so diagnostics must not
use their checkout defaults). Arguments after the image name replace that command and keep
every CLI option, for example:

```text
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/dataset:/data:ro" \
  ghost-audit inspect --dataset /data
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/dataset:/data:ro" \
  -v /tmp/ghost-audit-out:/output:ro ghost-audit \
  validate-output --dataset /data --predictions /output/output.csv
```

On Linux run every command with `--user "$(id -u):$(id -g)"` and create the output
directory first: the image's default user cannot write to a directory you own, and the
atomic CSV writer creates `output.csv` readable by its owner only, so later commands
such as `validate-output` must run as the same user. Docker Desktop on Windows and macOS
needs neither. **Tesseract is required to reproduce the accepted output.** With
`GHOST_AUDIT_OCR=0` seven cases have no provable resource state, publication is blocked
and the container exits 2 without writing a CSV. The image installs Debian
bookworm's Tesseract 5.3.0 (the reference run used Windows Tesseract 5.3.1); a container run
on the participant dataset produces the accepted `output.csv` byte for byte
(SHA-256 `1bc68692b30cfc7d23efb502c8ad6ba03bfecf75452415d11eae0d4639c3666c`). After
rebuilding on a different base image, compare that hash before trusting the output.

## Package

```text
uv run python code/package_submission.py
```

The deterministic `code.zip` includes runtime code, tests and fixtures, configuration,
`Dockerfile`/`.dockerignore`,
lockfile, this README, developer docs and the required reports at
`evaluation/evaluation_report.md` and `evaluation/usage_report.md`. It excludes dataset,
outputs, environments, caches, diagnostics, credentials, transcripts and nested archives.
Known text assets are stored with LF endings, so Windows and Linux checkouts of one commit
build a byte-identical archive.
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
- [Final quality pass and validation](docs/quality-pass.md)
- [Official evaluation report](code/evaluation/evaluation_report.md)
- [Runtime and development usage](code/evaluation/usage_report.md)
