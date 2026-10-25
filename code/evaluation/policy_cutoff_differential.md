# Policy-cutoff differential: BASELINE → POST-P0

Baseline `2d85859` (`eada7a56…`) → post-fix (`80780394…`). All 518 cases were compared on
status, step count, operation, state, system, resource, evidence and order.

- Cases changed: **9**. Status changes: **0**. Total steps: 3,067 → 3,067.
- Status counts unchanged: 154 COMPLETE / 354 INCOMPLETE / 10 NOT_APPLICABLE.
- Public sample metrics and strict-engine decisions: unchanged.
- Only diagnostics changed: in case_67, case_72 and case_176, a future-only search resource is now
  UNKNOWN instead of COMPLIANT. No output row changed for these cases.

| Case | Resource | Category | Leaking evidence (available) | Time-valid evidence | Step change |
|---|---|---|---|---|---|
| case_61 (audit 2026-02-14T10:00) | support_001 | ATTACHMENT → MESSAGE | evidence_58 (2026-09-12T07:30) | none before audit_at | VERIFY_RECORD_ABSENT → VERIFY_RECORD_REDACTED |
| case_71 (audit 2026-09-16T09:00) | support_1370 | ATTACHMENT → MESSAGE | evidence_06 (2026-09-18T11:55) | evidence_93 (2026-09-16T08:37) | REPORT_REMAINING_RECORD/DELETE_RECORD/VERIFY_RECORD_ABSENT → REPORT_EXPOSED_PII/REDACT_RECORD/VERIFY_RECORD_REDACTED |
| case_119 (audit 2026-08-22T11:00) | support_9309 | ATTACHMENT → MESSAGE | evidence_11 (2026-08-24T13:56) | evidence_88 (2026-08-22T10:39) | REPORT_REMAINING_RECORD/DELETE_RECORD/VERIFY_RECORD_ABSENT → REPORT_EXPOSED_PII/REDACT_RECORD/VERIFY_RECORD_REDACTED |
| case_131 (audit 2026-08-17T10:00) | support_2315 | ATTACHMENT → MESSAGE | evidence_12 (2026-08-19T10:00) | evidence_87 (2026-08-17T09:42) | REPORT_REMAINING_RECORD/DELETE_RECORD/VERIFY_RECORD_ABSENT → REPORT_EXPOSED_PII/REDACT_RECORD/VERIFY_RECORD_REDACTED |
| case_179 (audit 2026-07-23T12:00) | support_2283 | ATTACHMENT → MESSAGE | evidence_17 (2026-07-25T15:00) | evidence_84 (2026-07-23T11:43) | REPORT_REMAINING_RECORD/DELETE_RECORD/VERIFY_RECORD_ABSENT → REPORT_EXPOSED_PII/REDACT_RECORD/VERIFY_RECORD_REDACTED |
| case_227 (audit 2026-06-28T07:00) | support_5830 | ATTACHMENT → MESSAGE | evidence_22 (2026-06-30T07:00) | evidence_80 (2026-06-28T06:25) | REPORT_REMAINING_RECORD/DELETE_RECORD/VERIFY_RECORD_ABSENT → REPORT_EXPOSED_PII/REDACT_RECORD/VERIFY_RECORD_REDACTED |
| case_275 (audit 2026-06-03T09:00) | support_3684 | ATTACHMENT → MESSAGE | evidence_26 (2026-06-05T12:00) | evidence_77 (2026-06-03T08:34) | REPORT_REMAINING_RECORD/DELETE_RECORD/VERIFY_RECORD_ABSENT → REPORT_EXPOSED_PII/REDACT_RECORD/VERIFY_RECORD_REDACTED |
| case_431 (audit 2026-03-20T08:00) | support_3615 | ATTACHMENT → MESSAGE | evidence_40 (2026-03-22T08:00) | evidence_68 (2026-03-20T07:23) | REPORT_REMAINING_RECORD/DELETE_RECORD/VERIFY_RECORD_ABSENT → REPORT_EXPOSED_PII/REDACT_RECORD/VERIFY_RECORD_REDACTED |
| case_527 (audit 2026-01-29T12:00) | support_3896 | ATTACHMENT → MESSAGE | evidence_49 (2026-01-31T15:00) | evidence_62 (2026-01-29T11:44) | REPORT_REMAINING_RECORD/DELETE_RECORD/VERIFY_RECORD_ABSENT → REPORT_EXPOSED_PII/REDACT_RECORD/VERIFY_RECORD_REDACTED |

In case_61, `object_19` keeps DELETE: its catalogue link (activity_4007, 2026-02-13) precedes
the cutoff.

Open question, not changed here: the workflow's pre-audit `DELETE_RECORD` operation type on
these support resources matches the public samples' expected treatment 10 out of 10 times.
Using it as a category signal would be a separate policy change.
