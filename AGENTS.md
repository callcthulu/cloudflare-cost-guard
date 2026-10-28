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
  observations/latches/intents/outbox; `budget.py` accounts for guard signals;
  `cutoff.py` validates budget approvals and executes one action; `runner.py`
  orchestrates; `notify.py` delivers.
- Missing mode is **observe**, with zero mutating provider calls. `probe` and
  `enforce-preview` never mutate provider state. No executor token in observe.
  Automatic budget cutoff requires explicit arming of an existing installation;
  no live provider canary is claimed by source tests.
- Budgets allow zero or more USD/percentage warnings and zero or one hard cutoff.
  A missing/null hard limit never authorizes a write. Warnings are notification-only,
  use the same qualified signal and deduplicate by resource/source/period/threshold.
  Warning edits preserve cutoff approval; cutoff policy edits do not. Prioritize
  due cutoff outcomes over warnings and routine events without bypassing backoff.
- Unknown is not zero or healthy. Keep estimates, rated charges and subscription
  commitments separate. Use Decimal strings, UTC provider windows, explicit scope,
  known units and source quality. Account totals and breakdowns are not additive.
- Raw-threshold enforcement still requires exact evidence. Budget cutoff may use
  approximate/partial evidence only through explicit quality acceptance and a pinned
  version 2 approval. CPU planning reserves are neither observed CPU nor upper bounds.
  Rated guard evidence is the largest validated account line, never an assumed sum
  of disjoint charges. Never promise a guaranteed maximum bill.
- Identity is account + product + provider resource, not a display name or domain.
  Discovery does not enroll resources. Account costs do not identify a guilty site.
- Exactly approved stateless HTTP Workers support `delete_worker` with fixed
  `force=false`, or `disable_worker_endpoints` for workers.dev/preview flags only.
  Deletion requires explicit destructive/restore-source/stateless acknowledgements;
  owned Durable Objects, migrations, stateful bindings and ambiguous metadata block it.
  No R2/D1/Queues or other-product actions. Never remove Access, DNS or routes, change
  subscriptions, force deletion or add arbitrary commands. Read [automatic cutoff](docs/automatic-cutoff.md).
- Persist intent before a write. Reconcile uncertain attempts read-only; never
  automatically retry writes or re-enable endpoints. Trips survive unknown/healthy
  data. Operator rearm is local and explicit. It archives known terminal budget
  intents while preserving all usage; unresolved attempts block rearm. Preview/probe
  never write the budget ledger, outbox or action intents.

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
