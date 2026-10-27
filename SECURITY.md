# Security policy

This is early software with no stable releases or maintained older release lines.
Identify the affected commit and whether the problem reproduces on the default
branch. No response or fix-time SLA is promised.

## Report privately

Use [Report a vulnerability](https://github.com/callcthulu/cloudflare-cost-guard/security/advisories/new)
in this repository's Security tab. If the form is temporarily unavailable, ask a
maintainer for a private reporting route in an issue **without vulnerability or
exploit details**. Wait for a verified private channel before sending those details.
Do not disclose vulnerabilities in ordinary issues, pull requests or discussions.

A useful report includes the affected commit, Python/OS version, source locations,
expected and actual behavior, a minimal synthetic reproduction and potential impact.
Do not include tokens, actual account IDs, configuration, private URLs, databases,
raw notification payloads or customer data. Do not test other people's accounts or
production hosts. Coordinate disclosure while the maintainer assesses the report
and prepares a fix. Revoke exposed credentials through the provider's process;
removing a report does not revoke them.

## Boundaries

Read the [threat model](docs/threat-model.md), [capabilities](docs/capabilities.md)
and [recorded evidence](docs/evidence.md). No third-party security audit or
production safety certification is claimed. This utility is not a spending cap;
real enforcement remains unavailable. Source publication does not authorize actions
on a user's infrastructure.
