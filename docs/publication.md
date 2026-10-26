# Publication checklist

Preparation is complete only after reviewed files are integrated; publication itself
requires the owner's explicit decision. Keep source publication separate from live
deployment/enforcement. This checklist is not a security certificate.

## Repository preparation

- Retain [MIT LICENSE](../LICENSE), attribution and an unofficial-project notice.
- Provide a clear [README](../README.md), complete [installation guide](getting-started.md),
  [configuration](configuration.md), [operations/rollback](runbook.md) and
  [troubleshooting](troubleshooting.md). Examples must be synthetic and work against
  their documented revision. No fictitious tags, badges, releases or live passes.
- Provide [contribution guidelines](../CONTRIBUTING.md), [support](../SUPPORT.md),
  [security policy](../SECURITY.md), [community rules](../CODE_OF_CONDUCT.md),
  [changelog](../CHANGELOG.md), issue/PR templates and [agent instructions](../AGENTS.md).
- Preserve honest [capabilities](capabilities.md), [threat model](threat-model.md),
  [development evidence](evidence.md) and unverified live gates. No hard-cap claim.
- Inspect current files **and all publishable history/branches/tags** for secrets,
  private configuration, resource IDs, original handoffs, host identities, payment
  and notification data. `.gitignore` is not retroactive. Check release archives.
- Inspect private issues, PRs, attachments, comments, security reports and logs that
  could become visible with the repository. Resolve sensitive material before launch;
  don't assume changing visibility publishes only the default branch.
- Resolve independent review findings; verify links, configuration/CLI examples and
  relevant tests. No `.github/workflows` or paid CI is added by this preparation.

## Owner launch actions — not performed by this change

1. Review/integrate implementation PR #1, then the documentation PR, so the default
   branch has the complete application/license/docs. The bootstrap is not a release.
2. Review the exact commit/history/artifacts to publish and approve the visibility
   change. Copies may persist: making the repo private again does not recall copies
   or revoke a leaked credential.
3. Enable ordinary Issues if accepting reports; templates alone do not enable them.
4. Enable **private vulnerability reporting** on the public repository, verify
   [Report a vulnerability](https://github.com/callcthulu/cloudflare-cost-guard/security/advisories/new)
   works for an eligible non-maintainer, and ensure maintainers receive notifications.
   This public intake cannot be verified while the repo remains private. Follow
   [GitHub's setup instructions](https://docs.github.com/en/code-security/security-advisories/working-with-repository-security-advisories/configuring-private-vulnerability-reporting-for-a-repository).
5. Review reported-content moderation and monitor normal issues. Verify the conduct
   reporting routes; do not invent a personal contact address to fill a template.
6. If publishing a release, separately approve version/tag and use
   [the manual release process](maintaining.md#manual-release-process). Until then,
   label the project pre-release and install an explicitly reviewed commit.

## Separate deployment gates

Source readiness proves no real provider probe, deployment, alert receipt, 24-hour
window or live cutoff. Keep each false/unverified until separately proved on an
authorized installation. The real executor cannot currently prove its eligibility;
a public repo must not turn that limitation into an enabled default.
