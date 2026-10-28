# Budget-alert evidence — 2026-10-28

This delivery adds zero or more USD/percentage warnings, an optional hard cutoff,
contextual priority alerts, offline `show-policy` inspection and current policies
in `status`. See [configuration and editing](budget-alerts.md). Warning edits leave
existing cutoff approvals valid; changing cutoff semantics requires fresh approval.

Reviewed implementation commit: `ba00e2a1d6790654219a3d141015de2b2580daf8`.
Later source-pin/evidence documentation updates do not change its reviewed runtime,
tests, installer or examples. This is a source pin, not production approval.

## Verification

| Check | Actual result |
| --- | --- |
| Windows Python 3.14.7 | 200 tests: 197 passed, 3 platform skips, 0 failures; 9.505 seconds |
| Independent reviewer Windows run | 200 tests: 197 passed, 3 skips; 9.704 seconds |
| Disposable Ubuntu 24.04, Python 3.12.3 | 200 passed, zero skips/failures; 14.306 seconds |
| Booted systemd 255 lifecycle | Installation twice, clean unit verification, two scheduled processes, overlap protection, persistent latch, secret isolation and uninstall retention passed |
| Installed warning-only inspection | Service-user `show-policy` succeeded with an unreadable read token; two USD warnings, null hard limit, cutoff disabled, no raw identities and unchanged database bytes |
| State upgrade | Actual lifecycle database schema 5; populated schema-4 migration/restore and legacy critical-event priority covered by regressions |
| Independent security review | Findings corrected and rechecked; no unresolved actionable findings |

Commands: `python -B -m unittest discover -s tests -v` on Windows and
`python3 -B -m unittest discover -s tests -v` on Linux. Linux unit tests ran as
an unprivileged user in a route-free network namespace, with loopback for synthetic
notification tests. Logs: [Windows](verification/budget-alerts-windows-tests.txt),
[Linux](verification/budget-alerts-linux-tests.txt).

Regressions cover multiple/mixed thresholds, no-warning/no-cutoff tracking,
warning-only resources alongside armed resources, invalid/duplicate/equivalent
thresholds, exact long-decimal arithmetic and unrepresentable percentage rejection,
period/restart/reorder deduplication, unchanged old approval digests, contextual
cutoff events ahead of routine backlog, failed notification after successful cutoff,
warning exit status, readonly preview/probe, offline inspection and mixed installation.

The [independent review](verification/budget-alerts-security-review.md) also records
a synthetic integration with 150 warnings and the unchanged original approval:
all 150 warnings and a confirmed fixture deletion were produced; reopening and
reordering did not duplicate warning events.

All 38 runtime/test/deploy/example files match the
[LF-normalized source hashes](verification/budget-alerts-source.sha256), before
and after Linux execution. Original review JSON manifest SHA-256:
`d60890b74781ca03e758448c0823130f1995986ca713efa258937b9a6cb901c7`.
The Linux manifest SHA-256 is
`5e460c37f1ed11372c69c9c81fc9c97e8b6334fe4ef81e0fa920addb0e820513`.

The [Linux result](verification/budget-alerts-linux.json) records lifecycle and
installed inspection checks. Only the fresh disposable fixture used the root
lifecycle harness; synthetic collector injection stayed within its installed copy.
The collector count remained two after inspection, and uninstall retained exact
database bytes, synthetic secrets and an unrelated backup. The fixture was removed;
final WSL inventory was empty. `Result=exit-code` reflects synthetic unknown coverage
and pending alerts; MemoryPeak was unavailable rather than zero.

## Unverified live gates

No consumer credentials, live Cloudflare calls, real notification acceptance/receipt,
production installation or cutoff canary were used. DNS/CDN, Access, billing,
subscriptions, LeligDom and existing backup jobs were untouched. Source review and
fixture tests do not approve merge or production arming.

Alerts need an approved compatible HTTPS receiver. Failed delivery retries, so
duplicates can occur after an ambiguous timeout; receivers must deduplicate
`incident_id`. Priority respects due times, and finite per-run delivery means a
large warning backlog may take multiple runs. Cutoff never waits for notification.
Partial/sampled/delayed signals still do not guarantee a maximum invoice or bounded
overshoot. The [earlier cutoff evidence](automatic-cutoff-evidence.md) remains a
historical snapshot, not a substitute for this verification.
