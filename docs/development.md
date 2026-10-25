# Development

Use Python 3.12 and `uv sync --locked`. The editable install exposes `ghost_audit` and
`evaluation`; scripts also remain runnable directly. All direct constraints live in
`pyproject.toml`: runtime requirements under `project.dependencies`, quality tools under
`dependency-groups.dev`, and the wheel backend under `build-system.requires`.
`uv.lock` records the resolution. `code/requirements.txt` is generated, includes every
development tool, and supports pip in both the checkout and extracted archive:

```text
uv lock
uv export --locked --all-groups --no-emit-project --output-file code/requirements.txt
python -m pip install -r code/requirements.txt
python -m pip install --no-deps -e .
```

Run exports from the repository root. The project install uses the build requirements
in `pyproject.toml`; dependency installation uses the hashed, locked export. Never edit
the export manually or add ad hoc tool versions to installation commands. Verify
metadata with `uv sync --locked`; runtime-only uv users may add `--no-dev`.

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
fixture was mistaken for an unused symbol. Mypy targets are configured in `pyproject.toml`:
all production modules, evaluation, the script entry point, packaging and regression.
Domain definitions require typed signatures and collections. Remaining outer-layer
JSON diagnostic dictionaries and schema callbacks are checked but not universally strict.
No package-wide ignore, unchecked cast or `type: ignore` is needed.

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
