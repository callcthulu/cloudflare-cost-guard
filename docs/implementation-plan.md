# Implementation and acceptance plan

> Execution: bounded specialists with lead integration and independent security review.

1. Freeze models/config/policy; run RED/GREEN tests for identity, Decimal pricing,
   billing periods, unknown evidence and trip persistence.
2. Build bounded HTTPS collector with realistic contract fixtures. Test GraphQL
   errors, denied access, malformed/oversized bodies, rate limiting, truncation,
   stale timestamps and token isolation. Record source coverage honestly.
3. Build transactional state/outbox, CLI runner and dedicated systemd installer.
   Test overlap, rollback, account isolation, retries, crash recovery and redaction.
4. Build narrow executor behind approval and evidence checks. Fake tests must prove
   exact two-flag write only, no writes on any unsafe input, persisted intent,
   reconciliation after timeout/crash and no automatic re-enable.
5. Run disposable Linux service/timer lifecycle tests, independent security and
   documentation/privacy reviews, fix findings, scan diff and history, prepare
   private draft PR and sanitized handoff evidence. No automatic Actions workflows.

| ID | Acceptance |
| --- | --- |
| A1 | Observe always causes zero provider mutations. |
| A2 | Shared account allowances and Worker identity count once; accounts isolate. |
| A3 | Missing/stale/partial evidence unknown; sampled at most warning; CPU sum unsupported when absent. |
| A4 | UTC periods and deduplicated ledgers do not mix or double count. |
| A5 | API errors, timeout and truncation never yield healthy complete evidence. |
| A6 | Forbidden subscription or rated positive spend alerts independently. |
| A7 | Unsafe approval/scope/inventory/quality blocks all mutations. |
| A8 | Approved fake action updates only both endpoint flags of one Worker. |
| A9 | Timeout/crash/partial verification persists and reconciles. |
| A10 | No repeated completed actions; manual rearm only. |
| A11 | Bounded persistent outbox, deduplication and redaction. |
| A12 | Linux lifecycle, no overlap, safe uninstall retaining state. |
| A13 | Separately evidenced live probe, observe runs and alert receipt. |
| A14 | Separately authorized live canary or explicit unverified result. |

Review focus: attribution across domains; delayed/quantile metrics; applied writes
followed by timeouts; origin exposure through route changes; host/notification outage.
