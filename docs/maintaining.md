# Maintaining a small open-source project

This is an early observe-first utility, with no published stable release, hosted
service, paid support commitment or guaranteed response time. Use a small manual
maintenance process; no CI subscription or automation is needed to get started.

## Repository essentials

| File | Purpose |
| --- | --- |
| [LICENSE](../LICENSE) | Existing MIT use, modification and redistribution terms. |
| [README](../README.md) | New-user entry point and honest limits. |
| [Getting started](getting-started.md) / [runbook](runbook.md) | Installation, verification and operations. |
| [CONTRIBUTING](../CONTRIBUTING.md) | Contributor branches, tests and review. |
| [SECURITY](../SECURITY.md) | Private vulnerability reports and supported scope. |
| [SUPPORT](../SUPPORT.md) | Questions/ordinary bugs without private data. |
| [Code of conduct](../CODE_OF_CONDUCT.md) | Community behavior and moderation. |
| [CHANGELOG](../CHANGELOG.md) | User-visible changes; unreleased work is not a release. |
| [AGENTS](../AGENTS.md) | Safe workflow for coding assistants. |
| [PR template](../.github/PULL_REQUEST_TEMPLATE.md) | Structured submissions, no Actions execution. |

MIT is retained. No third-party runtime packages or vendored source are bundled in
the current tree; recheck licenses/attribution if a contribution adds any. Preserve
the MIT notice when redistributing. Private customer/infrastructure data is not
licensed for reuse. Cloudflare is a third-party product name: this independent,
unofficial project claims no affiliation, endorsement or logo rights.

## First publication

Follow [the checklist](publication.md). Preparation does not change visibility.
Implementation PR #1 and documentation PR #2 are integrated into `main`, with
reviewed commit ancestry preserved. Use [the launch plan](launch-plan.md) and
[branch governance](governance.md) for the separately approved public transition.
Do not invent a release tag or equate integration with public availability.

At launch, the owner explicitly changes visibility, enables Issues if accepting
reports, enables/verifies GitHub private vulnerability reporting and reviews content
moderation. Markdown templates do none of these. Private reporting is a public-repo
feature: follow [GitHub's instructions](https://docs.github.com/en/code-security/security-advisories/working-with-repository-security-advisories/configuring-private-vulnerability-reporting-for-a-repository).
Keep a real working private intake channel and decide who monitors it. Do not invent
an inbox, GitHub direct messages or an SLA. No Actions, paid features, Pages, package
registry or sponsorship are authorized by this documentation.

## Contributions and incidents

Request revision, platform/Python, sanitized expected/actual behavior, exit code and
a synthetic reproduction. Never request tokens, databases, account exports, full
config or private webhook payloads. Restrict/redact accidental sensitive reports
and arrange credential revocation privately; deletion does not revoke leaked secrets.

Review the actual diff, examples and tests. Require independent review for credential,
scope/ledger, persistence, installer or action changes. Agent/automation summaries are
supporting evidence, not approval. Users retain authority over their own infrastructure.

## Manual release process

1. Select a reviewed commit on the integrated default branch. Run offline tests and
   whitespace/privacy checks; inspect all publishable history, branches, tags and
   artifact metadata. No real user data in release tests.
2. For runtime/installer changes, repeat relevant fake-provider recovery tests and
   the disposable Linux lifecycle. For docs-only changes, verify commands/configs
   and links; distinguish these from historical Linux evidence.
3. Review [source coverage](capabilities.md). With offline-only evidence, label the
   release a pre-release and say so. One user's deployment is not universal provider
   certification. Do not claim a complete rated total or working cutoff without proof.
4. Update changelog/release notes with intended version, exact commit, tests,
   tested platforms, upgrade/rollback, coverage limits and known issues.
5. Obtain owner release approval, then create the tag/release explicitly. Inspect
   archives: source/docs/tests/license only, no config, tokens, SQLite, raw private
   evidence or original handoffs. Record a checksum and verify assets/links.
6. Keep live installation/canary evidence private and publish separately sanitized
   summaries only. Preserve original evidence; do not overwrite it to imply new tests.

These instructions create no release, tag or package publication. Coordinate security
fixes privately before public notes disclose an unpatched vulnerability.
