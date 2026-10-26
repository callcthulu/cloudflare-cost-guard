# Security policy

## Supported code

This is a pre-release project with no stable releases or maintained older release
lines. Reports should identify an affected commit and whether the issue reproduces
on the current default branch. No response or fix-time SLA is promised.

## Report a vulnerability privately

Do not disclose vulnerabilities in public issues, pull requests or discussions.
Do not include credentials, account exports, deployment configuration, private
endpoints, state databases, raw notification payloads or customer data in any report.
Use invented identifiers and a minimal synthetic reproduction.

**While this repository is private:** GitHub private vulnerability reporting is
unavailable. Authorized collaborators may use a repository issue only after
confirming the repository is still private and access is appropriate for the
report; Issues must also be enabled. If that route is unavailable, ask a maintainer
for a private reporting route without disclosing vulnerability details. Outsiders
should withhold details until a verified private channel is available; no separate
security email or private messaging service is advertised here. Private issues
become visible when a repository is made public; the maintainer must review and
resolve disclosure of any private reports before changing repository visibility.

**For a future public release:** the maintainer must enable and verify GitHub
private vulnerability reporting. Then use
[Report a vulnerability](https://github.com/callcthulu/cloudflare-cost-guard/security/advisories/new)
from the repository's Security tab. This link is a planned public reporting route,
not a claim that reporting is enabled now. If the form is unavailable, open only
a nonsensitive issue asking for a private reporting route, without exploit details.
[GitHub documents how private reports work](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately).

A useful private report includes the affected commit, Python/OS version, relevant
source locations, expected and actual behavior, synthetic reproduction steps and
potential impact. Do not test against other people's accounts or production hosts.
Coordinate disclosure with the maintainer while a report is assessed and a fix is
prepared. Never attach secrets to demonstrate impact; rotate exposed credentials
through the provider's approved process.

## Security boundaries and publication

No third-party security audit or production safety certification is claimed.
Read the [threat model](docs/threat-model.md), [capabilities](docs/capabilities.md)
and [evidence](docs/evidence.md) before use. This is not a spending cap; live
enforcement remains unavailable. Keep the repository private until the
[publication checklist](docs/publication.md) and a separate owner decision are
complete. Public reporting must be enabled and its form verified as part of that
release decision; adding this policy alone does not enable the GitHub feature.
