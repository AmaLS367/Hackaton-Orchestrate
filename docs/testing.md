# Testing and regression

Tests are collected from the repository root by `uv run python -m pytest -q`.
The suite groups isolated domain/application/infrastructure checks, integrations,
adversarial regressions and full submission end-to-end checks. Shared synthetic
builders live in `code/tests/fixtures/`; conftest supplies reusable datasets and rules.
No production module imports test fixtures or public sample answers.

The original 499 parametrized scenarios remain protected by a collection manifest,
including scenario names and parameter IDs. File moves and the explicitly recorded
semantic renames do not remove their coverage. New architecture tests check the whole
module graph for cycles, domain I/O dependencies and application adapter dependencies.
Import-linter separately enforces the configured layer and evaluation-isolation contracts.

## Public samples

The evaluation CLI runs independent predictions before opening public labels. Its
status, step precision/recall, positional field accuracy, sequence and exact-case
metrics measure different properties. Strict abstentions count as missing predictions,
not as excluded cases. Three original independent custom evaluation cases exercise
non-deletion, wrong citations and missing predictions; adversarial synthetic pipeline
cases cover ownership, retention, replicas, unavailable evidence, filters and OCR.

## Golden master

Before refactoring, all original tests, supported CLI modes, full strict/submission
runs and public sample metrics were captured outside the checkout. The original ignored
CSV was protected before it could be replaced. See [baseline](baseline.md).

`code/regression.py` refuses to replace a completed capture. A new candidate capture
compares exact CSV bytes and SHA-256, every case/status/ordered seven-field step,
strict decisions and abstentions, submission attribution and low-confidence resources,
all sample metrics, CLI exits/results and hashes of every participant input. Timing
fields and machine-specific artifact paths are normalized; real decision differences
are not. `diff.json` records structured per-case and diagnostic differences, and exit 1
means the equivalence gate failed.

Portable fixture tests exercise the comparator itself, including changed order,
resource/citation values, abstentions and confidence. Full-dataset golden checks use
only regression artifacts, never input to production prediction. The exact baseline
profile requires unchanged input bytes and the same OCR extraction environment.
Missing/different OCR must be reported as environment drift, not hidden by updating
expected output. The external protected capture remains the full source of regression
truth; no participant dataset or prediction records are committed as a test snapshot.

Run affected tests while editing. Once a structural stage is ready, freeze runtime
sources, run the full suite and static gates, then capture/compare both engines. Finish
with full default prediction, citation validation, evaluation and deterministic package
checks. Validate extracted code using a fresh runtime environment, so the editable
checkout cannot hide a missing module in the archive.
