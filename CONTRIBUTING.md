# Contributing to Ghost Data Still Exists

Thank you for your interest in contributing to the **Ghost Data Still Exists** deletion-audit agent for HackerRank Orchestrate (October 2026).

This guide outlines our architecture rules, development setup, quality standards, and verification workflow.

---

## 1. Development Setup

The project requires **Python 3.12** and uses [`uv`](https://docs.astral.sh/uv/) for deterministic dependency management.

### Recommended setup (`uv`)

Clone the repository and install dependencies with locked versions:

```bash
uv sync --locked
```

This installs the editable package (`ghost-audit`) and all development tools defined in `pyproject.toml`.

### Alternative setup (`pip`)

If `uv` is unavailable, use a standard Python 3.12 virtual environment and `pip`:

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell:
.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e . --group dev
```

---

## 2. Repository Structure

The codebase is organized under `code/` following Clean Architecture with strict dependency boundaries:

- **`code/ghost_audit/domain/`**: Pure business rules, core entities, immutable value objects, audit-time semantics, and deletion policy definitions. Has zero external dependencies.
- **`code/ghost_audit/application/`**: Use cases, workflow orchestration, temporal reconstruction, evidence correlation, and submission record generation. Depends only on `domain`.
- **`code/ghost_audit/infrastructure/`**: Secondary adapters, evidence parsing (PDF, SQL, logs, images/OCR), storage readers, and system activity loaders. Implements domain/application interfaces without depending on application logic.
- **`code/ghost_audit/interfaces/`**: Primary entry points and CLI adapters (`main.py`, inspection tools). Composes application workflows with infrastructure adapters.
- **`code/evaluation/`**: Independent evaluation engine and benchmarking tools for computing metrics (`evaluation_report.md` and `usage_report.md`). Production code never imports evaluation.
- **`code/tests/`**: Unit tests, integration tests, end-to-end tests, architectural contract tests, and regression fixtures.

---

## 3. Development Standards

To keep the codebase maintainable, secure, and competition-compliant:

- **Architectural Integrity**: Strictly respect Clean Architecture layers. Dependencies always point inward. Never import outer layers from inner layers (enforced by `import-linter`).
- **Strict Typing**: Add complete type annotations across all functions and classes. The codebase enforces `mypy --strict` with zero exceptions.
- **Code Style & Formatting**: Follow Ruff linting rules and 100-character line lengths. Format code cleanly before submitting.
- **Evidence Provenance & Audit-Time Semantics**: All findings and verification steps must cite participant-visible evidence (`file_id`, `activity_id`, `audit_id`). Never evaluate data created after a case's `audit_at` timestamp.
- **Comprehensive Testing**: Write unit and integration tests for every behavioral modification.
- **Descriptive Naming & Docstrings**: Use clear, domain-aligned names and meaningful docstrings that clarify invariants.

---

## 4. Prediction Safety

Because this is a competitive audit benchmark, all predictions must adhere to strict integrity requirements:

- **No Hardcoded Answers**: Never hardcode sample solutions, case families, or golden outputs.
- **Participant-Facing Data Only**: Read only input files under `dataset/`. Never access organizer-only data or hidden truth.
- **Ground Truth & Provenance**: Never fabricate citations or step outputs. Every reported item must be backed by evidence available at or before `audit_at`.
- **Preserve Dataset Immutability**: Never modify files inside `dataset/`. All inputs are strictly read-only.
- **Deterministic Output**: Ensure all outputs, ordering, and JSON serialization are completely deterministic across runs and platforms.
- **Regression Verification**: If a change alters predictions in `output.csv`, run baseline comparisons and document the precise rationale for every altered row.

---

## 5. Verification Commands

Before proposing or merging any change, ensure all quality gates pass locally:

```bash
# 1. Run the test suite
uv run pytest -q

# 2. Check and format code with Ruff
uv run ruff check .
uv run ruff format --check .

# 3. Verify static type safety with strict mypy
uv run mypy

# 4. Enforce architectural layer boundaries
uv run lint-imports

# 5. Evaluate predictions against public samples
uv run python code/evaluation/main.py --run --json
```

---

## 6. Contribution Workflow

1. **Verify your local checkout**: Ensure you are working from a clean baseline and your environment is up to date (`uv sync --locked`).
2. **Implement focused changes**: Keep modifications minimal, isolated, and well-covered by tests.
3. **Run all verification checks**: Confirm that tests, Ruff, strict mypy, and import-linter pass without warnings.
4. **Inspect prediction diffs**: If `output.csv` is affected, verify that the diff represents genuine accuracy improvements rather than accidental regressions.
5. **Review and document**: Prepare a clear summary of the changes, architectural impact, and verification results for review.

