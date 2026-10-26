# Implementation evidence

This package describes offline/fake-provider and disposable Linux evidence only.
No production host or Cloudflare account was accessed, configured, deployed or
mutated. No real credentials, private configuration or private notification data
are included. Live observation and canary results remain unverified.

The private [draft PR](https://github.com/callcthulu/cloudflare-cost-guard/pull/1)
contains the reviewed implementation and this delivery package. The final
[release checks](verification/release-checks.json) cover intended repository files,
documentation/evidence links and heuristic sensitive-pattern scanning. They are
not a guarantee that arbitrary future user configuration is safe to publish.

## Offline verification

`python -m unittest discover -s tests -v`: 76 tests, zero failures on Windows
Python 3.14 (two platform symlink skips), and 76 tests, zero failures/skips on
unprivileged Linux Python 3.12. Test logs: [Windows](verification/windows-tests.txt)
and [Linux](verification/linux-tests.txt). Tests use synthetic data and injected
provider transports. The notification receiver test binds loopback only, with a
test-only HTTP transport; production requires verified HTTPS.

Recorded regression cycles exposed missing behavior before fixes, including
rearm/outage recurrence, attribution, source-unit trust and state restoration.
The complete suite covers identity, Decimal account allowances, separate ledgers,
UTC periods, unknown/stale/sampled evidence, bounded HTTP failure paths, observe
zero-writes, exact fake two-flag containment, timeout/crash recovery, manual
rearm, notification retries and local receipt, lock/state recovery and deployment.

## Linux lifecycle

[Lifecycle report](verification/linux-lifecycle.json) records the final fresh
disposable Ubuntu 24.04/systemd 255 fixture. It runs the real installed CLI,
policy, SQLite and scheduler with a staged synthetic collector and no external
network access. See [reproduction steps](linux-testing.md). It separately proves
unit syntax verification, two actual timer activations, process overlap refusal,
restart latch persistence, secret restriction/redaction, idempotent installation
and uninstall preserving exact state and unrelated backups. This does not prove
production host capacity, provider collection, real alert receipt or live cutoff.
Both temporary Linux distributions were removed after testing; no existing
distribution or server installation was replaced. Downloaded fixture image removed.

## Independent reviews

[Sanitized review record](verification/reviews.md) describes two distinct angles:
security/correctness and public reuse/privacy/documentation. Review findings were
tracked and addressed, then regressions rechecked. Agent review is not a third-party
audit or a guarantee. The [implementation ledger](progress.md) records task boundaries.

## Coverage and live gates

| Check | Result |
| --- | --- |
| Current official API contract review | Recorded in [capability matrix](capabilities.md). |
| Actual account API access | Unverified; no live accounts enrolled. |
| Actual provider latency/freshness | Unmeasured; no fetch-time proxy used. |
| Production observe installation/service/timer | Not authorized or performed. |
| Real notification receipt | Not configured or verified. Local fake receiver only. |
| Independent host heartbeat | Operator setup pending. |
| 24-hour observation window | Not started. |
| Live disposable enforcement canary | Not authorized; unverified and currently unsupported. |
| Publication | Repository private; separate owner decision required. |

Workers requests are approximate rolling-window evidence; CPU aggregate is
unsupported. Billing V1 access, update heartbeat, composite row identity and
non-overlap must be verified before reporting a complete rated total. Parsed
positive charges can alert without pretending to be an account total.
Subscriptions are separate commitments and cannot establish absence of metered
charges. Other products lack fast metrics/cutoff. No maximum-bill guarantee exists.

The machine-readable [handoff status](../handoff-status.json) references each gate's
evidence. Its `commit` identifies the reviewed implementation; later evidence-only
commits may update this package without changing runtime code.
