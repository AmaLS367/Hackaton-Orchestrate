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

## Release lineage

Every row was reproduced by running that commit's `code/main.py` on the participant dataset
with Tesseract OCR. Only the prediction-changing commits are listed; the commits between
and after them restructure code, metadata, packaging and Docker support without changing
`output.csv`.

| Stage | Commit | COMPLETE / INCOMPLETE / NOT_APPLICABLE | Steps | `output.csv` SHA-256 |
| --- | --- | ---: | ---: | --- |
| Original submission baseline | `4476d26` | 152 / 356 / 10 | 3,071 | `2dfda949b915f713b7a261692be8bdd1b7cfcb3bbe3b5b2387d2b055f34d4227` |
| First temporal correctness fix | `2d85859` | 154 / 354 / 10 | 3,067 | `eada7a560b75e6acca66706444b19c6ee5b7b4d0cd5f3cb50cc13bdfaef43ea6` |
| Policy cutoff fix | `59ba4a1` | 154 / 354 / 10 | 3,067 | `807803941b11aa438f36365a98c77fcb9de447887fd830aba10ce9a2166343a5` |
| Support-category fallback | `bf707f8` | 154 / 354 / 10 | 3,067 | `1bc68692b30cfc7d23efb502c8ad6ba03bfecf75452415d11eae0d4639c3666c` |
| **Current accepted release** | `bf707f8` and later | **154 / 354 / 10** | **3,067** | `1bc68692b30cfc7d23efb502c8ad6ba03bfecf75452415d11eae0d4639c3666c` |

- Temporal fix (`2d85859`): latest temporal state per physical scope; exactly two rows change,
  case_86 and case_390, both INCOMPLETE → COMPLETE (152 → 154 COMPLETE, 356 → 354 INCOMPLETE,
  3,071 → 3,067 steps).
- Policy cutoff fix (`59ba4a1`): 9 case rows change, no status change; see
  `code/evaluation/policy_cutoff_differential.md`.
- Support-category fallback (`bf707f8`): 15 case rows change, no status change; see
  `code/evaluation/support_inference_differential.md`.
- Public-sample metrics are identical at all four stages: status 32/32, exact/sequence 21/32,
  precision 100%, recall 93.782%, field accuracy 87.935%, 12 missing and 0 extra steps.
- The strict engine is unchanged in the current release: 364 grounded predictions (22 / 332 / 10),
  154 abstentions, and the strict publication command exits 2.

## Measured reference (original submission baseline `4476d26`)

These figures are historical. They describe the baseline captured before the correctness
fixes above and do **not** describe the current release.

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
