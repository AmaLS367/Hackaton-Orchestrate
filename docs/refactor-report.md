# Refactor verification report

This records the earlier refactor. For current installation use README.md: the final
dependency pass removed the requirements file and installs directly from pyproject.toml.

Reference: `4476d2605a45186e27eba709262db7869a1c7e76` on `master`.
All implementation commits are local; no push or submission was performed.

## Outcome and protected evidence

This is a structural/readability refactor with **zero changed predictions** and no
retained behavioral correction. Full per-case output, ordered steps, strict decisions,
abstentions, attribution, low confidence, sample metrics and business CLI results
compare identically. A temporary CLI metadata-key regression was detected by the
comparator and corrected; the original `output_path` key has its own assertion.

The original ignored CSV was protected before generation. The immutable local capture
is `../.ghost-audit-baseline-01a17185-d648-7533-81b7-f4db648c3af6/`.
It contains `original-output.csv`, regenerated CSV, all per-case records, CLI transcripts,
test inventory, input hashes and original public-interface/import graph inventory.
Final machine-readable checks are in `../.ghost-audit-final-validation/`;
`capture/diff.json` is `[]`. These directories are outside Git and the submission ZIP.

| Full dataset | Baseline | Final |
| --- | ---: | ---: |
| Submission predictions | 518 | 518 |
| COMPLETE / INCOMPLETE / NOT_APPLICABLE | 152 / 356 / 10 | 152 / 356 / 10 |
| Submission steps | 3,071 | 3,071 |
| Strict predictions | 364 | 364 |
| Strict COMPLETE / INCOMPLETE / NOT_APPLICABLE | 22 / 332 / 10 | 22 / 332 / 10 |
| Strict steps / abstentions | 1,946 / 154 | 1,946 / 154 |
| Cases with low-confidence resources | 138 | 138 |
| Original behavioral scenarios | 499 | 499 preserved |
| Total passing tests | 499 | 527 |

Baseline CSV SHA-256:
`2dfda949b915f713b7a261692be8bdd1b7cfcb3bbe3b5b2387d2b055f34d4227`

Final CSV SHA-256:
`2dfda949b915f713b7a261692be8bdd1b7cfcb3bbe3b5b2387d2b055f34d4227`

Repeated root predictions are byte-identical. The complete dataset hash manifest is
unchanged. Citation/time/resource-linkage validation accepts all 518 rows with zero
unknown-support citations. Semantic truth and exhaustive discovery remain separate
from those mechanical checks.

## Public-sample metrics: unchanged in both engines

| Metric | Submission baseline = final | Strict baseline = final |
| --- | ---: | ---: |
| Predicted / reference cases | 32 / 32 | 21 / 32 |
| Status accuracy | 1.00000000 | 0.65625000 |
| Step accuracy | 0.937823834197 | 0.611398963731 |
| Step precision | 1.00000000 | 1.00000000 |
| Step recall | 0.937823834197 | 0.611398963731 |
| Field accuracy | 0.879348630644 | 0.469282013323 |
| Sequence / exact-case accuracy | 21/32 = 0.65625 | 6/32 = 0.1875 |
| Missing / extra steps | 12 / 0 | 75 / 0 |
| Incorrect evidence references | 0 | 0 |

No hidden accuracy claim or sample-specific correction was introduced. No changed-case
list is needed: the exact per-case diff is empty. Proof of a retained behavioral
improvement is not applicable because there are none.

## Architecture and naming

`domain` owns immutable contracts and pure identity, correlation, temporal, policy,
planning and citation rules. `application` coordinates the distinct strict and submission
use cases over loaded inputs. `infrastructure` owns physical parsing, loading and
publication. `interfaces.cli` assembles file adapters and services. No domain module
imports paths, CSV, SQL execution, subprocesses or an outer layer. Evaluation labels
remain isolated from production by an enforced forbidden-import contract.

| Original module / responsibility | Final location |
| --- | --- |
| `phase2.py`, `Phase2Analyzer` | `application/evidence_association.py`, `EvidenceAssociationService` |
| `phase2_models.py` | `domain/association_models.py` |
| `phase3.py` | `application/temporal_diagnostics.py` |
| `prediction.py` orchestration / writing | `application/strict_audit.py` / `infrastructure/serialization/prediction_artifacts.py` |
| `submission.py` | `application/submission_service.py` plus `submission/evidence.py`, `workflow.py`, `records.py` |
| Submission models / inventories / vocabulary | `domain/submission_models.py`, `snapshot_inventory.py`, `submission_semantics.py` |
| `ingestion.py` | `infrastructure/ingestion/dataset_loader.py`, `parsers/documents.py`, `domain/dataset.py` |
| `output.py` | `domain/output_contract.py`, `citation_validation.py`, `infrastructure/serialization/csv_output.py` |
| `temporal.py` | `application/temporal_service.py`, `domain/state_selection.py`, `snapshot_coverage.py` |
| `temporal_adapters.py` | Pure `domain/record_interpretation.py`, `observation_clocks.py`; format adaptation in application |
| `extraction.py`, `sql.py`, `ocr.py`, `csvio.py` | `infrastructure/parsers/structured.py`, `sql_snapshot.py`, `image_ocr.py`, `serialization/csv_records.py` |
| Shared parser schema constants | `domain/catalog.py` |
| `abstention.py` | `application/abstention_diagnostics.py`, `domain/diagnostic_models.py` |
| `identity.py`, `policy.py`, `planning.py`, `correlation.py`, `workflow.py` | Explicit domain modules; workflow renamed `workflow_attribution.py` |

Historical `phase2` and `phase3` CLI commands and established reason strings remain
compatible. There are no phase-named Python modules, catch-all utility packages,
compatibility re-export chains or circular imports.

The 216-line correlation closure became a private case search with ordered seed,
trace, reference, resource-version and bundling stages. Submission's former combined
predictor now composes three collaborators; its 81-line case algorithm separates
resource assessments, ambiguous-status risks and row construction. Positional mutable
assessment arrays became a typed dataclass. Workflow matching separates primary,
direct-report and downstream assignments. Temporal analysis separates collection,
per-scope selection and bundle construction. Record interpretation separates presence,
flow and restore semantics. Process-wide listing caches became index-owned cached
properties, preserving their lifetime and lookup behavior without retaining datasets.

Larger schema/policy dispatch and diagnostic assembly functions remain where one
coherent decision requires related evidence and uncertainty reasons. Their invariants
are documented and domain signatures are checked; they are not replaced by generic
factories or speculative interfaces. Public API docstrings were added with an AST
comparison proving executable structure and CLI module descriptions unchanged.

## Quality and test gates

- `uv sync --frozen`: passed; synchronized lockfile, editable package and pip fallback.
- `uv run python -m pytest -q`: **527 passed**. The original 499 parametrized scenario
  identities remain present, including an explicit manifest check after file moves.
- `uv run ruff check .`: passed with correctness, import sorting, modernization,
  bugbear, comprehensions and simplification rules.
- `uv run ruff format --check .`: passed for all configured project sources.
- `uv run mypy`: passed for all 60 configured runtime/evaluation/script targets.
  Every domain function requires annotations and parameterized collections; implicit
  Any returns are rejected. Outer-layer raw JSON diagnostics and some parser callbacks
  are body-checked without universal strict-call enforcement. No package exclusions,
  unchecked casts or `type: ignore` were added.
- `uv run lint-imports`: **2 contracts kept, 0 broken**: inward layer dependencies and
  production/evaluation isolation. Three architecture tests additionally enforce
  acyclic imports and domain/application boundaries.
- Default prediction, full validation, both sample engines and all captured CLI modes:
  passed with the expected exits (strict full publication remains exit 2).
- Packaging and independent extracted-environment checks passed. Dataset, outputs,
  environments, caches, diagnostics, credentials, transcript and nested archives are
  excluded from source archives.

Tests now live in `unit/domain`, `unit/application`, `unit/infrastructure`, `integration`,
`regression` and `e2e`. Synthetic builders are independent fixtures rather than imports
from other tests. Seven golden tests pin full submission bytes, all strict decisions,
confidence, both sample metric sets, input bytes and original collection. Eighteen
comparator tests ensure every step field, order, status, abstention, confidence and
metric difference is detected even if a stored CSV hash was not updated.

## Remaining uncertainty and technical debt

The baseline's inference assumptions are unchanged: submission may use timing-based
ownership, snapshot omission and later identity links; strict audit continues to
abstain. There are still 12 missing public-sample steps, 138 cases with low-confidence
resources and 154 strict abstentions. One submission status depends on ambiguous
attribution, exactly as before. These require separately evidenced correctness work,
not snapshot updates disguised as structural refactoring.

Exact regression depends on unchanged input bytes and the same OCR environment. The
reference has all 94 manifest files parsed. Missing or different Tesseract extraction
can change evidence and must be investigated. There is no mandatory model API and
runtime model usage remains zero. Application services construct stable pure domain
collaborators; injection is reserved for a real alternate implementation.

## Final distributable source tree

Root configuration: `pyproject.toml`, `uv.lock`, `.python-version`, `README.md`.
Generated `output.csv` and `code.zip` remain ignored; `log.txt` is a separate transcript.

```text
|-- code/
|   |-- evaluation/
|   |   |-- __init__.py
|   |   |-- evaluation_report.md
|   |   |-- failures.py
|   |   |-- main.py
|   |   |-- scoring.py
|   |   `-- usage_report.md
|   |-- ghost_audit/
|   |   |-- __init__.py
|   |   |-- application/
|   |   |   |-- __init__.py
|   |   |   |-- abstention_diagnostics.py
|   |   |   |-- evidence_association.py
|   |   |   |-- model_port.py
|   |   |   |-- observation_interpretation.py
|   |   |   |-- strict_audit.py
|   |   |   |-- submission/
|   |   |   |   |-- __init__.py
|   |   |   |   |-- evidence.py
|   |   |   |   |-- records.py
|   |   |   |   `-- workflow.py
|   |   |   |-- submission_service.py
|   |   |   |-- temporal_diagnostics.py
|   |   |   `-- temporal_service.py
|   |   |-- domain/
|   |   |   |-- __init__.py
|   |   |   |-- association_models.py
|   |   |   |-- catalog.py
|   |   |   |-- citation_validation.py
|   |   |   |-- correlation.py
|   |   |   |-- dataset.py
|   |   |   |-- diagnostic_models.py
|   |   |   |-- evidence_index.py
|   |   |   |-- identity.py
|   |   |   |-- intent.py
|   |   |   |-- models.py
|   |   |   |-- observation_clocks.py
|   |   |   |-- output_contract.py
|   |   |   |-- planning.py
|   |   |   |-- policy.py
|   |   |   |-- policy_models.py
|   |   |   |-- record_interpretation.py
|   |   |   |-- snapshot_coverage.py
|   |   |   |-- snapshot_inventory.py
|   |   |   |-- state_selection.py
|   |   |   |-- submission_models.py
|   |   |   |-- submission_semantics.py
|   |   |   |-- temporal_models.py
|   |   |   |-- time.py
|   |   |   `-- workflow_attribution.py
|   |   |-- infrastructure/
|   |   |   |-- __init__.py
|   |   |   |-- ingestion/
|   |   |   |   |-- __init__.py
|   |   |   |   `-- dataset_loader.py
|   |   |   |-- parsers/
|   |   |   |   |-- __init__.py
|   |   |   |   |-- documents.py
|   |   |   |   |-- image_ocr.py
|   |   |   |   |-- sql_snapshot.py
|   |   |   |   `-- structured.py
|   |   |   `-- serialization/
|   |   |       |-- __init__.py
|   |   |       |-- csv_output.py
|   |   |       |-- csv_records.py
|   |   |       `-- prediction_artifacts.py
|   |   `-- interfaces/
|   |       |-- __init__.py
|   |       `-- cli.py
|   |-- main.py
|   |-- package_submission.py
|   |-- package_traces.py
|   |-- regression.py
|   |-- requirements.txt
|   `-- tests/
|       |-- __init__.py
|       |-- conftest.py
|       |-- e2e/
|       |   |-- __init__.py
|       |   `-- test_submission.py
|       |-- fixtures/
|       |   |-- __init__.py
|       |   |-- audit_cases.py
|       |   |-- baseline_contract.json
|       |   |-- evidence_cases.py
|       |   |-- identity_cases.py
|       |   |-- output_cases.py
|       |   `-- paths.py
|       |-- integration/
|       |   |-- __init__.py
|       |   |-- test_citation_registry.py
|       |   |-- test_dataset_ingestion.py
|       |   |-- test_evidence_association.py
|       |   |-- test_evidence_recovery.py
|       |   |-- test_output.py
|       |   |-- test_packaging.py
|       |   |-- test_strict_audit.py
|       |   `-- test_temporal_reconstruction.py
|       |-- regression/
|       |   |-- __init__.py
|       |   |-- test_adversarial_evidence.py
|       |   |-- test_architecture.py
|       |   |-- test_golden_master.py
|       |   `-- test_ownership_and_cutoffs.py
|       `-- unit/
|           |-- __init__.py
|           |-- application/
|           |   |-- __init__.py
|           |   |-- test_evaluation.py
|           |   |-- test_regression_comparison.py
|           |   `-- test_submission_records.py
|           |-- domain/
|           |   |-- __init__.py
|           |   |-- test_correlation.py
|           |   |-- test_identity.py
|           |   |-- test_intent.py
|           |   `-- test_time.py
|           `-- infrastructure/
|               |-- __init__.py
|               |-- test_evidence_parsers.py
|               `-- test_log_formats.py
`-- docs/
    |-- architecture.md
    |-- baseline.md
    |-- data-flow.md
    |-- development.md
    |-- evidence-model.md
    |-- refactor-report.md
    `-- testing.md
```


## Extracted archive and pip fallback: passed

The source archive contains 115 entries, including all runtime modules, tests,
non-predictive contract fixtures, seven developer documents and both required
archive-root reports. CRC and every archived source byte were verified. A rebuild
from the extracted tree was byte-identical to the archive tested.

A clean extracted uv environment passed frozen sync, all **527 tests**, Ruff,
format checking, all 60 mypy targets and both import contracts. Its own package
origin was asserted inside the extracted directory, with PYTHONPATH and inherited
VIRTUAL_ENV removed. Full prediction, 518-row validation and public evaluation
passed. Strict publication returned the expected 2 and preserved the full output.

A separate clean pip-only environment installed `code/requirements.txt`, imported
code from the extracted source, and produced and validated byte-identical output.
Ruff and mypy were confirmed absent from that runtime environment. Neither check
used an editable installation of the original checkout. The dataset remained
external and read-only throughout.

Independent final integrity checks covered 1,102 cited steps: **0 unknown-support
citations, 0 nonexistent resources and 0 unsupported system/resource pairs**.
The source/report ZIP is deterministic and is rebuilt after recording these results;
its runtime and test entries are checked against the already executed archive.
Detailed machine-readable evidence is in `../.ghost-audit-release-check/verification.json`
and `../.ghost-audit-final-validation/integrity.json`.
