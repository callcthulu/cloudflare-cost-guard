# Support

Start with the [README](README.md), [configuration guide](docs/configuration.md),
[runbook](docs/runbook.md) and [current capabilities](docs/capabilities.md).
Missing provider evidence is unknown; this utility cannot guarantee a maximum bill.
Live enforcement is currently unavailable. See [implementation evidence](docs/evidence.md)
for the distinction between offline checks and unverified live operation.

For ordinary reproducible bugs or focused feature requests, use
[GitHub Issues](https://github.com/callcthulu/cloudflare-cost-guard/issues) when enabled
and follow the templates. While the repository remains private, only authorized
collaborators can access it; confirm repository visibility before posting.
If Issues is disabled, use an existing relevant pull request for nonsensitive
clarifications or wait until the maintainer enables the tracker. No separate
email, chat or commercial support channel is offered.

Include the reviewed commit, Python/OS version, command name, expected and actual
behavior, and the smallest synthetic reproduction. Describe output using synthetic
values. Do not attach real configuration, account/zone/resource identifiers, API
tokens, URLs containing secrets, SQLite state, account exports, raw logs or
notification payloads. Reproduce with invented data rather than copying a private
deployment and trying to redact it afterwards. Vulnerabilities use
[the security policy](SECURITY.md); do not disclose them in ordinary issues or PRs.

Support covers the project's documented behavior. Cloudflare billing disputes,
account access, provider service availability and operator-host administration
belong with the relevant provider or administrator. Maintainer help is voluntary;
no response time, availability, sponsorship benefit or commercial support commitment
is promised.

This is an independent, unofficial project, unaffiliated with and not endorsed by
Cloudflare. Cloudflare is a trademark of Cloudflare, Inc.; its name identifies the
provider whose APIs this project uses.
