# Contributing

Read the [README](README.md), [capabilities](docs/capabilities.md) and
[security policy](SECURITY.md) first. For an ordinary bug or feature, check existing
issues and describe the problem and a focused scope. Report vulnerabilities
privately through [SECURITY.md](SECURITY.md).

## Make a change

Fork the repository, create a branch separate from `main`, and submit a small pull
request. Maintainers working in this repository also use dedicated branches.
Explain the resulting behavior, validation and remaining limits. Update the README
or linked guides when usage changes. Follow the [code of conduct](CODE_OF_CONDUCT.md).

Python 3.11+ and the standard library are sufficient. From the repository root:

```sh
python3 -B -m unittest discover -s tests -v
git diff --check
```

On Windows, use `python`. The suite uses synthetic fixtures and injected
transports; a notification test uses local loopback. It needs no credentials,
pip packages, Linux root or external provider access. For behavior changes, add
meaningful regression coverage at the changed trust boundary, including rejected
and unknown inputs where relevant.

The root lifecycle harness creates users and fixed service paths. Run it only in
a fresh disposable Linux fixture following [Linux testing](docs/linux-testing.md),
never on a workstation or shared host. A contribution does not authorize a live
provider query, installation, notification or cutoff.

## Keep the boundaries intact

- Observe mode makes no provider writes. Discovery never enrolls a resource.
- Preserve unknown, stale, incomplete and approximate evidence. Keep usage estimates,
  rated charges and subscription commitments separate; account totals and breakdowns
  are not additive. Cite current official documentation when changing API contracts.
- Use synthetic examples and fixtures. Keep credentials, real IDs, endpoint URLs,
  deployment config, databases, raw reports and notification payloads outside Git.
- Inspect the full diff and new commit history before opening a PR. Automated
  scanning helps; `.gitignore` does not sanitize tracked files or history.

## Review and license

Required offline CI and resolved review threads gate merging. A human maintainer
reviews the diff and validation; sensitive changes to credentials, accounting,
persistence, installation or actions also need independent review. Agent review
is evidence for that decision, not human approval. The owner exception to the
approval-count rule does not bypass required CI. See [branch governance](docs/governance.md)
for the policy and [publication status](docs/publication-status.md) for verified
repository settings.

Contribute only material you have the right to license under the [MIT license](LICENSE).
Contributions use the same license; no CLA or DCO sign-off is required. Changes to
workflows, release automation or deployment need explicit maintainer review.
