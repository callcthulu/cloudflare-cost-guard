# Changelog

Changes are recorded here before a release is tagged. No stable release or
production-readiness certification is claimed.

## [Unreleased]

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
  pull request templates; and a publication checklist for a future owner decision.

### Verification limits

Recorded offline and disposable Linux evidence is described in
[docs/evidence.md](docs/evidence.md). No live Cloudflare access, production install,
real alert receipt, 24-hour observation or live cutoff is claimed. The repository
remains private; this changelog does not announce a public release.
