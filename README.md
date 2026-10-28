# Cloudflare Cost Guard

Self-hosted automatic budget cutoff for explicitly selected stateless Cloudflare
Workers, with configurable budget warnings and read-only monitoring as the default.
Runs on an existing Linux host with Python 3.11+, SQLite and a systemd timer.
No runtime dependencies to install.

Once armed, the guard automatically deletes the approved Worker (`force=false`)
or disables its workers.dev/preview flags when the selected USD signal reaches
`hard_limit_usd`. Budget warnings are independent: configure any number of USD
or percentage thresholds, or omit the hard limit for warning-only monitoring.
See [budget alerts](docs/budget-alerts.md) for editable examples and safe updates.
Send warnings and cutoff outcomes directly to email, Telegram, Slack or Discord,
in any combination, with independent retries. See [notification setup](docs/notifications.md)
and the [complete synthetic example](config.notifications.example.json).
No approval is requested per cutoff incident. Deletion is destructive;
endpoint disablement covers only those flags. Follow [automatic cutoff](docs/automatic-cutoff.md)
for supported targets, one-time approval, independent restore source and arming.

**An action trigger, not a guaranteed maximum bill.** Usage cost combines captured
request counts with a configured CPU planning reserve; CPU is not measured. The
alternative account-rated signal is a partial observed-charge floor. Missing data
stays unknown, and collection/action delays can cause overshoot. Read the
[capabilities](docs/capabilities.md) and guide's verification limits before use.

## Get started

Try the offline tests without credentials, root access or provider calls:

```sh
git clone https://github.com/callcthulu/cloudflare-cost-guard.git
cd cloudflare-cost-guard
python3 -B -m unittest discover -s tests -v
```

On Windows, use `python`. Service installation requires Linux with systemd.

Follow [getting started](docs/getting-started.md) to install a reviewed commit,
create protected read-token files and obtain a first observe report. Installation
does not start the timer. Optional cutoff requires a separate explicit arming step;
the initial install remains read-only. For delegated setup, use the
[agent deployment guide](docs/agent-deployment.md).

## Use it

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

Keep credentials, real configuration and deployment evidence outside Git. The host
needs its own independent outage monitoring. Offline tests do not prove live
provider access, notification delivery or a maximum bill.

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
