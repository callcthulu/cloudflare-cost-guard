# Repository governance

The repository uses a PR-first policy, a named maintainer and small offline checks.
The files below describe the intended configuration; their presence in Git does
not activate repository settings. See [publication status](publication-status.md)
for dated API readbacks, CI results and remaining verification.

## Two rulesets, separate responsibilities

Both prepared REST/import payloads target `~DEFAULT_BRANCH` and become active when
applied. Apply **both**; importing only the review rule leaves integrity unprotected.

| Ruleset | Rules | Bypass |
| --- | --- | --- |
| [Default branch integrity](examples/github-ruleset.public.json) | PR required, all conversations resolved, three passing offline checks with branch up to date, no force pushes or branch deletion, merge commits only | None, including the owner |
| [Default branch review](examples/github-ruleset.review.json) | One approval, code-owner approval, stale approvals dismissed, approval of the latest reviewable push by someone other than its pusher | Only `@callcthulu`, only through a PR |

Keeping these separate matters: the maintainer's review exception cannot bypass
the integrity ruleset's PR, CI, conversation, force-push or deletion requirements.
GitHub combines applicable rulesets. Merge commits preserve the reviewed commit
SHAs used by installation pins. Linear history is not required. See
[GitHub ruleset behavior](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
and [available rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets).

The owner cannot approve their own PR. For owner-authored changes, record manual
independent review and its limitations in the PR, then use the review-only bypass
after CI and all integrity requirements pass. Agent review supplies evidence; it
does not impersonate another person's GitHub approval. For external contributions,
the maintainer reviews and approves normally. The bypass technically permits the
owner to bypass review on any PR: limiting routine use to owner-authored changes
is a maintainer policy, not a GitHub-enforced condition. Any exceptional use should
record the reason and independent review. See [contributing](../CONTRIBUTING.md)
and [maintenance](maintaining.md).

`.github/CODEOWNERS` assigns every file, including itself and workflows, to the
actual owner `@callcthulu`. A 2026-10-27 permission query confirmed the owner's
`admin` role. The review payload uses that user's API-returned ID `34986874`,
not a guessed repository-role number. The current
[REST schema](https://docs.github.com/en/rest/repos/rules#create-a-repository-ruleset)
supports `User` actors with `pull_request` bypass; GitHub announced individual-user
bypass in its [May 2026 changelog](https://github.blog/changelog/2026-05-07-repository-rulesets-user-bypass-and-branch-renaming/).
API acceptance and saved settings still require launch readback. Code owners must
retain [write access](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners).

Administrators can edit or disable rulesets. These controls prevent ordinary
unsafe updates while active; they do not remove administrative powers.

## Offline CI

[`offline-tests.yml`](../.github/workflows/offline-tests.yml) runs on PRs, pushes to
`main` and manual dispatch. It allocates runners only for public repositories.
The stable required check names are:

| Check | Standard GitHub-hosted runner | Python |
| --- | --- | --- |
| `offline-linux-py311` | Ubuntu 24.04 | 3.11 |
| `offline-linux-py314` | Ubuntu 24.04 | 3.14 |
| `offline-windows-py314` | Windows 2025 | 3.14 |

Each runs `python -B -m unittest discover -s tests -v` with a ten-minute timeout.
The suite uses synthetic fixtures, injected transports and a loopback notification
receipt test. It installs no pip packages, needs no secrets or provider account,
uploads no artifacts and never invokes the root Linux lifecycle harness.
Passing CI does not establish service installation or live monitoring success.

The workflow grants only `contents: read`; checkout does not persist credentials.
There is no `pull_request_target`, untrusted PR text in shell commands, deployment,
self-hosted runner, dependency cache or automatic merge. The checkout v5 and
setup-python v6 refs were resolved through their official repository commit APIs
on 2026-10-27 and pinned to full SHAs. Weekly Dependabot checks cover GitHub Actions
only; every update still needs review and CI. See
[secure Actions usage](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions)
and [Dependabot configuration](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference).

## Launch and verification

The operator authorizes publication and settings separately from deployment.
GitHub Free supports rulesets for public repositories; do not buy a plan to apply
this policy. Before enabling execution, configure repository Actions settings:

- Allow only the reviewed `actions/checkout` and `actions/setup-python` actions;
  require full SHA action pins.
- Default `GITHUB_TOKEN` to read-only; disable Actions PR creation/approval.
- Require approval for **all external contributors** before fork workflows run.
  Review workflow and code changes before approving; approval executes untrusted code
  on an isolated hosted runner, even though no repository secrets are supplied.
- Use standard hosted runners only. No paid larger runners or private execution
  is part of this policy.

These settings follow [GitHub's repository Actions controls](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository).
Workflow permissions can request more than the repository default, so inspect
workflow updates even with restricted defaults. Enable available public-repository
secret scanning/push protection and private vulnerability reporting; verify the
result rather than assuming eligibility or successful activation.

Native CodeQL default setup may be enabled separately for Python. It is a
GitHub-managed scanning configuration, separate from the unit-test workflow above.
GitHub documents that default setup needs Actions enabled but is not governed by
other Actions policies; keep the narrow action allowlist and SHA requirement
instead of adding speculative exceptions. Verify its actual run and record the
result in publication status. See [GitHub's managed scanning policy exception](https://docs.github.com/en/enterprise-cloud@latest/admin/enforcing-policies/enforcing-policies-for-your-enterprise/enforcing-policies-for-github-actions-in-your-enterprise)
and [default setup](https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/configure-code-scanning/configure-code-scanning).

Run the public launch PR's checks before installing required-check rules. Verify
their exact names and producing GitHub App through the commit check-runs API.
The payload binds each check to GitHub Actions App ID `15368`, verified via
`GET /apps/github-actions`; verify actual run attribution before activation.
No invented or unreported required checks should block the bootstrap PR.

After application, read back both complete rulesets with owner authentication
(needed to see bypass actors), repository Actions settings and the rules applying
to `main`. Compare each rule, the integrity rule's empty bypass list and the review
rule's exact user/PR-only bypass. Record successful runs and a normal reviewed merge
separately from saved configuration. Do not force-push or delete `main` as a test.
Readback proves saved settings, not an observed rejection or fork approval exercise.
Keep pending acceptance tests explicit in [publication status](publication-status.md).
