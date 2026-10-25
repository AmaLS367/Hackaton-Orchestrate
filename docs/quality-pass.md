# Final code quality pass

## Scope and baseline

Started from clean `master` at `7ac812d`, after reading AGENTS.md and CLAUDE.md.
The initial 527 tests, Ruff lint/format, 60-file mypy configuration and both import
contracts passed. An independent output copy and full behavioral capture were saved
outside the checkout before editing. The stored original golden master matched with
zero differences. No deadline is configured.

Local commits: dependency consolidation `d7fa240`; strict typing `01a0f5f`; the third
commit contains these docs and the append-only transcript. Nothing was pushed.

## Dependencies

`pyproject.toml` already declared the runtime and dev constraints below. The remaining
manual duplicates were three lines in `code/requirements.txt` (pydantic, pypdf, pytest)
and ad hoc Ruff/mypy/import-linter names in README's pip command.

The final authoritative declarations are:

```toml
[project]
requires-python = ">=3.12"
dependencies = ["pydantic>=2.10,<3", "pypdf>=5,<7"]

[dependency-groups]
dev = [
    "import-linter>=2,<3",
    "mypy>=1.15,<2",
    "pytest>=8,<10",
    "ruff>=0.11,<1",
]

[build-system]
requires = ["hatchling>=1.27,<2"]
build-backend = "hatchling.build"
```

No dependencies or versions were added. `uv lock` and `uv sync --locked` confirmed
that the existing 24-package lock resolution remains valid; uv.lock is byte-unchanged.
The pip artifact is a hashed, pinned export containing runtime and all dev tools:

```text
uv lock
uv export --locked --all-groups --no-emit-project --output-file code/requirements.txt
python -m pip install --require-hashes -r code/requirements.txt
python -m pip install --no-deps -e .
```

Regenerating the export reproduced identical bytes. A fresh Python 3.12 pip environment
installed it with hash verification, passed `pip check`, and imported every runtime/dev
dependency. Build isolation reads its backend requirement from pyproject.toml.

## Strict typing and documentation

```toml
[tool.mypy]
python_version = "3.12"
mypy_path = "$MYPY_CONFIG_FILE_DIR/code"
explicit_package_bases = true
files = ["code"]
strict = true
```

The documented `uv run mypy` checks all **99 first-party Python files**: 53 production
package files (25 domain, 13 application, 12 infrastructure, 2 interfaces, 1 package
initializer), 4 evaluation files, 4 root scripts, and 38 tests/fixtures. There are no
excluded modules, relaxed overrides, missing-import ignores, error-code disables,
`Any` annotations, casts, typing suppressions or external stub workarounds.

Corrections include callable signatures, recursive JSON types, typed diagnostic and
regression envelopes, fixture contracts, SQLite callbacks and explicit optional-value
narrowing. Raw boundary payloads still use the existing Pydantic validators; parsed
fields retain precise datetime/model types. Collection matching and canonical ordering
are unchanged. The raw synthetic JSON wrapper validates fixture shape, not labels.

Every production module has a module docstring. Public boundary and complex algorithm
documentation now explains historical alias availability, ownership intervals, bounded
correlation, worker matching, SQL restrictions, physical replicas, policy applicability,
tombstone field coverage, remediation order, strict/submission differences and confidence
limits. README, development, testing and evidence-model docs describe the current checks.
The documentation-stage Python AST matches the typing commit after removing docstrings;
only comments, documentation strings and formatting changed in that stage.

## Verification

- `uv sync --locked`: passed.
- `uv run python -m pytest -q`: **527 passed** before and after typing/documentation.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: **114 files already formatted** (Ruff formatting also
  includes Markdown and TOML files beyond the 99 Python modules).
- `uv run mypy`: **99 source files**, strict, zero errors.
- `uv run lint-imports`: **2 contracts kept, 0 broken**, 82 analyzed files.
- `uv run python -m compileall -q code`: passed.
- `uv run python code/main.py`: passed twice with identical output bytes.
- `uv run python code/main.py validate-output --predictions output.csv`: passed.
- `uv run python code/evaluation/main.py --run --json`: passed with identical metrics.
- `uv run python code/package_submission.py`: passed.
- Full post-typing and final protected comparisons: **0 behavioral differences** across CSV,
  ordered steps, strict decisions/abstentions, confidence, public metrics and CLI results.

Both prediction runs retained 518 rows: **152 COMPLETE, 356 INCOMPLETE,
10 NOT_APPLICABLE**, and **3,071 ordered steps**. Original and final SHA-256:

```text
2dfda949b915f713b7a261692be8bdd1b7cfcb3bbe3b5b2387d2b055f34d4227
```

Strict decisions remain 364 predictions and 154 abstentions; strict publication returns
2 and preserves the destination. Low-confidence diagnostics, resource/evidence IDs,
source timestamps and the complete participant-input hash manifest remain unchanged.
No functional correction or intentional behavior difference was introduced. The inherited
submission assumptions and uncertainty described in evidence-model.md remain applicable.

Public-sample metrics, before and after:

| Metric | Before | After |
|---|---:|---:|
| reference_cases | 32 | 32 |
| predicted_cases | 32 | 32 |
| missing_cases | 0 | 0 |
| status_accuracy | 1.0 | 1.0 |
| step_accuracy | 0.9378238341968912 | 0.9378238341968912 |
| step_precision | 1.0 | 1.0 |
| step_recall | 0.9378238341968912 | 0.9378238341968912 |
| field_accuracy | 0.8793486306439674 | 0.8793486306439674 |
| sequence_accuracy | 0.65625 | 0.65625 |
| exact_case_accuracy | 0.65625 | 0.65625 |

The existing independent custom cases, failure analysis and offline usage report remain
in evaluation/. No new runtime model calls, tokens or costs were introduced.

## Archive and isolated execution

The source archive passed member/CRC/source-byte checks and contains 117 entries,
including all 99 Python modules, pyproject.toml, uv.lock, the generated pip export,
developer docs, synthetic regression fixtures and both required evaluation reports.
It excludes participant data, predictions, environments, caches, credentials, transcripts
and nested archives.

A fresh extraction outside the checkout passed `uv sync --locked`. A second fresh
Python 3.12 pip environment installed the hashed export and the extracted editable
project, then passed `pip check`, strict mypy (99 files), Ruff lint/format, both import
contracts and **244 unit tests**. All 99 modules imported from the extracted source
path with no original checkout/PYTHONPATH fallback. Full prediction and output validation
succeeded with an explicit external read-only dataset path; the output hash and every
public-sample metric exactly matched the baseline. Repeat archive builds have identical
bytes; archive-root report paths and source membership are verified separately.

No official dataset or AGENTS.md changes were made. No remaining issues block this
quality pass; inherited uncertainty and the unchanged sample failure cases remain
documented. Python 3.12 is the verified runtime. No push, merge or submission occurred.

## File coverage and changes

The exact mypy discovery tree is all `.py` files recursively under `code/`. It agrees
with the tracked source inventory (98 original files plus one typed fixture-contract
module). Reproduce the count with the command in development.md.

<details>
<summary>99 files checked by the normal mypy command</summary>

- `code/evaluation/__init__.py`
- `code/evaluation/failures.py`
- `code/evaluation/main.py`
- `code/evaluation/scoring.py`
- `code/ghost_audit/__init__.py`
- `code/ghost_audit/application/__init__.py`
- `code/ghost_audit/application/abstention_diagnostics.py`
- `code/ghost_audit/application/evidence_association.py`
- `code/ghost_audit/application/model_port.py`
- `code/ghost_audit/application/observation_interpretation.py`
- `code/ghost_audit/application/strict_audit.py`
- `code/ghost_audit/application/submission/__init__.py`
- `code/ghost_audit/application/submission/evidence.py`
- `code/ghost_audit/application/submission/records.py`
- `code/ghost_audit/application/submission/workflow.py`
- `code/ghost_audit/application/submission_service.py`
- `code/ghost_audit/application/temporal_diagnostics.py`
- `code/ghost_audit/application/temporal_service.py`
- `code/ghost_audit/domain/__init__.py`
- `code/ghost_audit/domain/association_models.py`
- `code/ghost_audit/domain/catalog.py`
- `code/ghost_audit/domain/citation_validation.py`
- `code/ghost_audit/domain/correlation.py`
- `code/ghost_audit/domain/dataset.py`
- `code/ghost_audit/domain/diagnostic_models.py`
- `code/ghost_audit/domain/evidence_index.py`
- `code/ghost_audit/domain/identity.py`
- `code/ghost_audit/domain/intent.py`
- `code/ghost_audit/domain/models.py`
- `code/ghost_audit/domain/observation_clocks.py`
- `code/ghost_audit/domain/output_contract.py`
- `code/ghost_audit/domain/planning.py`
- `code/ghost_audit/domain/policy.py`
- `code/ghost_audit/domain/policy_models.py`
- `code/ghost_audit/domain/record_interpretation.py`
- `code/ghost_audit/domain/snapshot_coverage.py`
- `code/ghost_audit/domain/snapshot_inventory.py`
- `code/ghost_audit/domain/state_selection.py`
- `code/ghost_audit/domain/submission_models.py`
- `code/ghost_audit/domain/submission_semantics.py`
- `code/ghost_audit/domain/temporal_models.py`
- `code/ghost_audit/domain/time.py`
- `code/ghost_audit/domain/workflow_attribution.py`
- `code/ghost_audit/infrastructure/__init__.py`
- `code/ghost_audit/infrastructure/ingestion/__init__.py`
- `code/ghost_audit/infrastructure/ingestion/dataset_loader.py`
- `code/ghost_audit/infrastructure/parsers/__init__.py`
- `code/ghost_audit/infrastructure/parsers/documents.py`
- `code/ghost_audit/infrastructure/parsers/image_ocr.py`
- `code/ghost_audit/infrastructure/parsers/sql_snapshot.py`
- `code/ghost_audit/infrastructure/parsers/structured.py`
- `code/ghost_audit/infrastructure/serialization/__init__.py`
- `code/ghost_audit/infrastructure/serialization/csv_output.py`
- `code/ghost_audit/infrastructure/serialization/csv_records.py`
- `code/ghost_audit/infrastructure/serialization/prediction_artifacts.py`
- `code/ghost_audit/interfaces/__init__.py`
- `code/ghost_audit/interfaces/cli.py`
- `code/main.py`
- `code/package_submission.py`
- `code/package_traces.py`
- `code/regression.py`
- `code/tests/__init__.py`
- `code/tests/conftest.py`
- `code/tests/e2e/__init__.py`
- `code/tests/e2e/test_submission.py`
- `code/tests/fixtures/__init__.py`
- `code/tests/fixtures/audit_cases.py`
- `code/tests/fixtures/contracts.py`
- `code/tests/fixtures/evidence_cases.py`
- `code/tests/fixtures/identity_cases.py`
- `code/tests/fixtures/output_cases.py`
- `code/tests/fixtures/paths.py`
- `code/tests/integration/__init__.py`
- `code/tests/integration/test_citation_registry.py`
- `code/tests/integration/test_dataset_ingestion.py`
- `code/tests/integration/test_evidence_association.py`
- `code/tests/integration/test_evidence_recovery.py`
- `code/tests/integration/test_output.py`
- `code/tests/integration/test_packaging.py`
- `code/tests/integration/test_strict_audit.py`
- `code/tests/integration/test_temporal_reconstruction.py`
- `code/tests/regression/__init__.py`
- `code/tests/regression/test_adversarial_evidence.py`
- `code/tests/regression/test_architecture.py`
- `code/tests/regression/test_golden_master.py`
- `code/tests/regression/test_ownership_and_cutoffs.py`
- `code/tests/unit/__init__.py`
- `code/tests/unit/application/__init__.py`
- `code/tests/unit/application/test_evaluation.py`
- `code/tests/unit/application/test_regression_comparison.py`
- `code/tests/unit/application/test_submission_records.py`
- `code/tests/unit/domain/__init__.py`
- `code/tests/unit/domain/test_correlation.py`
- `code/tests/unit/domain/test_identity.py`
- `code/tests/unit/domain/test_intent.py`
- `code/tests/unit/domain/test_time.py`
- `code/tests/unit/infrastructure/__init__.py`
- `code/tests/unit/infrastructure/test_evidence_parsers.py`
- `code/tests/unit/infrastructure/test_log_formats.py`

</details>

<details>
<summary>Files changed across the three local commits</summary>

- `README.md`
- `code/evaluation/evaluation_report.md`
- `code/evaluation/failures.py`
- `code/evaluation/main.py`
- `code/evaluation/scoring.py`
- `code/ghost_audit/application/abstention_diagnostics.py`
- `code/ghost_audit/application/evidence_association.py`
- `code/ghost_audit/application/strict_audit.py`
- `code/ghost_audit/application/submission/evidence.py`
- `code/ghost_audit/application/submission/records.py`
- `code/ghost_audit/application/submission/workflow.py`
- `code/ghost_audit/application/submission_service.py`
- `code/ghost_audit/application/temporal_diagnostics.py`
- `code/ghost_audit/application/temporal_service.py`
- `code/ghost_audit/domain/citation_validation.py`
- `code/ghost_audit/domain/correlation.py`
- `code/ghost_audit/domain/evidence_index.py`
- `code/ghost_audit/domain/identity.py`
- `code/ghost_audit/domain/observation_clocks.py`
- `code/ghost_audit/domain/planning.py`
- `code/ghost_audit/domain/policy.py`
- `code/ghost_audit/domain/workflow_attribution.py`
- `code/ghost_audit/infrastructure/parsers/documents.py`
- `code/ghost_audit/infrastructure/parsers/sql_snapshot.py`
- `code/ghost_audit/infrastructure/parsers/structured.py`
- `code/ghost_audit/infrastructure/serialization/csv_output.py`
- `code/ghost_audit/infrastructure/serialization/prediction_artifacts.py`
- `code/ghost_audit/interfaces/cli.py`
- `code/package_submission.py`
- `code/package_traces.py`
- `code/regression.py`
- `code/requirements.txt`
- `code/tests/conftest.py`
- `code/tests/e2e/test_submission.py`
- `code/tests/fixtures/audit_cases.py`
- `code/tests/fixtures/contracts.py`
- `code/tests/fixtures/evidence_cases.py`
- `code/tests/fixtures/identity_cases.py`
- `code/tests/fixtures/output_cases.py`
- `code/tests/integration/test_citation_registry.py`
- `code/tests/integration/test_dataset_ingestion.py`
- `code/tests/integration/test_evidence_association.py`
- `code/tests/integration/test_evidence_recovery.py`
- `code/tests/integration/test_output.py`
- `code/tests/integration/test_packaging.py`
- `code/tests/integration/test_strict_audit.py`
- `code/tests/integration/test_temporal_reconstruction.py`
- `code/tests/regression/test_adversarial_evidence.py`
- `code/tests/regression/test_architecture.py`
- `code/tests/regression/test_golden_master.py`
- `code/tests/regression/test_ownership_and_cutoffs.py`
- `code/tests/unit/application/test_evaluation.py`
- `code/tests/unit/application/test_regression_comparison.py`
- `code/tests/unit/application/test_submission_records.py`
- `code/tests/unit/domain/test_correlation.py`
- `code/tests/unit/domain/test_identity.py`
- `code/tests/unit/domain/test_intent.py`
- `code/tests/unit/domain/test_time.py`
- `code/tests/unit/infrastructure/test_evidence_parsers.py`
- `code/tests/unit/infrastructure/test_log_formats.py`
- `docs/development.md`
- `docs/evidence-model.md`
- `docs/quality-pass.md`
- `docs/testing.md`
- `log.txt`
- `pyproject.toml`

</details>
