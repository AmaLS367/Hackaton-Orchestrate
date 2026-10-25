# Structural-refactor baseline

The reference implementation is commit `4476d2605a45186e27eba709262db7869a1c7e76`
on `master`. The checkout was clean before the session log was appended. No additional
commits or participant dataset changes preceded the capture.

An existing ignored `output.csv` was copied to a separate directory **beside** the
checkout before running any prediction. The capture directory is local, never included
in Git or `code.zip`. It also contains a fresh output, parsed ordered per-case steps,
strict decisions and abstentions, submission confidence diagnostics, all sample
metrics, CLI transcripts/exit codes, test collection/results, source interface/import
inventory and SHA-256 hashes of every participant input.

Use `code/regression.py` to reproduce the capture or compare another revision:

```text
uv run python code/regression.py ../baseline
uv run python code/regression.py ../candidate --baseline ../baseline
```

Capture refuses to overwrite an existing `snapshot.json`. Keep the original baseline
directory outside the checkout and retain its `original-output.csv`. The comparator
checks the CSV hash, every status and ordered seven-field step array, strict decisions,
abstentions, submission attribution/confidence, sample metrics, deterministic CLI
results and the complete input manifest. Only elapsed clocks and artifact-directory
paths are normalized. Source paths, test node names, help text and archive bytes are
allowed to change structurally; behavioral command exit codes remain checked.

An unexpected difference produces `diff.json` and exit 1. Do not update the protected
baseline to hide differences. Investigate them and restore structural equivalence, or
isolate an evidence-backed correction with its own tests and commit.

## Measured reference

- Original tests: **499 collected, 499 passed**.
- Full submission: **518 cases**, **152 COMPLETE**, **356 INCOMPLETE**,
  **10 NOT_APPLICABLE**, **3,071 steps**.
- CSV SHA-256: `2dfda949b915f713b7a261692be8bdd1b7cfcb3bbe3b5b2387d2b055f34d4227`.
- Strict engine: **364 predictions** (22 COMPLETE, 332 INCOMPLETE,
  10 NOT_APPLICABLE), **154 abstentions**, no validation errors. Its full publication
  command returns 2 and preserves any existing destination.
- The public sample and remaining CLI results are retained in the protected capture;
  final measured comparisons are documented in the release report.
- Public samples: status 32/32, exact/sequence 21/32, step precision 1.0,
  recall/step accuracy 0.9378238341968912, field accuracy 0.8793486306439674;
  12 missing steps, zero extra steps, zero incorrect evidence references.

Public interfaces before refactoring include the `code/main.py` commands `predict`
(also the default), `inspect`, `validate-output`, `phase2`, `phase3`, their sample,
single-case and strict options; `code/evaluation/main.py` independent-file, reference
schema and both engine evaluation modes; and the submission and trace packaging
scripts. Python interfaces are inventoried in the capture rather than preserved by
chains of compatibility re-exports. The supported external contract is the CLI.
