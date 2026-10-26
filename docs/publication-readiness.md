# Open-source preparation record

Date: 2026-10-26. Scope: documentation/community metadata only, based on reviewed
implementation `7ea37012a0e321f4842579dcff8d3867e3f94ef5`. The repository remains
private; no release tag, deployment, GitHub setting change or provider action occurred.

## Delivered

- English onboarding from prerequisites and reviewed source to first observe report,
  scoped read credentials, optional generic webhook and explicit scheduling.
- Full configuration reference, account-only and Worker examples, troubleshooting,
  configuration/code updates, token rotation, state backup/restore and uninstall.
- [AGENTS.md](../AGENTS.md) and a [deployment prompt](agent-deployment.md) with clear
  operator approval boundaries and sanitized evidence requirements.
- Existing [MIT license](../LICENSE) retained, with contribution/support/security,
  community-conduct/changelog documents and ordinary issue/PR templates.
- [Maintainer guide](maintaining.md) and [publication checklist](publication.md),
  with the necessary owner launch steps and no invented contact address or SLA.

## Validation and independent review

The existing offline suite passes: 76 tests, zero failures, two Windows-specific
symlink skips. This change does not repeat or replace the historical disposable
Linux lifecycle or any live acceptance. The runtime, installer, tests, original
configuration example, license and ignore/line-ending settings are byte-identical
to the reviewed base (27 protected files).

Markdown links/anchors and shell syntax are checked locally. Complete synthetic
configuration examples are checked against the current parser; small fragments are
checked as JSON and in assembled configurations. YAML/frontmatter for issue metadata
is checked using an already available local validator, with no project dependency
added. No workflows, CI charges, new dependencies or automatic actions are introduced.
The README renders with headings, tables and code through GitHub's Markdown API;
this is not verification of the unmerged default-branch community/reporting UI.

An independent reviewer examined usability, installation safety, privacy/history,
licensing/reporting claims and agent authority. Findings were fixed: entering the
protected installed directory as the service user, replacing shell-dependent unit
path expansion, and explicitly scoping installer umask for fresh directory creation.
Installation now exports only the
reviewed commit's tracked files instead of promoting local cache/untracked files
into root-owned source. No remaining material blocker was found in this scope.

[Machine-readable checks](verification/publication-readiness.json) record the
precise local results. Heuristic scans and agent reviews are not security certification.

## Still separate owner decisions

The source changes need review/integration: implementation PR #1 first, then the
documentation PR. The default branch currently contains the bootstrap only.
Ordinary Issues remain disabled; templates will be available after integration and
explicit enablement. Public reporting requires GitHub's eligible public-repository
setting and real form/notification verification at launch.

The [checklist](publication.md) requires review of all publishable refs, archives
and GitHub issues/PRs/comments/attachments, including any private reports that would
be exposed. File/history checks do not inspect hidden or future GitHub attachments.
Before changing visibility, update any pre-launch wording and recheck the final
default-branch installation/security links. This preparation performs no visibility
change and does not claim those GitHub UI gates have passed.

Provider access, live installation, actual alert receipt, independent host monitoring,
a 24-hour observation and any canary remain separate deployment gates. The original
[handoff-status.json](../handoff-status.json) and [implementation evidence](evidence.md)
remain historical snapshots, not claims about this documentation change or a user's site.
