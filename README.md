# HackerRank Orchestrate - October 2026

## Ghost Data Still Exists

Build an AI agent that audits whether a user's personal data was actually deleted.

A deletion workflow may report **Complete** while data still exists in databases, logs, support attachments, exports, search indexes, archives, or backups. Sync and restore processes may also bring deleted data back.

For each request, the agent must first determine whether deletion was actually requested. It then returns `COMPLETE`, `INCOMPLETE`, or `NOT_APPLICABLE`, reports any remaining data or recreation risk, and produces the ordered remediation and verification steps required to finish an authorized deletion safely.

Read [`problem_statement.md`](./problem_statement.md) for the complete challenge contract.

## Implementation

The deterministic offline pipeline implements intent, historical identity resolution,
correlation, temporal reconstruction, all 15 supplied policies, remediation, verification,
and validated serialization. Dataset files are read only. Unsupported cases cause explicit
abstentions in diagnostics; a full submission is written only when every request has a
grounded prediction. Current measured results and blockers are in
[`code/evaluation/evaluation_report.md`](./code/evaluation/evaluation_report.md).

## Phase 5: evidence recovery

Phase 5 keeps the Phase 1–4 pipeline and recovers evidence it previously could not use.
On the 32 public samples, status accuracy rises from 17/32 to **32/32**, step recall from
57.5% to **92.2%** at **100%** precision, and exact cases from 4/32 to **19/32**. On the full
set, abstentions fall from 172 to **6** (151 COMPLETE, 351 INCOMPLETE, 10 NOT_APPLICABLE
grounded rows). `output.csv` is still withheld because six image-only cases lack sufficient
or consistent evidence. Details: [`code/evaluation/evaluation_report.md`](./code/evaluation/evaluation_report.md).

- `workflow.py` attributes `deletion_worker` events to the request whose batch produced
  them. A primary-profile deletion must fall in the batch window before `reported_at`
  and report a result consistent with the request's status. Exact-identity owners
  visible at the audit exclude other subjects, and unique assignments eliminate rivals
  (sample and evaluation requests compete because they share the stream). Ambiguous
  profiles are never named; when every candidate is proven absent, the deletion is
  verified without a step for the profile. A window holding more profiles than known
  requests disables per-resource attribution there.
- Linkage uses each observation's own clock (`linkage_time`). An earlier snapshot packaged
  in a later export can identify a record, but Phase 3 marks it linkage-only: it is never
  cited and never sets a state. Same-system resource IDs join unless an explicit logical
  collection differs. A subject's earlier request keeps evidence observed by its audit.
- Phase 3 takes the newest supported read, preferring precise reads only among ties. A
  confirmed record never read in a citable state is `ABSENT` when the latest complete
  listing of its collection (SQL table or JSON snapshot envelope) omits it; the output
  validator accepts that citation only for `VERIFY_RECORD_ABSENT` (`resource_support='coverage'`).
- Policy types each resource from all its confirmed rows (record type, collection,
  export container, read event, document/workflow hints, then the scoped system). The
  freshest surface decides, so a stale replica cannot outlive a newer read. Backups carry
  only the restore obligation. Without an explicit supplied fact, support conversations
  are shared (rule 05), confirmed attachments belong only to the subject (rule 06), and
  security/legal records without a deadline are preserved (rules 12/13); each default is
  named in the assessment reasons, and explicit facts always win. Redaction/anonymization
  is proven by observed nulled identifier fields with no exposed value.
- Documents: PDFs yield one observation per explicit or catalogued resource with the whole
  document's identifiers. Images use optional local Tesseract OCR (`ocr.py`, no Python OCR
  package; set `GHOST_AUDIT_OCR=0` to disable or `GHOST_AUDIT_TESSERACT` to locate the binary).
  OCR keeps only catalogued resources and the lines naming them; a misread identifier
  matches nothing and leaves the link unconfirmed. Without Tesseract, images stay deferred.
- Systems/collections: collection-only exports map to their schema's system,
  `support_replica` reports on `support_platform`, and envelope collections are not
  inherited by records that name another system.

No external model is called at runtime; Gemini was not configured (no key) and was not needed.

### Install and test

Use Python **3.12**. From the repository root, on Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r code/requirements.txt
python -m pytest -q
python code/main.py inspect
python code/evaluation/main.py --check-reference
```

On macOS/Linux, create the environment with `python3.12 -m venv .venv`, activate it
with `source .venv/bin/activate`, then run the same `python` commands above.
Installation requires obtaining the dependencies; all subsequent ingestion, validation,
evaluation, and tests run offline without credentials or an external AI service.

To score an independently generated **sample** prediction file:

```text
python code/evaluation/main.py --predictions path/to/sample_predictions.csv
```

Missing sample cases count as errors; unknown or duplicate case IDs are rejected.
`--check-reference` checks the 32 public sample rows against the schema and request IDs;
it does not measure prediction accuracy. The scorer refuses the reference file itself
as the prediction input. Only the testing-only `code/evaluation/` package reads sample answers.

To check a generated full-dataset output (exact request coverage, ordering, schema, and citation times):

```text
python code/main.py validate-output --predictions output.csv
```

Add `--samples` for a complete sample prediction file. Default dataset paths are resolved
relative to the repository, independently of the working directory. `--dataset PATH`
can select another participant dataset directory. Run pytest from the repository root.

### Architecture and extension points

- `code/ghost_audit/models.py`, `time.py`, `csvio.py`: strict Pydantic v2 input contracts,
  exact CSV headers, unique row IDs, and timezone-aware timestamps normalized to UTC.
- `extraction.py`, `sql.py`, `ingestion.py`: parse JSON, SQL, logs, text, PDFs, and CSV inputs
  once per dataset load. SQL runs only in memory with restricted commands and an instruction
  budget. Empty tables, replica names, embedded JSON, and original field values are preserved.
- Log adapters support bracket, key-value, timestamp-plus-JSON, plain-level, timestamp-first
  and standard RFC5424-like syslog, pipe-delimited service logs, and escaped cloud runtime
  messages. They retain raw lines and source locations, decode quoted fields, preserve
  unknown fields and scalar types, and correlate lookups through file/service-scoped traces.
- Every observation carries its participant evidence ID, file path, SHA-256 digest,
  JSON path/table row/text line/PDF page locator, manifest origin/capture time, and source
  timestamps. Explicit systems and collection names remain attached to resource references.
  Unknown systems remain unknown; resource-ID prefixes are not used to guess them.
  SQL resource references expose `physical_table` separately from `collection`; explicit
  logical `collection_name` values (including decoded `record_json`) take precedence for
  later classification. Replica table locators, origin systems, and snapshot times remain intact.
- `EvidenceRegistry` in `index.py` registers every manifest file, including deferred images
  and PDFs, plus activity and audit IDs. Entries contain source path/origin, capture time,
  and parsing status. Ingestion exposes `dataset.registry`; pass it to
  `EvidenceIndex(dataset.observations, registry=dataset.registry)` for complete citation coverage.
  Existing observation-only index construction remains supported, but cannot know about
  files without observations. Current identity snapshot user IDs are not citation IDs.
- `index.py`: reusable indexes for identifier values (including historical CSV changes),
  resources, systems, evidence IDs, and file/service-scoped log traces. Lookup performs
  no file parsing. Email matching is case-insensitive; phone matching removes presentation
  punctuation. Retrieval produces candidates, not confirmed identity or state decisions.
- Cutoff filtering requires the manifest capture time and all applicable enclosing/record
  source timestamps to be at or before `audit_at`. Nested snapshots keep their own scopes.
  Expiration, retention, and scheduled deadlines remain business facts and do not delay
  evidence availability. Activity results are tagged as claims. No state is inferred from an
  operation result; Phase 5 infers absence only from a complete listing omitting a confirmed,
  never-read record, and links (not cites) facts by their own observation clock.
- `output.py`: strict operation/phase/state combinations, citation placement, nonempty
  authorized outputs, exact request coverage, duplicate rejection, and deterministic CSV/JSON
  serialization. `canonical_steps` explicitly sorts by the official operation order, then
  system/resource, and renumbers. Readers reject incorrect order rather than silently fixing it.
  Citation validation distinguishes unknown IDs, future evidence, and evidence exclusively
  about unrelated resources/systems. It accepts grounded negative lookups without requiring
  a physical record, follows scoped traces, and rejects resource links available only after
  `audit_at`, even when an earlier document envelope exists.
  `validate_output` returns `CitationCheck` diagnostics outside the output schema:
  `resource_support` is `linked` or `unknown`, and `state_support` remains `unverified`.
  Deferred evidence can be structurally valid while its resource support is unknown;
  the CLI reports that count. A resource link never proves the claimed deletion state.
- `code/evaluation/scoring.py`: isolated local sample metrics and custom test cases.
  `code/evaluation/evaluation_report.md` defines their formulas and current limitations.
- `llm.py`: a small provider-agnostic protocol with response and token-usage metadata.
  Future Gemini/free-provider implementations can conform to it. No provider SDK, adapter,
  paid account, API key, or remote model call is part of Phase 1.

Images and PDF pages without extractable text are explicitly marked `deferred`, never treated
as empty/compliant evidence. (Phase 5 adds catalogued OCR and document-level PDF observations.)
Phase 3 implements temporal reconstruction; Phase 4 applies policy and constructs predictions.

## Phase 4: predictions and honest abstention

With the Python 3.12 environment activated, the official invocation is:

```text
python code/main.py
```

It processes all 518 requests. Exit **0** means root `output.csv` was written after strict
validation. Exit **2** means some cases could not be substantiated: the output is neither
created nor replaced, and any older file is stale. No fourth status or placeholder row enters
the submission. Inspect `code/evaluation/full_prediction_diagnostics.json` for the summary,
each case's decision or abstention, policy assessments, supporting evidence, and blockers.
These generated diagnostic artifacts are ignored by Git.

Separate sample production and evaluation commands:

```text
python code/main.py predict --samples
python code/evaluation/main.py --run
python code/evaluation/main.py --run --json
```

Sample production attempts `sample_predictions.csv` and writes
`code/evaluation/sample_prediction_diagnostics.json`; it has the same all-cases publication
gate and never reads reference answers. `--run` independently attempts every sample and
scores against all 32 reference rows, counting abstentions as errors. The evaluation harness
alone reads `sample_output.csv`. Use `--predictions PATH` to select the production destination
or score an existing independent sample CSV with the evaluation CLI. `--diagnostics PATH`
selects a diagnostic JSON destination. Artifacts cannot overwrite files inside the dataset.

`policy.py` maps explicit record types, known system/collection pairs, service-export object
schemas, and readback events to CSV policy rules. It evaluates shared context, subject-only
attachment ownership, attribution, email exposure, retention deadlines, legal holds, restore
configuration, and deleted tombstones. Missing conditions and unknown schemas remain unknown.
Historical condition evidence is separate from evidence proving the selected record state.
Full identifying-field coverage is required for null-only anonymization; a lone null email
is insufficient. Tombstones preserve the subject's stable reference; security and legal records
are never deleted because of a user reference.

`planning.py` deduplicates logical operations across separately assessed physical scopes.
Flows and restores are secured before cleanup. Every incomplete plan verifies intended
final states, including retained records and process safety, using empty future citations.
Findings cite current violation evidence. Complete plans cite proven compliant states only.
Unknown retention applicability causes precautionary preservation checks in an independently
established incomplete case; it cannot prove compliance. Absent retained records require
investigation because the official operations include no safe record-recreation operation.

The official schema requires operation/system/resource order even between cleanup records.
When an explicit downstream-before-source dependency contradicts that order, Phase 5 keeps the
official order and records the conflict in the case diagnostics. Unassigned images
do not block every case. Potential associations, snapshot gaps, claims, and unknown states cannot
establish violations. They can prevent `COMPLETE`; an independent proven violation still
establishes `INCOMPLETE`. A supported status with unresolved resources remains explicitly
flagged as a potentially incomplete plan. Discovery coverage is not a canonical label.
Retention or process-safety evidence alone cannot prove that deletion occurred: a complete
case also requires a proven compliant deletion, redaction, or anonymization record state.

`prediction.py` reuses the existing shared index and Phase 2/3 boundaries. Each emitted row
passes the existing output validator plus parsed, resource-linked citation checks before
publication. Aggregate diagnostics include status/abstention counts, scoped policy violations,
operation counts, unsupported states, runtime, validation results, and zero offline model usage.
No new dependency or runtime AI provider is required. Detailed metrics and remaining Phase 5
priorities are recorded directly in the Markdown evaluation and usage reports.

## Phase 2: intent, historical identity, and evidence correlation

Phase 2 runs offline with the existing Python 3.12 dependencies. It produces typed evidence
bundles for later reconstruction, with no deletion-state verdicts or root `output.csv`.

```text
python code/main.py phase2
python code/main.py phase2 --samples
python code/main.py phase2 --case-id case_33
python code/main.py phase2 --samples --case-id case_02
```

Aggregate diagnostics contain distributions, counts, and case IDs without raw personal
information. A single-case command intentionally prints the detailed bundle and its fictional
source records. `--dataset PATH` works with these commands. Existing `inspect` and
`validate-output` commands retain their Phase 1 behavior.

- `intent.py`: deterministic action/object and follow-up verification rules, explicit negation,
  cancellation, marketing scope, access/export/correction/support exclusions, and conservative
  handling of hypothetical or quoted instructions. English, Spanish, French, Portuguese,
  Japanese, and Korean have practical rule coverage. Unsupported or ambiguous requests return
  `UNCERTAIN` with a fallback recommendation; confidence describes rule certainty, not a
  calibrated probability. Workflow status never determines intent. Future providers can consume
  the same `IntentResult`; no external provider is implemented or called.
  Past-tense negation and future approval conditions are handled explicitly. A personal history
  of deletion plus a request to check residual backups, replicas, archives, search indexes, or
  restored records authorizes an audit; generic policy questions do not.
- `identity.py`: reusable exact ownership indexes over snapshots and both audit-change values.
  `IdentityResolver.resolve(request)` returns `RESOLVED`, `AMBIGUOUS`, or `UNRESOLVED`, with
  candidates and aliases retaining original values, field, source, audit ID, event time,
  known validity boundaries, and active-at-cutoff status. Only facts available by `audit_at`
  participate. A future snapshot is excluded rather than assumed valid earlier. Old values
  prove an earlier relationship only once that change is available. Incomplete history may
  therefore remain unresolved. Names never establish ownership; hashes are never computed.
  Shared historical aliases remain collision risks even after reassignment.
- `correlation.py`: exact identifier anchors, one file/service-scoped trace hop, one explicitly
  supported resource-reference hop, then terminal collection of observations for established
  resources. Each accepted link retains the full chain of evidence IDs and observation locators.
  Automatic resource joins require a matching system and resource ID; an explicitly different
  logical collection or an ownership boundary prevents confirmation (Phase 5 no longer requires
  both sides to state a collection). Explicit cross-collection links need independently scoped references;
  ambiguous target collections stay potential. `related_system` takes precedence, while documented
  `relationship_direction` (or `direction`) values `upstream` and `downstream` select source and
  target systems respectively. An absent or unknown direction never defaults to the source.
  Unknown subjects in lookup selectors or mixed prose contaminate trace-only links; independently
  grounded direct links remain confirmed. Potential paths never seed confirmed expansion.
  There is no expansion by whole file, system alone, name, or newly found alias.
  SQL table/replica names, collections, payloads, timestamps, and source provenance survive intact.
- `phase2_models.py`, `phase2.py`: strict Pydantic bundles and reusable `Phase2Analyzer`.
  Bundles contain intent, resolved identity, aliases, confirmed/potential observations, resource
  references, evidence IDs, ambiguities, and available deferred file metadata. Unrelated
  observations are omitted and counted; `association_for` can query their explicit `UNRELATED`
  classification. All source observations stay in the shared index. Each confirmed resource
  is an association, not proof that it currently contains prohibited data.

Deferred images form an **unassigned candidate pool**, filtered by capture time. Their content
and subject have not been interpreted. Having available deferred files does not establish that
they concern a particular case. Parsed PDFs/text without grounded identifiers or supported
resource relationships can also need further interpretation. Mixed-subject records are handled
conservatively and can suppress valid links until stronger evidence exists; bounded expansion
can miss longer relationship chains. No absent row, workflow claim, or retrieval count establishes
deletion compliance.

The full run resolves all 518 request identities and classifies 508 deletion requests and 10
non-deletion requests, with no uncertain intents on this corpus. These are diagnostic results,
not accuracy measurements. Stabilization passes 293 tests and yields 2,100 confirmed observation
associations (previously 2,857): 905 joins lacking collection proof are downgraded, while 148
independently identified records with null/redacted subject fields are recovered. The current
test and diagnostic results, limitations, and preparation
for Phase 3 are documented in [`code/evaluation/evaluation_report.md`](code/evaluation/evaluation_report.md).

## Phase 3: temporal state reconstruction

```text
python code/main.py phase3
python code/main.py phase3 --samples
python code/main.py phase3 --case-id case_33
python code/main.py phase3 --samples --case-id case_05
```

These commands reconstruct observations at each request's `audit_at`; they do not apply
deletion policy, classify deletion completion, plan remediation, or write `output.csv`.
Aggregate output contains counts and case IDs without personal identifiers. Single-case
inspection includes detailed fictional field values and provenance. Existing CLI commands
and `--dataset PATH` continue to work.

The Phase 4 integration API reuses the existing loaded dataset and index:

```python
from ghost_audit.phase2 import Phase2Analyzer
from ghost_audit.temporal import TemporalStateEngine

phase2 = Phase2Analyzer(dataset)
engine = TemporalStateEngine(phase2.index)
state_bundle = engine.analyze(phase2.analyze(request))
diagnostic_json = state_bundle.model_dump_json(indent=2)
```

`TemporalStateEngine().analyze(case_bundle)` also accepts a standalone Phase 2 bundle.
Passing the existing index additionally validates evidence registration and anchor availability,
and exposes known SQL sibling-table coverage gaps. Analysis performs no file I/O or model calls.

- `temporal_models.py` defines `CaseStateBundle`, per-resource/source histories, timestamped
  observations, field representations, typed record/flow/restore selections, replica comparisons,
  unresolved facts, and supporting/conflicting evidence. The resolved identity and intent survive
  intact. Original provenance includes the evidence ID, locator, digest, capture and source clocks;
  Phase 2 correlation links retain the full ownership evidence chain.
- `temporal_adapters.py` interprets parsed JSON/SQL snapshots, completed resource lookups,
  service readbacks, field scans, connector configurations, and restore permissions. `NULL`,
  explicit redaction markers, stable references, and identifying values remain field facts.
  A tombstone with null identifiers remains an observed `PRESENT` record; nulls alone do not
  establish `REDACTED` or `ANONYMIZED`. Explicit state labels describe observations and can
  conflict with actual fields. Security/legal categories never imply compliance.
- `temporal.py` gates both observation and availability clocks. Snapshot observation times come
  from scoped capture clocks, independently of older row updates or later export packaging.
  Per-scope histories are chronological. The latest supported read wins; precise snapshots/resource
  reads outrank summary labels only at the same clock (Phase 5). Conflicting simultaneous direct observations
  remain `UNKNOWN`/`CONFLICTED`; a later resolution retains historical conflict evidence.
  Activity and operation results remain `CLAIM_ONLY` and cannot override direct contents.
- Known SQL schema families can equate logical collections across primary, read, regional,
  reporting, and failover tables. Explicit `collection_name` remains authoritative. Physical table
  and replica scope stay attached to each fact. Generic tables require explicit logical collection
  metadata. Potential associations never become proof, including potential replica records.
  A row without a collection joins its resource's single known collection (Phase 5); unspecified
  service surfaces are separated by origin and region, and policy uses the freshest surface.
- Scoped 404/zero-row resource lookups can establish absence. Search misses require explicit
  resource query scope; cache misses, failed reads, unavailable downloads, and missing SQL rows
  do not prove absence. Known sibling-table gaps are `UNKNOWN`, not synthetic deletion facts.
  Replica reports distinguish state disagreement, field disagreement, and coverage gaps, and
  indicate whether compared observations are contemporaneous.
- Flow activity and restore permission have independent selections. An existing archive can
  remain `PRESENT` with restoration `BLOCKED`; a restore authorization does not establish archive
  existence. A category label such as active backup does not establish restore permission.

The full run processes 518 requests (508 authorized), establishing record states in 498 cases.
Across 2,703 resource/source scopes it establishes 1,544 record states and leaves 1,159 unknown.
It observes 135 active flows and 29 allowed restore permissions. These are discovery coverage
counts, not prediction accuracy or policy violations. Eleven images remain deferred, and 504
authorized cases have unresolved evidence, ambiguity, or gaps. The full request set has no
supported replica disagreements; samples expose one failover/primary coverage gap. Synthetic
tests exercise explicit replica disagreements rather than promoting potential corpus evidence.

Phase 4 consumes these observations and independent scopes, checks `support`, unresolved states,
and replica comparisons, and retains the cited ownership chain. Its policy and planning modules
do not map presence, null identifiers, discovery counts, or an absence of conflicts directly
to compliance.

---

## Quick Start

Clone the repository and move into the project directory:

```bash
git clone https://github.com/AmaLS367/Hackaton-Orchestrate.git
cd Hackaton-Orchestrate
```

Start your AI coding tool from the **repository root** so it automatically reads [`AGENTS.md`](./AGENTS.md) and logs your session turns to `log.txt` in the root directory.

Build your solution in `code/main.py`, or use another language and document its setup and run command clearly in your README.

Your solution must:

- Read the input files from `dataset/`
- Generate one prediction row for every request in `dataset/deletion_requests.csv`
- Write the final predictions to `output.csv` in the repository root

Run the Phase 1 inspection entry point with:

```bash
python code/main.py inspect
```

The blank template at `dataset/output.csv` is provided as a reference. Your final generated file for submission must be the root-level `output.csv`.


## Dataset

All participant-facing files are in `dataset/`:

| File | Contents |
| --- | --- |
| `deletion_requests.csv` | 518 requests |
| `sample_deletion_requests.csv` | 32 sample requests |
| `sample_output.csv` | Correct sample answers |
| `user_identities.csv` | Current user identities |
| `user_audit_log.csv` | Historical identity changes |
| `system_activity.csv` | Activity across services and data processes |
| `deletion_rules.csv` | Required treatment for each data category |
| `evidence_files.csv` | Manifest of supplied evidence files |
| `output.csv` | Blank output template |

Evidence is stored under `dataset/evidence/` and may include PDFs, images, logs, JSON, plain text, or SQL snapshot exports. SQL captures may contain a primary database, regional replicas, a reporting replica, or a failover replica so replication drift can be investigated directly. The `.sql` files are readable as text and executable with SQLite.

Only `deletion_requests.csv` requires answers. The other files provide evidence and context.

---

## Output

Create `output.csv` with these columns in this exact order:

```text
case_id,deletion_status,steps_json
```

Produce exactly one row per request. `deletion_status` is `COMPLETE`, `INCOMPLETE`, or `NOT_APPLICABLE`. `steps_json` is an ordered JSON array containing findings, remediation actions, and verification checks. Use an empty array (`[]`) for `NOT_APPLICABLE`. Evidence references may be a `file_id`, `activity_id`, or `audit_id`. Determine the resource state at `audit_at` from the available evidence; reported workflow statuses and operation results are claims. Use `dataset/sample_output.csv` as the format reference.

The final file must contain 518 data rows sorted by `case_id` (plus the header row). The grader parses `steps_json` as JSON, so object-key order and whitespace do not matter; array order does. Order findings, remediation, and verification in that phase order. Within a phase, follow the operation order in the problem statement, then sort by `system_id` and `resource_id`.

---

## Evaluation

`output.csv` will be compared with hidden canonical answers. Scoring considers:

- deletion assessment accuracy;
- current and historical identity resolution;
- discovery of remaining data and recreation risks;
- correct policy application and evidence references; and
- completeness and ordering of remediation and verification steps.

Your `code.zip` must include:

```text
code/evaluation/evaluation_report.md
code/evaluation/usage_report.md
```

- `evaluation_report.md` must cover case, row, field, and sequence accuracy, at least three additional evaluation cases created by you, failures found, and improvements made.
- `usage_report.md` must cover the final full-dataset run, including model providers and names, model calls, input and output tokens, total and average tokens per request, and estimated total and per-request cost. Include per-model and overall totals when using multiple models.

**Important:** Place `evaluation_report.md` and `usage_report.md` inside `code/evaluation/` (matching `code/evaluation/main.py` in this starter layout), write your complete evaluation metrics, custom evaluation test cases, and token/cost breakdowns directly inside those Markdown files, and keep prompts in source code or Markdown files. Automated code evaluation ignores raw data files (`.csv`, `.tsv`, `.json`, `.jsonl`, `.sql`, `.log`), so content stored only in those formats will not be visible to the code judge or AI interviewer.

---

## Chat Transcript

This repository includes [`AGENTS.md`](./AGENTS.md), which instructs compatible AI coding tools to append conversation summaries to `log.txt` in the repository root:

| Platform | Path |
| --- | --- |
| macOS / Linux | `<repo root>/log.txt` |
| Windows | `<repo root>\log.txt` |

- Always launch your AI coding agent from the repository root (or explicitly ask it to read `./AGENTS.md` first) so every turn is logged to `log.txt` with the required `User Prompt`, `Agent Response Summary`, `Actions`, and `Context` sections.
- Upload `log.txt` directly as your `chat_transcript` submission on HackerRank.
- Do not include API keys, tokens, credentials, or secrets in prompts, code, configuration, or `log.txt`.

---

## Packaging `code.zip` and Submission

| Item | Description |
| --- | --- |
| `code.zip` | Runnable solution, prompts, configuration, `README.md`, and `evaluation/` reports |
| `output.csv` | One answer row for each of the 518 requests in `dataset/deletion_requests.csv` |
| `chat_transcript` | The root `log.txt` file generated by your coding agent |
| AI interview | Live explanation of your architecture, approach, and evaluation |

You may use any programming language, model, framework, or retrieval approach. Include clear setup and execution instructions in `README.md` inside `code.zip`.

To package `code.zip` from the repository root without bundling the dataset:

**macOS / Linux:**

```bash
zip -r code.zip README.md pyproject.toml code -x "*/__pycache__/*" "*/.venv/*" "*/venv/*" "*/node_modules/*" "*/.git/*" "*/.DS_Store"
```

**Windows (PowerShell):**

```powershell
Compress-Archive -Path README.md, pyproject.toml, code -DestinationPath code.zip -Force
```

When packaging `code.zip`:

- Keep your evaluation reports in `code/evaluation/` so they are bundled automatically with `code` (or add `evaluation` to the archive command above if you placed them in a top-level `evaluation/` directory).
- Do **not** include `dataset/`, virtual environments (`.venv`, `venv`, `node_modules`), or build caches (`__pycache__`). On Windows, keep `.venv` at the repository root (outside `code/`) and remove any `code/__pycache__` folders before running `Compress-Archive`.
- Do **not** include nested archives (`.zip`, `.tar`, `.gz`, `.tgz`, `.7z`, `.rar`) inside `code.zip` — submissions containing nested archive files will be rejected.

Before submitting, confirm that:

- `output.csv` has the exact header `case_id,deletion_status,steps_json` and contains all 518 data rows sorted by `case_id`;
- every `steps_json` value is a valid JSON array with consecutive step numbers starting at `1`;
- findings cite valid evidence IDs, and `COMPLETE` verification steps cite evidence proving the current state;
- proposed remediation and future verification steps use an empty `evidence_id` (`""`);
- `code.zip` includes your runnable code, `README.md`, `code/evaluation/evaluation_report.md`, and `code/evaluation/usage_report.md`;
- `log.txt` follows the `AGENTS.md` turn format and is uploaded to the `chat_transcript` slot; and
- no API keys, credentials, real personal data, or sensitive configuration values are included.
