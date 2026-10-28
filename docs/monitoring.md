# Independent monitoring

`python -B -m cfguard.monitoring` provides an optional read-only sampler and a
watcher on another existing host. It detects a stopped guard, delayed guard
notifications, positive subscription commitments, Worker/zone inventory drift and
lost visibility. Python 3.11+ and the standard library suffice. It neither runs
the guard nor changes its mode, state, Cloudflare resources or cutoff approvals.
It cannot cap a bill or discover every chargeable product.

## Data and policy

The sampler reads the guard's current schema-6 SQLite format in URI read-only mode
with a consistent transaction. It reads current account snapshots/subscriptions
and guard timestamps, then collects bounded Worker and zone inventories through
GET-only Cloudflare requests. It atomically writes its own version-1
[sanitized observation](monitoring-schema.md). Real IDs, domains, plan names, raw
errors, credentials and recipients stay on the source host. Discovery never
enrolls a resource for cutoff.

The watcher reads a local observation or retrieves the fixed private observation
path through SSH. It needs no Cloudflare token or guard database. Defaults allow
900 seconds for observation, guard-finish and snapshot age, 60 seconds of future
timestamp tolerance, and 900 seconds before a continuing notification backlog
warns. A fresh sampler does not conceal a stopped guard. Guard state has no
notification enqueue timestamp: watcher first-seen tracking detects continuing
backlog, but age before the first observation is unknown.

Every valid positive USD subscription row warns, including an allowed plan; rows
are not summed. Malformed/non-USD/conflicting evidence also leaves visibility
unknown. Expected Worker/zone IDs form an administrator-reviewed private baseline.
Only complete account-bound inventory can establish additions/removals or clear
drift. Never accept the first discovered inventory automatically as the baseline.
Other products, Registrar renewals, tax and unbilled fees are outside this view.
Collection time is not proof of provider freshness.

Known limitations acknowledge one exact account/source/status, such as unavailable
billing coverage. They stay visible without repeated alerts for the acknowledged
static condition. New failures, changed limitations and loss of previously
affirmative coverage still alert. The watcher separately pins the expected account
references so removing an account from an observation cannot silently reduce scope.

## Configure and preview

Start from the synthetic [sampler](../config.monitoring-sample.example.json),
[watcher](../config.monitoring-watch.example.json) and
[SMTP](../config.monitoring-smtp.example.json) examples. Copy configuration outside
Git to protected files; populate real account IDs, expected resource IDs, paths,
SSH profile and destination privately. Do not publish filled configuration,
observations, SQLite, raw logs or deployment evidence.

The generic configuration directory is `/etc/cloudflare-cost-guard-monitor`.
Sampler output lives in `/var/lib/cloudflare-cost-guard-monitor`; the independent
watcher's state uses `/var/lib/cloudflare-cost-guard-monitor-watch`. Keep these
administrator-controlled. Protect observations/state with private
directory/file permissions. Sampler secrets support service-owned `0600` or
root-owned `0640` for the effective service group; parent directories must resist
non-administrator replacement. Verify existing service identity and access before
adapting templates. Do not weaken guard state/token permissions to make sampling work.

On the guard host, the installed module lives under `/opt/cloudflare-cost-guard`.
Run as the existing service identity, from that directory:

```sh
python3 -B -m cfguard.monitoring validate --config /etc/cloudflare-cost-guard-monitor/sample.json
python3 -B -m cfguard.monitoring sample --config /etc/cloudflare-cost-guard-monitor/sample.json \
  --output /var/lib/cloudflare-cost-guard-monitor/observation.json
```

Sampling reads the configured guard database and makes provider reads. Validate
token scopes first: approved Worker Scripts Read and account-filtered zone
visibility are required for inventory. Denial remains unknown; broadening scopes
needs separate review. Worker inventory is single-page; zones use consistent
account-filtered pagination, at most 32 pages of 50, including supported zone
types. Missing/changing pagination metadata invalidates completeness.

The watcher can run from the same reviewed source checkout on an independent
existing host. It needs no enforce configuration, executor token or root guard
installation. Run from the checkout root:

```sh
python3 -B -m cfguard.monitoring validate --config /etc/cloudflare-cost-guard-monitor/watch.json
python3 -B -m cfguard.monitoring watch --config /etc/cloudflare-cost-guard-monitor/watch.json
```

Default watch is stateless preview: it reads the configured local/SSH observation,
but reads no SMTP password, writes no monitoring state and sends nothing. It
cannot show historical coverage-loss transitions or queued delivery. Persistent
mode supplies those checks; preview is not a substitute for reviewing its state.

For SSH, use a dedicated approved profile with BatchMode and strict known-host
checking. The only remote command is:

```sh
/usr/bin/head -c 2097153 /var/lib/cloudflare-cost-guard-monitor/observation.json
```

Provision a narrow forced-command key with no forwarding or administration access.
Review the exact user/key/group access separately; no account/key provisioning is
automated. Authentication or host-key failure must not trigger fallback or wider
permissions. Never expose a public observation URL or grant remote SQLite access.

## Persistent incidents and email

`watch --apply` reads the protected SMTP settings to bind the destination and
persists incidents, evidence history and queued events only in the watcher's own
state. It sends nothing without `--send`. It produces bounded degradation reminders, normally every
24 hours, and a recovery only after fresh affirmative evidence for the same scope.
Unknown/missing/stale evidence cannot clear an incident. Recurrence cancels a queued
recovery; recovery cancels obsolete unsent alerts.

After reviewing the exact destination and send scope, append `--send`:

```sh
python3 -B -m cfguard.monitoring watch --config /etc/cloudflare-cost-guard-monitor/watch.json --apply --send
```

`--send` requires `--apply` and can send all due monitoring events up to the
per-run bound of three; it is not a one-message notification test. Preview a
disposable synthetic observation with separate temporary monitoring state for the
first approved receipt check. Do not flush real pending incidents as a test.
Verified TLS is required. SMTP acceptance is distinct from owner-confirmed receipt;
timeouts/crashes can cause duplicates. Retry backoff is retained across restarts.
Due fee, inventory and account-set alerts precede routine coverage events.

Events bind to the SMTP destination identity. A changed destination cancels old
pending messages instead of redirecting them; password rotation for the same
destination preserves binding. Inspect cancellation evidence and retain the old
configuration privately. Independent guard-native notifications remain separate.

Exit codes: `0` no active actionable issues (limitations may remain), `2` invalid
configuration/evidence, `3` monitor unavailable/overlap, `4` active issue, `5`
pending/failed delivery. Inspect the JSON evidence as well as the exit code.

## Optional systemd scheduling

Templates are provided for [sampling](../deploy/cfguard-monitor-sample.service),
[its timer](../deploy/cfguard-monitor-sample.timer),
[watching](../deploy/cfguard-monitor-watch.service) and
[its timer](../deploy/cfguard-monitor-watch.timer). The main guard installer does
not configure, install or activate them. Review/adapt identity, checkout path,
permissions, writable paths, configuration and the independent host before copying
units. The watcher service includes `--apply --send`: starting it sends due emails.

Before scheduling, validate both configs, compare one authorized sampler result to
the provider view, inspect sanitization and account binding, verify narrow SSH and
owner-confirmed receipt, and exercise synthetic failures/recovery. Verify adapted
units on the actual Linux host with `systemd-analyze verify`. Keep timers stopped
until those decisions are explicit. Confirm two real scheduled processes and a
24-hour availability/freshness record, not merely enabled timer settings. Windows
tests do not establish POSIX permissions or systemd behavior. The watcher needs its
own external uptime check or an explicitly accepted blind spot.

For recovery, restore the failed read/sampler/mail path, preview the fresh evidence,
then resume persistent watch. Keep state: deleting it erases incident, reminder,
coverage-history and destination-binding evidence. Do not rebaseline drift merely
to silence it. For rollback stop/disable only the optional monitoring timers on
their respective hosts, wait for services to finish, preserve private state and
remove only reviewed optional files. Do not uninstall the shared guard package,
change guard timers, restore provider resources or alter backups as monitoring
rollback. Revoke only newly provisioned monitoring credentials through the normal
approved process. See [verification boundaries](monitoring-verification.md).
