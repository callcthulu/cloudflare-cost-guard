# Cloudflare Cost Guard

Monitor Cloudflare usage, unexpected subscriptions and available rated charges
from an existing Linux host. Python 3.11+, standard library only, private SQLite
state and a systemd timer. **This is best-effort monitoring, not a spending cap.**

Initial **observe** mode uses read tokens only: no mutating provider calls.
Missing or delayed evidence stays unknown. Workers requests are approximate and
cover a rolling five-minute window; CPU totals, complete rated totals and most
other product metrics are unavailable. Real enforcement is blocked by evidence
and inventory limits. Read the [capability matrix](docs/capabilities.md).

## Start here

- **Install and get a first report:** [getting started](docs/getting-started.md).
- **Delegate setup safely:** [agent deployment guide](docs/agent-deployment.md).
- **Choose accounts, zones and thresholds:** [configuration](docs/configuration.md).
- **Operate, update, back up or remove:** [runbook](docs/runbook.md).
- **Investigate a result:** [troubleshooting](docs/troubleshooting.md).

Supported service deployment is Linux with systemd. Disposable Ubuntu 24.04 /
Python 3.12 evidence and offline Windows/Python 3.14 checks are recorded in
[evidence](docs/evidence.md). Python 3.11 is the minimum code requirement, not a
claim that every supported Python/distribution combination has been tested.
No pip packages, containers or new Cloudflare purchases are required.

For a credential-free local check from a reviewed source checkout:

```sh
python3 -m unittest discover -s tests -v
```

This project is pre-release. While the repository is private, access requires
authorization. The installation guide pins the verified implementation commit;
`main` now includes the integrated application and documentation. Installation
never enables the timer. Keep tokens,
actual configuration, notification URLs and private evidence outside Git and chat.

## Commands and results

Run installed commands from `/opt/cloudflare-cost-guard` as the dedicated
`cloudflare-cost-guard` user, with `--config /etc/cloudflare-cost-guard/config.json`.

| Command | Behavior |
| --- | --- |
| `validate` | Validate configuration; no provider calls or token-content check. |
| `probe` | Read-only provider collection; no notifications/actions. Initializes local state and lock if absent. |
| `run` | One collection, policy and outbox cycle; observe mode initially. |
| `status` | Local timestamps, pending notifications and latch counts; no provider calls. |
| `rearm` | Explicitly reset an enrolled local latch; never reopen endpoints. |
| `enforce-preview` | Evaluate an eligible proposed plan without remote mutation; not a readiness certificate. |

Exit codes: `0` completed/healthy, `2` invalid configuration, `3` unknown
collection/quality or runtime/lock failure, `4` warning/incident, `5` action or
pending/failed notification. Within a run, precedence is **5 > 4 > 3 > 0**.
Inspect JSON: a notification result can mask collection failures in the exit
code. An unset webhook leaves alerts pending.

An external heartbeat, actual approved alert receipt, two scheduled observe runs
and a 24-hour availability window are separate operational gates. Offline tests
prove none of those live outcomes. See [handoff status](handoff-status.json).

## Project documentation

| Topic | Documents |
| --- | --- |
| Operation and boundaries | [Capabilities](docs/capabilities.md), [enforcement](docs/enforcement.md), [threat model](docs/threat-model.md), [Linux testing](docs/linux-testing.md) |
| Design and validation | [Design](docs/design.md), [implementation plan](docs/implementation-plan.md), [progress](docs/progress.md), [evidence](docs/evidence.md), [independent reviews](docs/verification/reviews.md) |
| Contribution and maintenance | [Contributing](CONTRIBUTING.md), [agent instructions](AGENTS.md), [maintaining](docs/maintaining.md), [changelog](CHANGELOG.md) |
| Community and release | [Support](SUPPORT.md), [code of conduct](CODE_OF_CONDUCT.md), [security reporting](SECURITY.md), [publication checklist](docs/publication.md), [launch plan](docs/launch-plan.md), [branch governance](docs/governance.md), [MIT license](LICENSE) |

The [open-source preparation record](docs/publication-readiness.md) separates
completed repository checks from the owner's remaining launch decisions.
