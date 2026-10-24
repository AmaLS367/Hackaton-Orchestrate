# Phase 1 foundation evaluation

No independent audit predictions or submission output have been produced. Case-level
deletion-status accuracy, step accuracy, field accuracy, sequence accuracy, and exact-case
accuracy on the public samples are **not yet measured**. These metrics must be reported
from independent engine predictions in a later phase. Hidden evaluation labels are not used.

The provided 32 sample answers pass strict schema validation and exact sample request
coverage. This is a reference-contract check, not 100% prediction accuracy.

Validation used Python 3.12 with Pydantic v2, pytest, and pypdf. The complete corpus loads
518 evaluation requests and 94 evidence files: 83 parsed and 11 images deferred. It yields
9,690 indexed observations, including identity history and activity claims. SHA-256 checks
confirm all 103 dataset files remain unchanged. No root prediction output was created.
The final `python -m pytest -q` run passed **96 tests**.

## Local metric definitions

The testing-only scorer evaluates every reference case, including missing predictions:

- Status accuracy: matching deletion statuses / reference cases.
- Step accuracy: multiset matches of six step fields excluding `step_no`, divided by the
  sum over cases of `max(predicted step count, reference step count)`.
- Step precision and recall: the same matched-step count divided by predicted and
  reference step counts, respectively.
- Field accuracy: matching fields in position-aligned steps / seven times the sum of
  maximum step counts. Missing and extra steps contribute seven incorrect fields each.
- Sequence accuracy: cases whose complete ordered step arrays match / reference cases.
- Exact-case accuracy: cases whose status and ordered steps match / reference cases.

When no steps exist on either side, step/field metrics equal one only if every reference
case was supplied. Otherwise a zero denominator scores zero. Unknown and duplicate case
IDs are rejected. These transparent local metrics do not claim to reproduce the hidden grader.

## Participant-created evaluation cases

These fictional cases are executable in `code/tests/test_evaluation.py`; their constructed
answers test the scorer, not the unimplemented audit engine:

1. `fictional_export_only`: a valid NOT_APPLICABLE row with no steps. Matching it yields
   status, step, and sequence accuracy of 1. Output-model tests reject nonempty steps.
2. `fictional_deletion`, incorrect citation: one COMPLETE verification has the correct
   resource and operation but cites `wrong_file`. Status accuracy is 1, field accuracy
   is 6/7, and step, sequence, and exact-case accuracy are 0.
3. `fictional_deletion`, missing prediction: no row is supplied for a reference case.
   Missing-case count is 1; status, step, and field accuracy are 0. Nothing is filled in.

Additional temporal/provenance cases cover nested future observations, independent sibling
snapshot scopes, offset normalization, business deadlines, and log trace collisions. SQL
tests cover empty primary tables alongside populated replicas, embedded JSON, snapshot
scope times, and blocked external database/extension operations. PDF tests cover both
extractable text and blank pages requiring OCR. The full participant corpus is ingested
and indexed in integration tests; repeated case lookups are checked to perform no file I/O.

## Failures found and improvements

- Initial restricted SQL execution rejected indexes created by the supplied snapshots.
  The in-memory authorizer now permits table/index construction and reindexing, while
  continuing to reject ATTACH, extension loading, writable schema, and virtual tables.
- A test helper raised KeyError before testing an unknown operation. It now passes the
  invalid value to Pydantic so rejection is exercised at the actual schema boundary.
- Scoped extraction keeps future sibling snapshots from delaying unrelated records;
  future record observations cannot borrow an earlier envelope as a valid citation.

All predictions, semantic policy correctness, remediation dependencies, and final sample
accuracy remain unmeasured. Image extraction and semantic document interpretation are
unfinished and must be addressed before claiming complete evidence coverage.
