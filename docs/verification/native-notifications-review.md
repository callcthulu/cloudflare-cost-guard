# Independent native notification security review — 2026-10-28

Final verdict: **all three findings resolved; no remaining blocker identified**
in the delta from `412434d9f4f8f92813f6bd06a2c5f43faa71f958`.
Independent agent review is evidence, not human merge approval or authorization
for live sends, deployment or cutoff.

Scope: native adapters, protected files, strict configuration, recipient binding,
per-target queue/upgrade/restore, priorities and retries, CLI isolation, installer,
docs and synthetic regressions. No product/test edits were made by the reviewer.

## Findings corrected and independently rechecked

| Finding | Correction |
| --- | --- |
| Leaving multi-target mode cancelled deliveries but the legacy/absent-configuration result omitted the count | Nonzero cancellations remain visible in the run result and trigger existing exit-5 handling; unchanged legacy result shape stays compatible |
| Mutable Telegram usernames could redirect queued alerts after reassignment | Only nonzero signed-64-bit numeric chat IDs are accepted; aliases fail before transport |
| Route reconciliation allocated every pending delivery before collection/cutoff | Set-based SQL is bounded by at most 16 configured routes, without backlog-sized Python row materialization |

The final 10,000-delivery regression checks memory, cancellation counts, audit,
backoff, first binding, missing credentials and no historical backfill. The reviewer
independently ran all ten delivery-state tests and inspected the SQL replacement.

Additional review covered static human-readable warning/cutoff titles, endpoint-only
scope, currency/action context and aggregate message limits; strict native HTTPS
origins, no redirects/proxies and bounded responses; SMTP verified TLS with no
plaintext fallback; application acknowledgements; secret-error sanitization;
selected synthetic-send isolation; no resend of accepted target deliveries; and
installer checks for all native file references before mutation.

Final independent full suite on frozen source: **242 tests in 14.601 seconds,
239 passed and 3 platform skips**. Whitespace checks passed. The 41-file source
manifest was recomputed after testing with zero drift. Original JSON manifest
SHA-256: `e0cae5ea324c0972c53b3d55ba983246dcb9bee2faa6c8218f85418fcc61946f`.
See [per-file hashes](native-notifications-source.sha256) and
[delivery evidence](../native-notifications-evidence.md).

All provider/receiver behavior used injected transports and synthetic files. Source
review and offline checks do not establish live acceptance, human receipt, provider
cutoff eligibility, exactly-once delivery or a maximum invoice.
