# Solution audit — 2026-10-28

Audited the merged source at `ea25f30ae592119b7d4214f832f8e274e8850b58`, then
corrected the gaps below in reviewed source
`cc1ea53f0e0b0fcf5c6d1936a78a0c599f915d85`. This is offline/source and disposable
Linux verification; it does not establish live notification receipt or cutoff.

## Requirements checked

| Area | Verified behavior and guide |
| --- | --- |
| Hard cutoff | Zero or one positive USD threshold; null/omitted disables it. An explicitly armed, approved stateless HTTP Worker can be deleted with `force=false`, or have only workers.dev/preview flags disabled. [Cutoff guide](automatic-cutoff.md) |
| Soft warnings | Zero or more USD/percentage thresholds, stable deduplication across polls/restarts/reordering, and new-period alerts. Percentages require a hard limit. Warning-only resources cannot write provider state. [Budget guide](budget-alerts.md) |
| Delivery | Native authenticated TLS SMTP email, numeric-ID Telegram, Slack, Discord and generic HTTPS JSON. Independent destination retries, priority, recipient binding, cancellation and no historical fanout. [Channel setup](notifications.md) |
| Human setup/use | Prerequisites, protected source/secrets, stopped installer updates, validation/probe, policy/status inspection, isolated notification testing, scheduling and recovery. [Getting started](getting-started.md), [runbook](runbook.md) |
| Agent setup/use | Repository invariants and a copyable prompt with full source pin, required operator inputs, exact authorization boundaries, verification gates and private handoff expectations. [AGENTS](../AGENTS.md), [agent guide](agent-deployment.md) |

An independent budget probe also verified warning state after SQLite reopen,
reordering, adding a threshold and changing the guard period. Warning edits retained
the cutoff approval digest. The three complete example configs validate; policy
inspection and all four default notification previews work without credentials.

## Gaps found and corrected

- The budget guide incorrectly denied native senders; troubleshooting incorrectly
  denied `test-notification` and suggested running queued incidents. Both now
  describe native destinations and selected preview/explicit synthetic send.
  Delivery limits are described per destination, globally per run.
- Upgrade/disarm text now includes schema 6, SMTP egress, writer-reference removal
  for observe installation, preservation of original private policy, and the fact
  that read-only preview does not persist reconciliation. It does not recommend
  enforce runs merely for inspection or deleting state.
- Legacy webhooks and Cloudflare transport/public probes omitted malformed HTTP
  protocol exceptions. These now retain sanitized failure/backoff or unknown
  results. Reads retry within existing bounds; mutations remain one attempt.
  A synthetic deletion applied before a malformed response now immediately
  reconciles read-only without replaying the mutation.

## Verification

| Check | Actual result |
| --- | --- |
| Baseline Windows suite | 242 tests: 239 passed, 3 platform skips |
| Corrected Windows suite, Python 3.14.7 | 247 tests: 244 passed, 3 skips; 12.752 seconds |
| Corrected disposable Ubuntu 24.04, Python 3.12.3 | 247 passed, zero skips; 14.877 seconds |
| Independent fix review | Nine-file correction inspected; all five new boundary regressions passed |
| Booted systemd 255 lifecycle | Two actual scheduled processes, overlap exclusion, durable latch, secret isolation and exact uninstall retention passed |
| Installed four-channel preview | Unreadable protected files, no external routes, no `--send`, unchanged database, collector count stayed two, schema 6 confirmed |

Unit commands were `python -B -m unittest discover -s tests -v` on Windows and
`python3 -B -m unittest discover -s tests -v` on Linux. Tests use synthetic data and
injected transports; the existing notification receiver binds loopback only.
Logs: [Windows](verification/solution-audit-windows-tests.txt),
[Linux](verification/solution-audit-linux-tests.txt).

All 41 [reviewed source hashes](verification/solution-audit-source.sha256) matched
before and after Linux execution. Original review manifest SHA-256:
`4db0a6875108aa6ab14d1ddcaaf8f206efe21ce8824a718ff16fdad7092d76a5`.
The [Linux receipt](verification/solution-audit-linux.json) records fixture results.
Temporary staging and smoke-helper setup needed reruns; only fixture helpers
changed, and final tests used unchanged reviewed product source. The disposable
fixture was removed and final WSL inventory was empty.

The documentation pass checked all 43 existing Markdown documents' local links
and anchors, 41 shell blocks with Bash syntax validation, and all 13 tracked JSON
files. Commands involving real installation or delivery were not executed on a
workstation or real server. Later evidence/source-pin edits are checked separately
and do not change the reviewed runtime.

## Limits that remain

The configured cutoff is an automatic action threshold, **not a guaranteed maximum
invoice**. Captured usage is partial/approximate with a configured CPU planning
reserve; the account-rated signal is a largest-line floor. Delays, outages and
in-flight work can cause overshoot. R2, D1, Queues and Pages have no cutoff adapter.

Notification acceptance is not human receipt; ambiguous timeouts can duplicate
messages. SMTP OAuth-only accounts and mutable Telegram aliases are unsupported.
Live source coverage, actual recipient receipt and an exact-resource cutoff canary
still require the operator's authorized deployment verification. No consumer
credentials, live provider calls, real sends, DNS/CDN/Access/billing changes or
existing backup-job changes were used for this audit.
