# Automatic cutoff evidence — 2026-10-27

The feature implements an automatic budget-to-action path for explicitly enrolled
stateless HTTP Workers. Once armed, `run` can delete the exact Worker with
`force=false`, or disable only its workers.dev and preview flags. Configuration,
approval, eligibility and recovery are described in [automatic cutoff](automatic-cutoff.md).

Reviewed implementation commit: `9c6e16b817e0f3541c8fceb986342dd83d6535f3`.
Subsequent source-pin and evidence documentation changes do not alter runtime,
tests or installation code. This identifies source availability, not merge or
production approval.

## Offline and Linux verification

| Check | Actual result |
| --- | --- |
| Windows Python 3.14.7 | 170 tests: 167 passed, 3 platform skips, 0 failures; 8.907 seconds |
| Disposable Ubuntu 24.04, Python 3.12.3 | 170 passed, 0 skips/failures; 9.551 seconds |
| Real HTTP adapter, injected provider responses | Automatic DELETE exactly once, authenticated absence read-back, endpoint-only scope, no resend after ambiguous writes |
| Independent security review | Findings corrected and regression-tested; no remaining source-review findings |
| Booted systemd 255 lifecycle | Install twice, unit verification, overlap exclusion, two scheduled processes, persistent latch, secret isolation, uninstall retention passed |
| Inactive enforcement installation | Default refusal, explicit `--allow-enforce`, protected approvals/service-identity checks and no automatic unit start passed |

Commands: `python -B -m unittest discover -s tests -v` on Windows;
`python3 -B -m unittest discover -s tests -v` on Linux. Linux unit tests ran
unprivileged in a network namespace without external routes; loopback was enabled
for the synthetic notification receiver. Tests require no provider credentials.
Logs: [Windows](verification/automatic-cutoff-windows-tests.txt),
[Linux](verification/automatic-cutoff-linux-tests.txt).

Regression coverage includes overlapping/revised minute usage, restart persistence,
overlapping rated charge windows, period-bound approvals, expiry during slow reads,
official empty/default version response shapes, namespace ownership on later
pages, malformed namespace owners, configuration/manifest rejection, no writer in
observe/probe/preview, account isolation, and separate reader/writer transports.
Definite 401/403 rejections require read-only recovery and manual rearm; timeouts
and 5xx remain uncertain and never automatically retry a mutation.

The [security review](verification/automatic-cutoff-review.md) records the scope
and fixes. The [source manifest](verification/automatic-cutoff-source.sha256)
contains final delivery SHA-256 values for all 33 reviewed runtime, test, installer,
unit and example-config files, normalized to LF. The Linux copy matched its review
before and after execution. Final staging then removed only trailing blank lines
from `tests/test_automatic_cutoff_runner.py` and `tests/test_cutoff_cli.py`; both
affected suites were rerun on Windows (16 tests, one platform skip). Independent
review verified those were the only differences from the Linux snapshot. Runtime,
installer, units and example config are unchanged. Required CI verifies the final
committed test files separately from the disposable lifecycle result.

The Linux lifecycle harness ran only in a newly imported, disposable fixture.
Synthetic collector injection was confined to the installed fixture copy; it did
not alter the reviewed source. See [fixture results](verification/automatic-cutoff-linux.json).
The separate arming smoke validated the installed service identity and approval
without running enforcement. The fixture was removed; final WSL inventory was empty.
The unit's `Result=exit-code` reflected synthetic unknown coverage/pending alerts;
the two scheduled runs completed. MemoryPeak was unavailable, not reported as zero.

## Live gates remain unverified

No live Cloudflare request, consumer credential, production installation,
notification receipt or destructive canary was used. DNS/CDN, Access, billing,
subscriptions, other repositories and existing backup jobs were untouched.
Source tests and provider read-back fixtures are not a live API contract canary.

Initial installation remains observe-only. A real deployment, exact-resource
canary and production arming each need the operator's authorization. Sampling,
missing history, CPU variability/reserves, polling delay, outages, ongoing work
and charges outside the approved Worker can produce unbounded overshoot. This is
an automatic cutoff threshold, not a guaranteed maximum invoice. R2, D1, Queues
and Pages have no implemented cutoff adapter.

The initial [implementation evidence](evidence.md) and [publication receipt](publication-status.md)
remain historical snapshots; their older counts and capabilities are not rewritten.
