# Changelog

Changes are recorded here before a release is tagged. No stable release or
production-readiness certification is claimed.

## [Unreleased]

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

### Added

- Python 3.11+ standard-library CLI for configuration validation, capability probes,
  bounded observe runs, status, explicit rearm and enforcement preview.
- Multiple-account and configured-zone subscription inventory, approximate Workers
  request analytics and incremental V1 Alpha rated rows where provider access exists.
  Unknown totals, unsupported CPU totals and coverage limits remain explicit.
- Separate usage/charge/commitment evidence, Decimal policy calculations, SQLite
  incidents/latches/action intents and a persistent notification outbox.
- A narrowly gated Worker endpoint executor tested with fake providers; real
  enforcement remains blocked by metric, inventory and cutoff-proof limitations.
- Linux systemd installer and synthetic disposable-host lifecycle checks. Installation
  does not start or enable the timer.
- Offline synthetic regression tests, sanitized review records and documentation of
  architecture, configuration, operations, threat boundaries and pending live gates.
- Contribution, support, conduct and security-reporting guidance; bug/feature and
  pull request templates; and publication/maintenance procedures.

### Verification limits

Recorded offline and disposable Linux evidence is described in
[docs/evidence.md](docs/evidence.md). No live Cloudflare access, production install,
real alert receipt, 24-hour observation or live cutoff is claimed. Source publication does not establish those live outcomes or announce a
versioned release.
