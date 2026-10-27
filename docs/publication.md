# Publication checklist

Use this checklist for source publication. Deployment, provider changes, outreach
and a versioned release each need their own authorization. Record observed results
in [publication status](publication-status.md); a checklist is not a settings receipt
or security certificate.

## Review the source

- Retain the [MIT license](../LICENSE), attribution and unofficial-project notice.
- Verify [README](../README.md), [installation](getting-started.md), configuration,
  operations, security reporting and contribution instructions against the selected
  commit. No fictitious tags, badges, tests or live passes.
- Inspect all publishable files, history, refs, archives and GitHub conversations,
  comments, attachments and logs. Resolve private material before visibility changes;
  `.gitignore` is not retroactive. Keep private deployment evidence outside Git.
- Resolve independent security/privacy/documentation findings. Run offline tests and
  verify links and examples. Preserve [capability limits](capabilities.md).

## Configure and verify GitHub

1. Confirm the exact reviewed revision and the owner's source-publication decision.
2. Change visibility, then apply and read back [branch governance](governance.md):
   required CI, PRs, resolved threads, no direct default-branch pushes, force pushes
   or deletion. The owner's approval-count exception must not bypass CI.
3. Enable Issues and private vulnerability reporting. Check the
   [reporting form](https://github.com/callcthulu/cloudflare-cost-guard/security/advisories/new)
   and maintainer notification settings. Verify public support/conduct links.
4. Inspect Actions permissions, fork approval policy and successful required checks.
   Keep execution read-only and credential-free; no provider or deployment secrets.
5. Read back security/scanning settings where available without buying a plan.
   Scanning is additional evidence, not proof of absence of secrets.
6. Verify anonymous cloning and the normal reviewed PR path. Record configured
   settings separately from behavior actually observed; do not force-push/delete the
   default branch as a test.

## Keep deployment evidence separate

Source publication proves no live API coverage, production install, alert receipt,
24-hour observation or cutoff. Preserve those as unverified until separately
established on an authorized installation. For releases use
[maintaining](maintaining.md#manual-release-process).
