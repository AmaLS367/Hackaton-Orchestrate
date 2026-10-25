# Development

Use Python 3.12 and `uv sync --locked`. The editable install exposes `ghost_audit` and
`evaluation`; scripts also remain runnable directly. All direct constraints live in
`pyproject.toml`: runtime requirements under `project.dependencies`, quality tools under
`dependency-groups.dev`, and the wheel backend under `build-system.requires`.
`uv.lock` records the resolution. Pip installs runtime dependencies and development
tools directly from the same metadata in both the checkout and extracted archive:

```text
python -m pip install --upgrade pip
python -m pip install -e . --group dev
```

Upgrade pip first for dependency-group support and run installation from the project
root. Runtime-only pip users can run `python -m pip install .`. Build isolation also
reads its backend requirement from `pyproject.toml`. Pip resolves its constraints;
use uv for the exact locked resolution. After changing metadata, run `uv lock` and
verify `uv sync --locked`; runtime-only uv users may add `--no-dev`. No dependency
export or separate requirements file is maintained or packaged.

## Conventions

Prefer pure domain functions, immutable model values and explicit per-run state.
Application services accept a loaded `Dataset`; interfaces assemble it with concrete
file adapters. Introduce injection or protocols only for an actual replaceable
boundary, not a speculative repository hierarchy. Keep strict and submission confidence
logic distinct. Share established schema and official-operation vocabulary.

Use semantic module names. Historical `phase2` / `phase3` exist only as CLI compatibility
names and stable diagnostic strings. New code must not infer predictions from case IDs,
filenames, sample answers, private truth or expected outputs. Never modify `dataset/`
while implementing or testing predictions. Preserve existing ignored artifacts before
running a different implementation. Stage intentional files and use conventional commits.

## Adding an evidence format

Add physical decoding under `infrastructure/parsers/`, preserve raw content, digest,
manifest identity and source clocks, and emit provenance-bearing domain observations.
Register it in the document dispatcher. Construct independent synthetic records that
exercise both positive and unavailable/ambiguous evidence. Parser output must not contain
an authoritative deletion verdict. Any new record semantics belong in the pure record
interpreter; its source-format argument is supplied outside the domain.

For a new policy condition, extend the domain evaluator and supplied-schema mapping.
Keep omitted applicability unknown, preserve retained records and test the future,
conflicting and partial-projection cases. Planning changes must respect official
operation ordering and explicit dependency conflicts.

## Quality gates

```text
uv run python -m pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run lint-imports
```

Use `uv run ruff format .` and `uv run ruff check . --fix` for routine formatting/imports.
Review fixes, especially pytest fixture imports; tests must never disappear because a
fixture was mistaken for an unused symbol. The normal `uv run mypy` command uses:

```toml
[tool.mypy]
python_version = "3.12"
mypy_path = "$MYPY_CONFIG_FILE_DIR/code"
explicit_package_bases = true
files = ["code"]
strict = true
```

This discovers every first-party Python file recursively: domain, application,
infrastructure, interfaces, both engines, evaluation, all four root scripts, tests
and fixtures (99 files). There are no exclusions, relaxed overrides, missing-import
ignores, casts, `Any` annotations or typing suppressions. Recount after adding modules:

```text
uv run python -c "from pathlib import Path; print(len(list(Path('code').rglob('*.py'))))"
```

Use precise model/collection types inside the engines and `TypedDict` for diagnostic
envelopes. Raw evidence uses recursive `JsonValue` until schema validation or explicit
narrowing establishes a field's type. Tests pass raw timestamp strings and malformed
payloads through the existing `model_validate` boundary, preserving parsed datetime
types and the negative validation scenarios. Check optional values before dereferencing
them; an absent observation or identifier is a business distinction, not a typing escape.

Use concise Google-style docstrings for public interfaces and non-obvious algorithms.
Explain cutoff availability, scope, policy or inference assumptions; avoid narrating
obvious assignments. Keep diagnostic confidence separate from proof of deletion.

Run the protected comparison after a structural change. Investigate every changed case,
step, citation, uncertainty diagnostic and sample metric before proceeding. A correctness
fix requires independent participant evidence and a synthetic test, and must be committed
separately from structural edits. Never accept it solely because sample accuracy rose.

## Packaging and extracted execution

```text
uv run python code/package_submission.py
```

The packager uses an explicit source/document/fixture allowlist, fixed timestamps,
sorted entries and CRC/byte validation. Required reports are also copied to archive-root
`evaluation/`. Outputs, datasets, JSON diagnostics, caches and agent traces are separate.

Extract to an empty directory and run its own scripts with the supplied participant
folder outside the archive:

```text
python code/main.py --dataset /absolute/path/to/dataset
python code/main.py validate-output --dataset /absolute/path/to/dataset --predictions output.csv
python code/evaluation/main.py --dataset /absolute/path/to/dataset --run --json
```

Install runtime dependencies first, using uv or pip as in the README. A clean-environment
smoke test must not import the original checkout through an editable install or
`PYTHONPATH`; use that environment's Python and the extracted scripts. Rebuild twice to
check deterministic archive bytes. No tool submits anything to HackerRank.
