# Public-launch repository protection

This is a prepared policy, **not an applied GitHub setting**. Public visibility and
ruleset activation require a separate explicit owner decision. On 2026-10-26 a
read-only repository query confirmed `main`, private visibility and all three merge
methods enabled. That snapshot is not proof of future protection.

GitHub Free supports branch rulesets in **public** repositories; private-repository
rulesets require a qualifying paid plan. Do not buy a plan or publish merely to
activate this draft. [GitHub ruleset availability](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets).

## Recommended launch profile: one maintainer

Use the [prepared ruleset JSON](examples/github-ruleset.public.json). It targets the
default branch through `~DEFAULT_BRANCH`, including a future default-branch rename.
The file is inert in Git; importing it activates its rules because its intended
enforcement is `active`. No installer or workflow applies it.

| Setting | Launch value and reason |
| --- | --- |
| Require a pull request | Yes; every default-branch change has a reviewable PR. |
| Required GitHub approvals | **0**; the sole maintainer must be able to merge their own PR. |
| Resolve review threads | Yes; address outstanding code conversations before merging. |
| Force pushes / branch deletion | Blocked on the default branch. Feature branches remain ordinary branches. |
| Bypass actors | None, including no standing admin bypass. |
| Merge methods in this ruleset | Merge commits only, preserving reviewed commits and ancestry. |
| Linear history | Off; it would conflict with merge commits. |
| Status checks / deployments | None; this repository has no CI or deployment gate to require. |

Zero required approvals does **not** mean zero review. Follow
[CONTRIBUTING](../CONTRIBUTING.md), review the exact diff and tests, and obtain the
independent review required by [maintaining](maintaining.md) for sensitive changes.
Agent review is evidence for the maintainer; it is not another person's GitHub
approval. The platform cannot enforce that manual process in this profile. Authors
cannot approve their own PRs, so requiring one approval now would block an owner PR
without an eligible second reviewer or an exception.
[GitHub approval rules](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/approving-a-pull-request-with-required-reviews).

The repository may keep squash/rebase enabled generally; this default-branch ruleset
allows only merge commits. If switching to squash/rebase and linear history later,
review both settings together and update commit-pinning/release instructions.
Require only real status checks once an explicitly approved check exists and has
reported successfully; an invented check name can strand PRs. Review threads and
merge methods are documented in [available rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets).

Rules are not immutable owner controls: an administrator can edit or disable a
ruleset. An empty bypass list removes routine exceptions while the ruleset is
active; it does not remove repository administration powers.
[Managing rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/managing-rulesets-for-a-repository).

## Later profile: a reliable second reviewer

After adding an eligible trusted collaborator, set required approvals to **1** and
enable stale-approval dismissal. Consider last-push approval only when a reviewer
other than both the PR author and most recent pusher will be available. Test the
review path before relying on it; a sole-owner CODEOWNERS entry does not solve
self-approval.

Add CODEOWNERS only for real owners with write access, then consider requiring
their review for credential handling, policy, persistence and installation. Include
the CODEOWNERS file itself. On a personal repository, do not invent organization
teams. [Code-owner eligibility and behavior](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners).

Keep bypass empty by default. If an emergency exception is later approved, GitHub's
**For pull requests only** bypass preserves a PR trail; **Always allow** permits
direct pushes. A review-bypass policy should be a separate ruleset from deletion
and force-push protections. Select the actual eligible actor in GitHub rather than
copying a guessed numeric role ID. The launch JSON contains no bypass actor.
[Creating rulesets and bypass permissions](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository).

## Owner activation after public launch approval

1. Complete [publication](publication.md), review the exact launch commit, and
   separately authorize the visibility change and this ruleset activation.
2. Once public, open **Settings → Rules → Rulesets → New ruleset → Import a
   ruleset** and choose the JSON. Inspect the default-branch target, active status,
   empty bypass list and every rule before saving. The file is also a REST
   create-ruleset request body; no API mutation is run by this preparation.
3. Read the saved ruleset back and inspect the rules applying to `main`. Confirm
   GitHub displays the required PR, merge method, thread-resolution and blocked
   force-push/deletion settings. Existing rulesets can add requirements; inspect
   them too. Do not claim tested rejection without observing it.
4. Use the next ordinary low-risk PR to verify the owner can merge after review
   and thread resolution. Record that result separately from offline JSON checks.
   Do not force-push or delete `main` as a test.

The field names and `~DEFAULT_BRANCH` selector follow GitHub's
[create-ruleset REST schema](https://docs.github.com/en/rest/repos/rules#create-a-repository-ruleset).
Local validation cannot prove GitHub accepted or enforced the configuration.

## Actions remain a separate decision

No workflow, runner, required check, automatic release or paid CI is introduced.
The launch plan recommends disabling Actions until a workflow is separately
approved; having no workflow files is different from disabling the repository setting.
If CI is separately approved later, start with a manually initiated offline test
run, no provider credentials and no deployment. Review runner costs and triggers
before enabling it.

At that later setup, choose restricted default `GITHUB_TOKEN` permissions
(read-only contents/packages), keep Actions PR creation/approval disabled, and
require approval for **all external contributors** before fork workflows run.
Inspect workflow changes and code before approving execution. These are proposed
future settings, not verified current settings. Workflow files can request wider
permissions; defaults are not a hard ceiling. Avoid `pull_request_target` for
untrusted contribution execution because fork approval restrictions do not apply
to that trigger. [GitHub Actions repository settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository).
