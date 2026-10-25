# Data flow

1. The terminal interface resolves the dataset location. The ingestion adapter opens
   only request CSVs, identities, audit history, activity, rules and the evidence manifest.
   Both participant request files supply workflow competitors; only the selected file
   supplies prediction requests. Public answers never enter this path.
2. Parsers read each manifest file once per load. They preserve participant citation IDs,
   file digests, source/capture clocks, physical tables, logical collections, raw text
   and locators. Restricted SQL executes in an in-memory connection. OCR is optional.
3. A domain `Dataset` holds the extracted values and complete citation registry,
   including deferred files. `EvidenceIndex` supports identifier/resource/system/citation
   lookups and scoped trace expansion without reopening evidence. Snapshot caches live
   on that index and disappear with it.
4. The strict use case classifies intent, resolves cutoff-visible identity aliases and
   associates evidence through bounded links. Timing candidates remain potential until
   independently anchored. The temporal service checks link availability, interprets
   readbacks and builds separate histories for each physical scope.
5. Strict policy evaluation distinguishes unknown applicability from compliance. Planning
   emits a grounded official row or keeps an undecidable case with blockers. Publication
   requires every selected request to have a row and all citation checks to pass.
6. The submission use case independently indexes identifiers and ownership facts, assigns
   uniquely constrained workflow batches, gathers record and inventory facts and chooses
   the best-supported official result. It records ambiguous candidates and low-confidence
   resources. It never fabricates a resource or evidence ID to fill a missing answer.
7. The interface writes strict diagnostics on every prediction run. Default publication
   writes submission rows, after full validation, through a temporary file and atomic
   replacement. Strict publication returns 2 and preserves the destination if abstentions
   or validation errors remain. Rows and step arrays use deterministic canonical order.
8. The separate evaluation CLI obtains independent sample predictions, then reads public
   reference answers and scores status, unordered steps, ordered fields and sequences.
   Missing strict predictions count against all reference cases.

`validate-output` proves schema, coverage, citation availability and resource linkage.
It explicitly does not certify the semantic truth of a state claim or exhaustive
resource discovery. Those limitations remain visible in diagnostics.
