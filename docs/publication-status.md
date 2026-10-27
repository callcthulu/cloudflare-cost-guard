# Public repository settings

This is the dated publication receipt. Its original source pin and runtime
comparison below predate automatic cutoff. See [current cutoff evidence](automatic-cutoff-evidence.md)
and [getting started](getting-started.md) for the feature's source and validation.

Verified on 2026-10-27 through GitHub API readbacks and actual workflow runs.
The [repository](https://github.com/callcthulu/cloudflare-cost-guard) is public;
an HTTPS clone succeeded with credential helpers, injected headers and token
environment variables disabled.

| Control | Observed setting |
| --- | --- |
| Default branch | `main`, protected |
| [Integrity ruleset](https://github.com/callcthulu/cloudflare-cost-guard/rules/25992270) | Active; PR required, conversations resolved, branch up to date, no force pushes or deletion, merge commits only; no bypass actors |
| Required checks | `offline-linux-py311`, `offline-linux-py314`, `offline-windows-py314`, each bound to GitHub Actions App `15368` |
| [Review ruleset](https://github.com/callcthulu/cloudflare-cost-guard/rules/25992272) | Active; one code-owner approval, stale approvals dismissed, last-push approval; only `@callcthulu` has a PR-only review exception |
| Workflow token | Read-only; Actions cannot approve PRs |
| Actions | Full SHA pins required; only `actions/checkout` and `actions/setup-python` allowed in repository workflows |
| Fork execution | Maintainer approval required for all external contributors |
| Security intake | GitHub private vulnerability reporting enabled |
| Secret protection | Secret scanning and push protection enabled; zero open secret alerts at verification |
| CodeQL | Python default setup enabled, standard hosted runner, weekly schedule; initial and subsequent scans succeeded |
| Dependency maintenance | Weekly Actions-only Dependabot; security alerts/updates enabled; updates still require review |
| Community | Issues enabled; Wiki, Pages and Projects disabled; merged feature branches deleted automatically |

The owner exception applies only to the review ruleset. It cannot bypass the
integrity ruleset's PR, CI, force-push or deletion requirements. For external PRs,
the maintainer reviews normally. See [governance](governance.md) and
[CONTRIBUTING](../CONTRIBUTING.md) for the review policy.

## Checks actually exercised

- [CI run 40582555276](https://github.com/callcthulu/cloudflare-cost-guard/actions/runs/40582555276)
  passed on reviewed commit `6bf35c783c7a7380b1243c8f7691122fc91b5b83`:

  | Check | Python | Result |
  | --- | --- | --- |
  | Linux / 3.11 | 3.11.17 | 107 passed |
  | Linux / 3.14 | 3.14.8 | 107 passed |
  | Windows / 3.14 | 3.14.9 | 106 passed, one symlink skip |

- Required checks were activated only after those exact check names and producing
  App IDs were observed. [PR #8](https://github.com/callcthulu/cloudflare-cost-guard/pull/8)
  then merged with all checks passing through the owner review exception.
  [The resulting main run](https://github.com/callcthulu/cloudflare-cost-guard/actions/runs/40582790373)
  also passed all three checks.
- [Initial CodeQL analysis](https://github.com/callcthulu/cloudflare-cost-guard/actions/runs/40581804742)
  succeeded without widening the action allowlist. Its one alert traced the explicit
  never-valid token in the disposable Linux test harness. Independent review
  confirmed it was synthetic; that specific alert was dismissed as a false positive.
  The query and test-file scanning remain enabled. There were zero open CodeQL
  alerts at verification; [the later main analysis](https://github.com/callcthulu/cloudflare-cost-guard/actions/runs/40582802054)
  also succeeded.

The first Linux/Python 3.14 CI run exposed a test's assumption about JSON-parser
nesting limits. The [reviewed test-only repair](https://github.com/callcthulu/cloudflare-cost-guard/pull/8)
injects the parser failure directly and verifies sanitization, no retry and recovery.
It does not change production parsing or weaken the error guard.

The [pre-publication review](verification/public-launch-review.md) covered accessible
history, GitHub surfaces, source, workflows and policies without a blocking finding.
Installation now pins the public source commit above; runtime and installer files
remain identical to compatibility commit `a00bedfca4fa89fbbfb4be4a49218257a0cd3caf`.
The [MIT license](../LICENSE) is unchanged.

No destructive force-push/deletion test or outside-contributor approval exercise
was performed. Readbacks prove saved settings, not rejection of every possible
unsafe operation. Publication did not deploy the service, access consumer credentials,
send outreach, establish live billing coverage or enable enforcement.
