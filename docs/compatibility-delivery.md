# Subscription and billing-info compatibility delivery

Date: 2026-10-27. Base: `770050f889a775012d2ae4f3f046845820c683a0`.
This is a source-only compatibility update. The separate delivery package's
`handoff-status.json` records its full pinned commit and evidence checksums;
the root status file remains the original historical delivery record.

## Changes

| Reported issue | Corrected behavior |
| --- | --- |
| Zone collection used a plural list route | Use documented `GET /zones/{zone_id}/subscription`, requiring an object. Account subscriptions retain their plural list route and strict completeness checks. |
| Account and zone appearances could double-count one subscription | Reconcile by owning account and verified provider subscription ID. Keep both appearances and zone attribution in the private snapshot. Conflicting identity, amount, currency, plan or attribution leaves the total unknown. |
| V1 account coverage was not collected | Read `GET /accounts/{account_id}/billable-usage/info`. Explicit `covered:false` means unavailable coverage; invalid/missing info means unknown. Neither establishes zero spend. |
| Missing or cached metadata could overstate period verification | Require explicit parsed, covered and verified-period proof. Verification requires operator confirmation plus consistent active UTC anchors. Cache proof expires at known subscription transitions and the billing boundary. |

No new configuration fields or token permissions are needed. Subscription
commitments, rated charges and estimates remain separate. Complete endpoint
responses do not prove all-product inventory or a complete bill. Positive rated
lines and forbidden plans remain account alert evidence even if totals are unknown;
neither identifies a guilty site. Real enforcement remains unsupported.

## Regression evidence

The baseline suite had 76 tests. The updated suite has 107 tests, including
new synthetic collector, policy, cache and collector-to-policy regressions.
Tests use injected transports and temporary fixture credentials; no consumer
configuration or provider credentials are required.

- [Windows test log](verification/compatibility-windows-tests.txt): Python 3.14.7,
  107 tests run, 105 passed and two platform symlink skips.
- [Linux test log](verification/compatibility-linux-tests.txt): Python 3.12.3,
  107 tests passed, no skips. Unprivileged disposable Ubuntu 24.04, isolated
  network namespace with loopback only; source hashes checked before execution.
- [Independent review](verification/compatibility-review.md): security,
  correctness, privacy and evidence review; includes fixes and independent
  reproduction of two review findings.
- [Documentation review](verification/compatibility-docs-review.md): usability,
  upgrade commands and privacy, including the corrected source-selection command.
- [Linux test provenance](verification/compatibility-linux.json): source manifest,
  environment and cleanup evidence.

Regression-first runs reproduced the wrong singular endpoint, missing explicit
coverage, absent identity metadata and duplicate reconciliation gaps. Independent
review then reproduced two additional gaps: absent billing proof could be accepted
by policy, and cached verification could outlive a known subscription transition.
New tests failed before those corrections and passed after them. Raw failing logs
remain local because tracebacks contain workstation paths; the green logs here
contain synthetic test names/results only.

Relevant regressions include:

- Exact singular GET and object schema; missing/invalid identity, plan, price and
  currency; account empty-list/nonzero-total rejection and bounded read failures.
- Shared zero and positive commitments counted once; distinct IDs separate;
  conflicting amount, currency, plan, canonical identity, scope and multi-zone
  attribution unknown; display names ignored for identity.
- Uncovered plus empty usage, malformed/denied info, missing anchors, inactive or
  conflicting metadata and later covered responses, without invented balances.
- Hourly metadata restoration, old cache formats, stale/future evidence, billing-day
  changes, month rollover, exact expiry, active subscription endings and future starts.
- Missing proof blocks both rated totals and full-period estimates; real adapter
  metadata reaches policy without losing duplicate provenance.

## Consumer handoff

Review the new full delivery SHA and follow the existing
[upgrade procedure](runbook.md#configuration-updates-upgrades-and-token-rotation)
only after deployment is separately authorized. Preserve state, latches and
external secret files. Old billing-cache entries remain unknown until refreshed;
no migration, cache deletion or database reset is needed.

After an authorized read-only probe, inspect the explicit billing coverage fields
and each subscription endpoint separately, following the
[capability contract](capabilities.md) and [troubleshooting](troubleshooting.md).
This delivery performed no deployment, consumer credential access, authenticated
provider query or live notification check. The installer/systemd lifecycle was
unchanged and was not rerun for this update; its earlier evidence remains historical.
Workers analytics are still collected; an opt-out remains a separate change.
