# Maintaining

Cloudflare Cost Guard is an early observe-first utility. Maintainer help is
voluntary; there is no hosted service or support SLA.

## Review contributions

Follow [CONTRIBUTING](../CONTRIBUTING.md) and [branch governance](governance.md).
Review the actual diff, synthetic examples and tests. Require independent review
for credential, accounting, persistence, installer or action changes. A human
maintainer owns the merge decision; agent summaries do not approve it.

Request a commit, Python/OS version and minimal synthetic reproduction for reports.
Never request credentials, databases, account exports, full config or private
notification payloads. Handle vulnerabilities through [SECURITY](../SECURITY.md).
If sensitive data is posted, restrict the report and arrange credential revocation
privately; deletion alone is insufficient.

MIT is retained. The current runtime uses the standard library without vendored
third-party code. Recheck licensing and attribution when adding dependencies or
assets. Private deployment data is not part of the reusable project.

## Manual release process

1. Select a reviewed default-branch commit. Run offline tests and whitespace checks;
   inspect publishable files, history, refs and archives for sensitive data.
2. For runtime/installer changes, repeat relevant recovery tests and the disposable
   [Linux lifecycle](linux-testing.md). For docs, verify commands, configs and links.
   Record the actual environment and do not relabel historical evidence as new.
3. Recheck [capabilities](capabilities.md). Offline success or one deployment cannot
   certify universal account coverage. Do not claim a complete bill or working cutoff.
4. Update [CHANGELOG](../CHANGELOG.md) and notes with the exact commit, tested
   platforms, upgrade/rollback instructions, known issues and verification limits.
5. Obtain the owner's explicit version/tag/release approval. Then create the release,
   inspect source archives and any assets for private data, record checksums and
   verify links. A source-publication decision alone does not approve a versioned release.

Keep live installation and account evidence private. Publish a sanitized summary
only when approved. Coordinate security fixes privately before public release notes.

## Repository settings

[Publication](publication.md) covers the launch checks; [publication status](publication-status.md)
records verified settings. Follow [governance](governance.md) for required CI and
the owner's narrow review exception. Neither a workflow file nor a prepared ruleset
proves GitHub has enabled or enforced its setting.

## Technical archive

These documents preserve design and review history, including dated private-stage
snapshots. Their old counts, pins and deployment/publication status are historical.
Use [getting started](getting-started.md) for the installation pin and the current
[publication status](publication-status.md) for repository settings.

- [Design](design.md), [implementation plan](implementation-plan.md) and [progress](progress.md).
- [Initial implementation evidence](evidence.md), [independent reviews](verification/reviews.md)
  and the original [handoff snapshot](../handoff-status.json).
- [2026-10-26 documentation preparation](publication-readiness.md) and its
  [machine-readable checks](verification/publication-readiness.json).
- [2026-10-27 compatibility delivery](compatibility-delivery.md) and its regression evidence.
