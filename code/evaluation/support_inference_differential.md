# Support-category workflow fallback: differential

Baseline `7e890b2` (`80780394…`) → after (`1bc68692…`). All 518 cases compared on status, step
count, operation, state, system, resource, evidence and order.

- Cases changed: **15**. Status changes: **0**. Total steps: 3,067 → 3,067. Rejected inferences: 0.
- In each case only the named support resource changes, from `REPORT_EXPOSED_PII / REDACT_RECORD /
  VERIFY_RECORD_REDACTED` to `REPORT_REMAINING_RECORD / DELETE_RECORD / VERIFY_RECORD_ABSENT`. The
  finding keeps citing the same pre-audit readback.
- Public sample metrics and strict-engine decisions are unchanged.
- Every one of the 15 meets all of these conditions:
  - It has exactly one deletion-worker treatment, a `DELETE_RECORD` (result FAILED).
  - That operation lies between `requested_at` and `audit_at` and is uniquely assigned to this
    request's batch.
  - It has no time-valid record type, attachment or conversation evidence and no shared
    order/agent context.
  - The record names only the deletion subject.

| Case | Resource | Worker operation (time) | Finding evidence (captured) |
|---|---|---|---|
| case_47 | support_5742 | activity_3809 (2026-09-12T11:54) | evidence_94 (2026-09-26T10:38) |
| case_71 | support_1370 | activity_3505 (2026-08-29T09:38) | evidence_93 (2026-09-16T08:37) |
| case_95 | support_5750 | activity_3190 (2026-08-10T06:45) | evidence_89 (2026-09-01T05:33) |
| case_119 | support_9309 | activity_2979 (2026-07-27T11:52) | evidence_88 (2026-08-22T10:39) |
| case_131 | support_2315 | activity_3021 (2026-07-30T10:44) | evidence_87 (2026-08-17T09:42) |
| case_143 | support_6560 | activity_2992 (2026-07-28T08:59) | evidence_86 (2026-08-07T07:41) |
| case_179 | support_2283 | activity_2549 (2026-06-27T12:58) | evidence_84 (2026-07-23T11:43) |
| case_227 | support_5830 | activity_2360 (2026-06-14T07:49) | evidence_80 (2026-06-28T06:25) |
| case_251 | support_4541 | activity_2158 (2026-05-31T12:56) | evidence_78 (2026-06-18T11:44) |
| case_275 | support_3684 | activity_1860 (2026-05-12T09:40) | evidence_77 (2026-06-03T08:34) |
| case_287 | support_7432 | activity_1912 (2026-05-15T08:55) | evidence_76 (2026-05-29T07:43) |
| case_347 | support_9474 | activity_1446 (2026-04-15T09:38) | evidence_71 (2026-04-29T08:32) |
| case_431 | support_3615 | activity_806 (2026-03-02T08:51) | evidence_68 (2026-03-20T07:23) |
| case_443 | support_8341 | activity_771 (2026-02-28T06:43) | evidence_66 (2026-03-10T05:38) |
| case_527 | support_3896 | activity_142 (2026-01-15T13:15) | evidence_62 (2026-01-29T11:44) |

The category is a weak inference from a workflow claim. It is recorded as
`inferred_support_category:<resource>:<activity>` and the resource is listed as low-confidence in
`submission_diagnostics.json`. The operation never sets record state or completion.
