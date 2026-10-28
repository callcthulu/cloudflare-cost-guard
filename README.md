# Cloudflare Cost Guard

Self-hosted Cloudflare usage and subscription monitoring, alerts, and optional
cutoff for approved stateless Workers. Observe by default. Not a spending cap.

For operators who want Cloudflare evidence and notifications on infrastructure
they control. Runs on an existing Linux host with Python 3.11+, SQLite and systemd;
there are no third-party runtime packages to install. Missing or stale data stays
unknown. Account charges cannot identify which domain caused a cost.

## Try it without credentials

The synthetic demo runs the real monitoring incident logic with temporary SQLite
state and an in-memory message receiver. It makes no network requests, reads no
credentials and does not install or start services. Python 3.11+ is sufficient:

```sh
git clone https://github.com/callcthulu/cloudflare-cost-guard.git
cd cloudflare-cost-guard
python3 -B -m examples.monitoring_demo
```

On Windows, use `python`. The demo shows a positive subscription fee, repeat-alert
deduplication, missing evidence that cannot clear the fee incident, and recovery
after fresh evidence returns. Its temporary state is removed when it finishes;
the messages are simulated, not delivered email. Billing coverage remains an
explicit limitation throughout. The demo does not exercise provider reads or cutoff.

## Install and use

Follow [getting started](docs/getting-started.md) to install a reviewed commit,
create protected read-token files and obtain a first observe report. Installation
does not start the timer. Optional cutoff requires a separate explicit arming step;
the initial install remains read-only. For delegated setup, use the
[agent deployment guide](docs/agent-deployment.md).

Configure any number of USD or percentage [budget warnings](docs/budget-alerts.md),
or omit the hard limit for warning-only monitoring. Guard notifications support
email, Telegram, Slack and Discord in any combination, with independent retries.
See [notification setup](docs/notifications.md) and the
[synthetic example](config.notifications.example.json).

The [getting-started guide](docs/getting-started.md#5-install-validate-and-probe)
defines the installed `cfguard` shell helper. With that helper:

```sh
cfguard show-policy --config /etc/cloudflare-cost-guard/config.json
cfguard probe --config /etc/cloudflare-cost-guard/config.json
cfguard run --config /etc/cloudflare-cost-guard/config.json
cfguard status --config /etc/cloudflare-cost-guard/config.json
cfguard test-notification --config /etc/cloudflare-cost-guard/config.json --target ops-slack
```

`show-policy` displays sanitized current policies without provider calls, token
reads or opening state. `probe` collects read-only evidence without sending alerts;
`run` evaluates policy and delivers queued alerts; `status` reads local execution
state and displays current policies. `test-notification` previews one synthetic
message using configuration only; explicit `--send` sends it to the selected target.
It never collects Cloudflare data or flushes queued incidents. Unknown or warning results
need attention. With no notification receiver, pending alerts can produce exit 5;
that does not establish collection health or alert receipt. See
[configuration](docs/configuration.md), [operations](docs/runbook.md) and
[troubleshooting](docs/troubleshooting.md).

Exit codes: `0` completed, `2` invalid config, `3` unknown/collection/runtime
failure, `4` warning/incident, `5` action or pending/failed notification. For a run,
precedence is **5 > 4 > 3 > 0**; inspect JSON as well as the exit code.

Keep credentials, real configuration and deployment evidence outside Git. Optional
[independent monitoring](docs/monitoring.md) adds a read-only sampler and a watcher
on another host: guard outages, delayed notifications, positive subscription fees
and Worker/zone inventory drift. Use `python -B -m cfguard.monitoring`; the main
installer does not configure or start these optional services. Offline tests do
not prove live provider access, notification delivery or a maximum bill.

## Optional Worker cutoff

Explicit arming can authorize deletion of one approved stateless HTTP Worker
(`force=false`), or disable only its workers.dev/preview flags, when a selected
USD signal reaches `hard_limit_usd`. Deletion is destructive; endpoint disablement
does not stop other invocation paths. Follow [automatic cutoff](docs/automatic-cutoff.md)
for one-time approval, an independent restore source and arming. No approval is
requested per incident after arming. No other product actions are supported.

**The trigger is not a guaranteed maximum bill.** Usage estimates combine captured
request counts with a configured CPU planning reserve; CPU is not measured. The
alternative account-rated signal is a partial observed-charge floor. Collection
and action delays can cause overshoot. Subscription fees, taxes and unsupported
products are not bounded by an action. Check [capabilities](docs/capabilities.md)
and Cloudflare's [native budget alerts](https://developers.cloudflare.com/billing/manage/budget-alerts/)
alongside this tool; those alerts do not pause usage either.

## Verification and release status

This is early software. The [prepared prerelease notes](docs/releases/v0.1.0-alpha.1.md)
describe scope, upgrade precautions and limits. Source tests are not a live cutoff
canary or proof of a complete bill. Run the credential-free suite from the root:

```sh
python3 -B -m unittest discover -s tests -v
git diff --check
```

The [solution audit](docs/solution-audit-2026-10-28.md) and
[monitoring verification](docs/monitoring-verification.md) distinguish historical
results from current code and remaining live gates.

The [cutoff evidence](docs/automatic-cutoff-evidence.md) records regression tests,
independent security review and disposable Linux lifecycle verification.
The [budget-alert evidence](docs/budget-alerts-evidence.md) covers multiple warnings,
optional cutoff, priority delivery and policy inspection.
The [native notification evidence](docs/native-notifications-evidence.md) covers
channel adapters, independent delivery tracking and installed preview isolation.

## Contribute

Small, focused pull requests are welcome. Start with [CONTRIBUTING](CONTRIBUTING.md)
for development, testing and review. Use [Issues](https://github.com/callcthulu/cloudflare-cost-guard/issues)
for ordinary bugs and questions, and [private vulnerability reporting](SECURITY.md)
for security findings. See [support](SUPPORT.md), [community rules](CODE_OF_CONDUCT.md)
and the [changelog](CHANGELOG.md).

The [threat model](docs/threat-model.md) explains trust boundaries. Maintainers can
find review and release procedures, plus the historical technical archive, in
[maintaining](docs/maintaining.md).

[MIT licensed](LICENSE). Independent and unofficial; unaffiliated with and not
endorsed by Cloudflare. Cloudflare is a trademark of Cloudflare, Inc.
