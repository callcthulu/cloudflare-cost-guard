# Native notification evidence — 2026-10-28

This delivery adds native email, Telegram, Slack and Discord alongside the existing
generic HTTPS JSON receiver. Each incident snapshots its destination set and
recipient/configuration digests; each destination has independent retry, acceptance
and cancellation state. See [setup](notifications.md) and the complete
[synthetic observe configuration](../config.notifications.example.json).

Reviewed implementation commit: `63ae782e95e3b8360541b0b539a4dc29e0c9384d`.
Subsequent setup-pin/evidence documentation updates do not change the reviewed
runtime, tests, installer or examples. This pin does not authorize a live send.

## Verification

| Check | Actual result |
| --- | --- |
| Windows Python 3.14.7 | 242 tests: 239 passed, 3 platform skips, zero failures; 14.195 seconds |
| Independent reviewer's Windows run | 242 tests: 239 passed, 3 skips; 14.601 seconds |
| Final Windows run after test-transport correction | 242 tests: 239 passed, 3 skips; 17.105 seconds |
| Disposable Ubuntu 24.04, Python 3.12.3 | 242 passed, zero skips/failures; 16.209 seconds |
| Booted systemd 255 lifecycle | Installation twice, clean unit verification, two scheduled processes, overlap protection, durable latch, secret isolation and uninstall retention passed |
| Installed native inspection | All four previews and `show-policy` passed as the service identity with all six protected files unreadable and no external network routes |
| Inspection isolation | No `--send`, unchanged database bytes, collector count stayed two, units inactive, actual schema 6 and delivery table confirmed |
| Independent security review | All three findings corrected and rechecked; no unresolved blocking finding |

Commands: `python -B -m unittest discover -s tests -v` on Windows and
`python3 -B -m unittest discover -s tests -v` on Linux. Unit transports are injected;
the existing receiver fixture uses loopback only. Linux unit tests ran unprivileged
in a network namespace with no external routes. Logs:
[Windows](verification/native-notifications-windows-tests.txt),
[Linux](verification/native-notifications-linux-tests.txt).

Regressions cover legacy webhook compatibility, strict channel configuration,
application acknowledgements, native origin restrictions, TLS, redirects/proxies,
response size, protected-file replacement, sanitized errors, mentions, bounded
text, selected synthetic-send isolation, all installer secret references, independent
retries, no successful resend, priorities/backoff, migration/restore, recipient
changes, first binding and no historical fanout to added targets.

Real collector/cutoff integration with synthetic transports verifies the approved
Worker is deleted before native notifications run. A failed Discord delivery retries
independently while Slack's accepted cutoff notification is not resent; the provider
mutation remains exactly once. Probe and preview never read notification secrets.

The [independent review](verification/native-notifications-review.md) records the
cancellation-report, mutable Telegram alias and backlog-memory corrections. The
10,000-delivery memory regression reduced traced Python peak allocation from
6,527,031 bytes to 4,510 bytes on the development workstation. This is not a Linux
production capacity guarantee.

All 41 [LF-normalized source hashes](verification/native-notifications-source.sha256)
matched before and after Linux tests. Original review JSON manifest SHA-256:
`e0cae5ea324c0972c53b3d55ba983246dcb9bee2faa6c8218f85418fcc61946f`.
Linux manifest SHA-256:
`028daeed59551cde962f14c14d86c59880f688eec718b1628c08a7870bd38012`.

CI then flagged two loose URL substring checks in the injected synthetic
notification transport. They were replaced with exact parsed-hostname matching.
Independent assembly review compared the Linux archive and all 41 files: only
`tests/test_automatic_cutoff_runner.py` changed; runtime, deployment and examples
are identical. The reviewer reran all 19 integration tests successfully, and the
lead reran the full Windows suite. The [final Windows log](verification/native-notifications-final-windows-tests.txt)
and [delivery source hashes](verification/native-notifications-delivery-source.sha256)
record the refined test fixture. Final-commit CI verifies that committed snapshot
separately from the original Linux lifecycle result. The original Linux receipt,
logs and source hashes above remain unchanged. Delivery review JSON manifest SHA-256:
`ef36fcbc38bca7f0cb6dee03624b3fc48629ec766b9b7193483b9b79a7574ab8`.

The [Linux result](verification/native-notifications-linux.json) contains actual
UTC timestamps and installed inspection results. Root lifecycle operations ran
only in a new disposable fixture; synthetic collection stayed in that installed
copy. Uninstall preserved exact database bytes, synthetic secrets and an unrelated
backup. The fixture was removed and final WSL inventory was empty.
`Result=exit-code` reflects synthetic unknown coverage/pending alerts; MemoryPeak
was unavailable, not zero.

## Live gates

No real SMTP, Telegram, Slack, Discord, external receiver or Cloudflare call was
made. No consumer credentials, production deployment, alert receipt or cutoff
canary were used. DNS/CDN, Access, billing, subscriptions and existing
backup jobs were untouched. Source review is not merge or deployment approval.

Provider acceptance is distinct from human receipt; timeouts can cause duplicates.
Email requires supported authenticated SMTP with verified TLS, and Telegram requires
a numeric chat ID. Changing destinations can cancel pending deliveries rather than
redirect them. Live sends need the operator's selected destination and explicit
`--send`; actual receipt is an owner verification step. Spending-signal and invoice-cap
limitations remain unchanged. Earlier [budget-alert](budget-alerts-evidence.md) and
[cutoff](automatic-cutoff-evidence.md) results remain dated historical snapshots.
