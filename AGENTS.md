# Working on Cloudflare Cost Guard

This file guides coding assistants. It grants no deployment, credential, provider
mutation, publication or messaging permission. Honor the operator's current scope.

## Read first

1. [README](README.md): purpose and current limits.
2. [Capabilities](docs/capabilities.md) and [threat model](docs/threat-model.md):
   facts the implementation may claim, and trust boundaries.
3. [Contributing](CONTRIBUTING.md): development and review.
4. For deployment, follow [the agent deployment guide](docs/agent-deployment.md)
   and [getting started](docs/getting-started.md), not a guessed install command.

## Architecture and invariants

- Python 3.11+ standard library, JSON configuration, SQLite, Linux systemd. No
  runtime dependency installation, web UI, hosted Worker or general plugin framework.
- `config.py` validates administrator-owned configuration; `cloudflare.py` collects
  bounded evidence; `policy.py` evaluates without I/O; `state.py` persists private
  observations/latches/intents/outbox; `runner.py` orchestrates; `notify.py` delivers.
- Missing mode is **observe**, with zero mutating provider calls. `probe` and
  `enforce-preview` never mutate provider state. No executor token in observe.
  Current real enforcement is unavailable.
- Unknown is not zero or healthy. Keep estimates, rated charges and subscription
  commitments separate. Use Decimal strings, UTC provider windows, explicit scope,
  known units and source quality. Account totals and breakdowns are not additive.
- Adaptive analytics/unknown sampling cannot authorize a cutoff. CPU quantiles are
  not aggregate CPU. The current real adapter cannot establish a complete rated
  balance. Never promise a hard spending cap.
- Identity is account + product + provider resource, not a display name or domain.
  Discovery does not enroll resources. Account costs do not identify a guilty site.
- The only possible executor write disables both workers.dev/preview flags on an
  exactly approved standalone Worker. All other mutations are out of scope: never
  remove Access, DNS or routes, change subscriptions, or add arbitrary commands.
- Persist intent before a write. Reconcile uncertain attempts read-only; never
  automatically retry writes or re-enable endpoints. Trips survive unknown/healthy
  data. Operator rearm is local and explicit.

## Development workflow

Work on a dedicated branch, with bounded changes and independent review for safety
or release work. Inspect Git state before editing; do not discard unrelated work.
Do not merge, tag, publish, change visibility or install on a real host without
operator authorization. Agent output is evidence to review, not approval.

Use synthetic fixtures and injected transports. Run from the repository root:

```sh
python3 -B -m unittest discover -s tests -v
git diff --check
```

Use `python` on Windows if appropriate. The unit suite needs no credentials, provider
access, pip install, Linux root or container daemon. Never run `tests/linux_lifecycle.py`
on a workstation/shared server: it creates real users and fixed service paths and
belongs only in a fresh, explicitly disposable Linux fixture. See [Linux testing](docs/linux-testing.md).

For behavior changes, reproduce the issue and add meaningful regression coverage at
its trust boundary. For documentation changes, verify commands, configs, links and
safety claims; do not change runtime merely to shorten a guide. Record actual
commands/results and untested platforms.

## Privacy and completion

Keep tokens, secret URLs, account/zone IDs, host identities, original private handoffs,
live configuration, SQLite, private notifications and raw deployment evidence outside
Git, PRs, chat and public support reports. Use external protected file paths, synthetic
IDs and report `resource_ref` values. `.gitignore` does not sanitize tracked files/history.

Before a PR, inspect diff/history for sensitive data. Explain changes, tests and limits.
Preserve historical evidence as a dated snapshot; never overwrite it to imply new
live verification. Report offline code, Linux lifecycle and live gates separately.
Never claim user approval, notification receipt or production success without evidence.
