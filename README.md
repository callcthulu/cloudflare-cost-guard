# Cloudflare Cost Guard

Watch Cloudflare usage, unexpected subscriptions and available rated charges from
an existing Linux host. Python 3.11+, standard library only, SQLite state, systemd.
Multiple accounts and domains are configuration. **This is not a spending cap.**

Default **observe** mode makes zero mutating provider calls. Missing or delayed
data is reported as unknown. Estimates, rated usage and subscription commitments
remain separate. Read [current capabilities](docs/capabilities.md) before relying
on coverage: the billing API is Alpha; CPU totals and most product fast metrics
are unavailable; adaptive Workers data cannot authorize cutoff.

## Start safely

Run offline tests without credentials or provider access:

```sh
python3 -m unittest discover -s tests -v
```

For Linux installation, use a reviewed checkout in a root-controlled directory:

```sh
sudo python3 deploy/install.py prepare
# Prepare a private, root-owned config from config.example.json, and provision
# read tokens as root:cloudflare-cost-guard 0640 at its external file paths.
sudo python3 deploy/install.py install --config /root/cfguard-config.json
cd /opt/cloudflare-cost-guard
sudo -u cloudflare-cost-guard python3 -B -m cfguard validate --config /etc/cloudflare-cost-guard/config.json
```

No timer is enabled by installation. Follow the [runbook](docs/runbook.md) to probe,
approve a notification destination and explicitly start observe monitoring. Never
paste tokens into commands, configuration JSON, Git, issues or chat.

## Commands

All commands take `--config /absolute/protected/config.json` after the command.

| Command | Behavior |
| --- | --- |
| `validate` | Validate configuration; no provider calls. |
| `probe` | Read-only capability collection; no actions or notifications. |
| `run` | One bounded collection/evaluation/outbox run; observe by default. |
| `status` | Local scheduler/collection timestamps and incident counts. |
| `rearm` | Explicitly clear an enrolled local latch; never re-enable endpoints. |
| `enforce-preview` | Check a proposed plan; never mutate provider state. |

Exit codes: 0 completed/healthy, 2 invalid configuration, 3 collection/quality/lock
failure, 4 incident, 5 action or pending/failed notification. Precedence within a
run is 5 > 4 > 3 > 0. Inspect the JSON report as several conditions can coexist.
No configured alert destination means alerts remain pending, not delivered.

## Limits and rollout

The narrow executor is tested with fake APIs. Production enforcement is deliberately
blocked while exact fresh metrics, full standalone inventory and unambiguous public
cutoff proof cannot be established. It cannot stop every internal invocation or
storage charge. Do not add an executor token to an observe installation.

An independent heartbeat monitor is required to detect a stopped host. A live
read-only probe, actual alert receipt, scheduled observe runs, a 24-hour window and
a separately approved disposable canary are distinct release gates. No live checks
are implied by offline tests. See [handoff status](handoff-status.json) and
[evidence](docs/evidence.md) for this implementation's actual results.

Documentation: [configuration](docs/configuration.md), [operations and rollback](docs/runbook.md),
[enforcement](docs/enforcement.md), [threat model](docs/threat-model.md),
[security reporting](SECURITY.md), [Linux testing](docs/linux-testing.md),
[design](docs/design.md), [acceptance plan](docs/implementation-plan.md),
[publication checklist](docs/publication.md).
Implementation tracking: [ledger](docs/progress.md), [independent reviews](docs/verification/reviews.md).
