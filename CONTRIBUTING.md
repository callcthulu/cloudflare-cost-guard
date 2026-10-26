# Contributing

Cloudflare Cost Guard is a private, pre-release project preparing for possible
public reuse. Publication is a separate maintainer decision. Read the
[README](README.md), [capabilities](docs/capabilities.md),
[design boundaries](docs/design.md) and [security policy](SECURITY.md) first.

## Propose a focused change

Use the repository's issue templates for ordinary bugs or feature proposals when
Issues is enabled. Describe the problem, expected behavior and a small proposed
scope. Check existing issues and pull requests before opening another one.
Security findings follow [SECURITY.md](SECURITY.md), not a public issue or PR.

Work on a dedicated branch separate from `main` or `master`; submit a small pull
request for review. Do not push changes directly to the default branch. Explain
behavior, limits, validation and any unresolved evidence in the PR. Changes to
API contracts should cite current official Cloudflare documentation and preserve
unknown, incomplete, stale and approximate evidence instead of treating it as zero.

## Develop and verify locally

Python 3.11+ and the standard library are sufficient; there are no pip dependencies.
From the repository root, run the offline suite as an unprivileged user:

```sh
python3 -m unittest discover -s tests -v
```

On Windows, `python` can replace `python3`. The suite uses synthetic fixtures and
injected transports; its notification receipt check uses local loopback only.
It needs no credentials or external provider access. Never use real account data
to make a test pass. Add meaningful regression tests for changed behavior,
including rejected/unknown inputs and failure paths when changing security or
enforcement boundaries. Avoid tests that only repeat implementation details.

Linux installation and lifecycle checks require a fresh disposable VM or WSL2
distribution with systemd. Follow [Linux testing](docs/linux-testing.md); never run
the root lifecycle harness on a production or shared host. Routine contribution
checks must not install services, contact Cloudflare, send real notifications or
perform live containment. Offline success does not establish live safety.

## Before requesting review

- Update the README and relevant linked docs when commands, behavior or limits change.
- Review the complete diff and any new commits/history for secrets and private data.
  Automated scanning is only an aid; review examples, logs and metadata manually.
- Keep fixtures synthetic. Do not commit generated/deployment configuration, approval
  manifests, tokens, account or zone IDs, endpoint URLs, state databases, exports,
  raw reports or notification payloads. Use `config.example.json` as a synthetic
  reference; keep local files in ignored locations and check `.gitignore` coverage.
- Preserve observe mode's zero provider writes, separate ledgers and explicit
  enforcement gates. Describe exactly what was checked and what remains unverified.
- Do not add paid CI, workflows or automatic publication/deployment without separate
  maintainer review. This project currently runs no GitHub Actions workflows.

Maintainers review changes before merging. Follow the
[code of conduct](CODE_OF_CONDUCT.md). Only contribute material you have the right
to license under the repository's existing [MIT license](LICENSE); contributions
are made under that license. No separate CLA or mandatory DCO process is specified.

The prepared [public branch policy](docs/governance.md) requires PRs and resolved
threads, blocks default-branch force pushes/deletion and provides no routine bypass.
It is not active until the owner explicitly launches and verifies it. The solo
profile requires zero GitHub approvals so an owner's PR is not stranded; manual
independent review remains a maintainer gate, not enforced human approval or CI.
