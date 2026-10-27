# Cloudflare Cost Guard

Self-hosted monitoring for Cloudflare usage, subscriptions and available rated
charges. Runs on an existing Linux host with Python 3.11+, SQLite and a systemd
timer. No runtime dependencies to install.

**Best-effort monitoring, not a spending cap.** Observe mode uses read-only tokens
and makes no provider writes. Missing data stays unknown. Workers requests cover
an approximate rolling five-minute window; aggregate CPU and complete rated totals
are unavailable. Real enforcement is currently unsupported. See the
[capability matrix](docs/capabilities.md) before relying on a report.

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
does not start the timer. For delegated setup, use the
[agent deployment guide](docs/agent-deployment.md).

## Use it

The [getting-started guide](docs/getting-started.md#5-install-validate-and-probe)
defines the installed `cfguard` shell helper. With that helper:

```sh
cfguard probe --config /etc/cloudflare-cost-guard/config.json
cfguard run --config /etc/cloudflare-cost-guard/config.json
cfguard status --config /etc/cloudflare-cost-guard/config.json
```

`probe` collects read-only evidence without sending alerts; `run` evaluates policy
and delivers queued alerts; `status` reads local state. Unknown or warning results
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
