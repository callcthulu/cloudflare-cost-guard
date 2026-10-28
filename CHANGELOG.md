# Changelog

Changes are recorded here before a release is tagged. No stable release or
production-readiness certification is claimed.

## [Unreleased]

### Added

- Native email (TLS SMTP), Telegram, Slack and Discord destinations alongside the
  backward-compatible generic JSON receiver; configurable combinations, incident
  recipient snapshots and independent retry/cancellation state per destination.
- Configuration-only `test-notification` preview and explicit `--send` for one
  selected synthetic message without Cloudflare calls or backlog delivery. See
  [notification setup](docs/notifications.md). Live receipt remains an operator gate.

- Optional multiple USD/percentage resource-budget warnings, warning-only budgets
  without a hard limit, and configuration-only `show-policy` inspection. Warning
  edits preserve cutoff approval; equivalent effective warning thresholds share
  period deduplication. Current policies appear alongside execution state in `status`.
- Priority delivery for due notifications: cutoff outcomes before warnings before
  routine events, within the shared per-run delivery limit. See
  [budget alerts](docs/budget-alerts.md) and [verification](docs/budget-alerts-evidence.md).
  Historical cutoff evidence is unchanged.

- Optional automatic USD-budget cutoff for explicitly enrolled stateless HTTP
  Workers: destructive non-forced script deletion or workers.dev/preview-only
  disablement. Initial installation stays observe-only; existing installations
  require explicit arming, a separate writer and pinned version 2 owner approval.
- Persistent, deduplicated per-minute request accounting with a configured CPU
  planning reserve, or a partial largest-rated-line account floor. Quality acceptance
  is explicit; below-threshold partial evidence remains unknown. No maximum invoice
  or measured CPU guarantee is made.
- `prepare-cutoff` creates an unarmed external approval template; preview sends
  no provider write and adds no ledger, outbox or intent. Schema 4 preserves earlier state and adds usage/intent history. Manual
  rearm archives known terminal budget attempts without erasing usage; uncertain
  attempts are reconciled read-only without automatic write retry or restoration.

See [automatic cutoff](docs/automatic-cutoff.md) for configuration, scope and
verification limits. This feature is tested offline, not proved by a live canary.

### Fixed

- Make the JSON parser error regression independent of platform nesting limits;
  production parsing and error guards are unchanged.
- Use the singular zone subscription object endpoint while preserving strict
  completeness checks on account lists.
- Reconcile duplicate account/zone subscription appearances by owning account and
  verified provider ID; conflicts leave the commitment total unknown.
- Parse V1 billing-info coverage explicitly. Uncovered/empty accounts do not become
  zero balances; missing anchors cannot verify a period. Hourly cache restoration
  preserves coverage without elevating stale, previous-period or old-format proof.

See the [compatibility delivery](docs/compatibility-delivery.md) for regression
evidence, independent review and upgrade boundaries.

### Earlier additions

- Python 3.11+ standard-library CLI for configuration validation, capability probes,
  bounded observe runs, status, explicit rearm and enforcement preview.
- Multiple-account and configured-zone subscription inventory, approximate Workers
  request analytics and incremental V1 Alpha rated rows where provider access exists.
  Unknown totals, unsupported CPU totals and coverage limits remain explicit.
- Separate usage/charge/commitment evidence, Decimal policy calculations, SQLite
  incidents/latches/action intents and a persistent notification outbox.
- A legacy raw-threshold Worker endpoint executor tested with fake providers; its
  exact-evidence/inventory path remains blocked by current real-source limitations.
- Linux systemd installer and synthetic disposable-host lifecycle checks. Installation
  does not start or enable the timer.
- Offline synthetic regression tests, sanitized review records and documentation of
  architecture, configuration, operations, threat boundaries and pending live gates.
- Contribution, support, conduct and security-reporting guidance; bug/feature and
  pull request templates; and publication/maintenance procedures.

### Verification limits

Recorded offline and disposable Linux evidence is described in
[docs/evidence.md](docs/evidence.md). No live Cloudflare access, production install,
real alert receipt, 24-hour observation or live cutoff is claimed. Source publication
does not establish those live outcomes or announce a versioned release.
