# Operations and rollout

For first installation use [getting started](getting-started.md). Commands here
use Bash on Linux. `sudo` marks administrator operations. Installed CLI commands
run as `cloudflare-cost-guard` from `/opt/cloudflare-cost-guard`; running them as
root can create incorrectly owned state. No command in this runbook authorizes a
Cloudflare write or reopens a remote endpoint.

Define this helper in your ordinary login-user Bash shell before CLI examples:

```sh
cfguard() {
  sudo -u cloudflare-cost-guard sh -c 'cd /opt/cloudflare-cost-guard && exec /usr/bin/python3 -B -m cfguard "$@"' cfguard "$@"
}
```

It enters the mode-0750 installed directory **as the service user**. Do not add
your login user to the service group or weaken directory permissions. Redefine
the helper when opening a new shell.
## Notifications and scheduling

Initial probe needs no notification receiver. Before scheduled operation, choose
an existing **owner-approved generic HTTPS JSON receiver**. It must accept the
application's incident payload, deduplicate `incident_id`, and return HTTP 2xx
only after durable acceptance. Delivery is at least once after an uncertain
network timeout; HTTP acceptance is not human receipt. There is no built-in
Slack/Discord message adapter or notification testing CLI.

A representative incident body is:

```json
{
  "incident_id": "synthetic-incident:1",
  "status": "unknown",
  "reason_code": "rated_unknown",
  "scope": "account",
  "resource_ref": "synthetic-reference",
  "metric": "rated_cost"
}
```

Scheduler/action event fields differ. Do not require every event to have every
field above. Alert payloads omit raw resource inventory. Treat receiver URLs as
secrets: HTTPS only, no URL user/password, fragment or redirect. Store the URL
in a root:cloudflare-cost-guard mode `0640` external file with protected parents,
using the same secure-file approach as read tokens. For an already securely
provisioned root-only input file:

```sh
sudo install -o root -g cloudflare-cost-guard -m 0640 \
  /root/secure-import/notification.url \
  /etc/cloudflare-cost-guard/secrets/notification.url
```

Add `notification` to `/root/cfguard-config.json` using the
[configuration fragment](configuration.md#files-notifications-and-enforcement-fields),
then reinstall through the update procedure below. Never edit installed
`/etc/cloudflare-cost-guard/config.json` directly: it is hash tracked.
`max_attempts` is the maximum due events attempted **per run**, not a lifetime
retry count. Failed events retry on future runs with bounded backoff. An unset
receiver leaves incidents pending; the run exits 5 while any remain pending.

Run one observe cycle after explicit receiver/notification approval and confirm
that the intended recipient actually received its incident. Previously queued
unknown/warning events can provide this verification; do not provoke a paid
charge or alter a live Worker as an alert test. Inspect pending count, the run's
`notification` object and collection health separately.

```sh
cfguard run --config /etc/cloudflare-cost-guard/config.json
printf 'run exit: %s\n' "$?"
cfguard status --config /etc/cloudflare-cost-guard/config.json
```

Have the owner approve an independently hosted check in an existing monitoring
system. It should detect absent runs, old `last_finished`, old
`last_collection_success`, unknown collection and growing pending notifications.
Choose thresholds with the five-minute cadence, 240-second maximum run and
660-second local heartbeat setting in mind. How the external system obtains
sanitized evidence is an operator integration; this repository installs no
external heartbeat or public health endpoint. Do not expose SQLite, secret files
or a raw private status mapping. A local timer cannot alert if its host is down.

Only after explicit install, receiver and scheduling decisions:

```sh
sudo systemctl enable --now cloudflare-cost-guard.timer
sudo systemctl status cloudflare-cost-guard.timer cloudflare-cost-guard.service --no-pager
sudo systemctl list-timers cloudflare-cost-guard.timer --all --no-pager
sudo journalctl -u cloudflare-cost-guard.service --since '15 minutes ago' --no-pager
```

The unit uses `OnBootSec=1min`, `OnUnitActiveSec=5min`, `AccuracySec=5s`.
It is a monotonic five-minute interval based on service activation, not wall-clock
`:00/:05` scheduling or five minutes after completion. There is no persistent
catch-up configuration for downtime. systemd serializes this oneshot service;
a separate process lock also rejects overlapping CLI runs. A long service run or
stopped host cannot be treated as continuous coverage.

Verify **two actual scheduled processes** (not just an enabled timer), actual
alert receipt and a **24-hour** source-availability/freshness record. Record each
account's denied/unknown endpoints and data timestamps. Do not claim zero spend,
full coverage or enforcement readiness from an enabled timer, HTTP 2xx, offline
tests or these observe gates. Nonzero incident exits can mark the service failed;
the timer continues scheduling. See [troubleshooting](troubleshooting.md).

## Configuration updates, upgrades and token rotation

Stop the timer **before every install/update**; installation does not disable an
already enabled timer and is not a transactional package manager. Wait for the
service to become inactive before replacing managed files; do not proceed while it is active. `stop` on the timer
does not stop a service already running. Check it first; if an administrative
stop is necessary, retain the resulting incomplete-run evidence.

```sh
sudo systemctl stop cloudflare-cost-guard.timer
sudo systemctl status cloudflare-cost-guard.service --no-pager
```

While stopped, back up state/config through your private backup policy. Keep a
root-controlled reviewed source checkout. Edit the protected **source** JSON
(`/root/cfguard-config.json` in the initial guide); for upgrades separately review
and pin the new code before copying it into a root-controlled source location.
Use a new source path rather than blindly overwriting a prior reviewed checkout.
Adding accounts/zones/resources requires exact ID and token-scope review.

```sh
sudoedit /root/cfguard-config.json
sudo sh -c 'umask 022; exec /usr/bin/python3 -B /root/cfguard-source/deploy/install.py install --config /root/cfguard-config.json'
sudo systemd-analyze verify /etc/systemd/system/cloudflare-cost-guard.service /etc/systemd/system/cloudflare-cost-guard.timer
cfguard validate --config /etc/cloudflare-cost-guard/config.json
cfguard probe --config /etc/cloudflare-cost-guard/config.json
```

The wrapper scopes `umask 022` to installer directory creation; it does not relax
explicit secret/config/state modes or repair pre-existing directory permissions.
That command uses the initial source path; substitute the reviewed root-controlled
checkout path for a code upgrade. Installation checks all recorded hashes first.
Editing installed config/code/units by hand causes future install and uninstall
to refuse. Preserve the changed files and marker, review the difference and
restore the exact recorded reviewed content before retrying. Do not delete the
marker, rewrite its hashes, remove foreign files or force-delete directories to
make installation pass. A partially failed install also requires review.
Restart the timer explicitly only after validating the new installed state:

```sh
sudo systemctl start cloudflare-cost-guard.timer
```

Rotate tokens while scheduling is stopped. Securely stage a replacement in the
same protected directory, with root:service-group `0640`, then atomically replace
the configured token file. Never print it. Secret files are external and not
hash-managed, so replacing one at the same path does not require editing config.
Run `probe`, record read-access results, and revoke the old token through the
provider's approved process. Changing the path requires config reinstall. No
executor token belongs in an observe installation.

## Latches and private identity mapping

Trips remain latched through healthy or unknown evidence. Investigate the cause
before explicitly rearming a resource. Replace placeholders locally with the
exact enrolled account/script; do not share real identities in support reports.

```sh
cfguard rearm --config /etc/cloudflare-cost-guard/config.json --account-id ACCOUNT_ID --resource-id SCRIPT_NAME
```

For an existing account billing latch, use `--scope account --account-id ACCOUNT_ID
--product billing` with the same command/config. Rearm changes local state only;
it never re-enables endpoints. Pending/partial/verified cutoff evidence prevents
rearm; preserve it and follow [enforcement recovery](enforcement.md).

Reports use stable hashed `resource_ref` values. `status --show-identities`
explicitly adds a private mapping to provider IDs. Use it only locally with the
same installed command/config and never attach its output to Git/issues/chat.
A successful `status` exit means local state was read, not that collection is healthy.

## State backup and restore

Stop the timer, wait for any service to finish and confirm no direct CLI run is
active. Use the SQLite backup API under the process lock as the service user.
The destination must be new; choose another private name if it already exists.
The following wrapper enters the installed directory as the service user:

```sh
sudo -u cloudflare-cost-guard sh -c 'cd /opt/cloudflare-cost-guard && exec /usr/bin/python3 -B -' <<'PY'
from pathlib import Path
from cfguard.state import RunLock, Store
state = Path('/var/lib/cloudflare-cost-guard')
with RunLock(state), Store(state) as store:
    store.backup(state / 'operator-backup.sqlite3')
PY
```

Copy that snapshot through your existing private external backup process; retain
its protected permissions and integrity evidence. It contains identities, latches
and private operational history. A local snapshot alone is not disaster recovery.
Monitor disk usage: the application has no disk quota, automatic incident purge
or backup retention policy. Do not copy an active SQLite file casually or delete
state to clear an unknown result.

Restore first into a **new empty**, service-owned mode `0700` directory. For
example, after confirming `/var/lib/cloudflare-cost-guard-restore` is absent:

```sh
sudo install -d -o cloudflare-cost-guard -g cloudflare-cost-guard -m 0700 /var/lib/cloudflare-cost-guard-restore
sudo -u cloudflare-cost-guard sh -c 'cd /opt/cloudflare-cost-guard && exec /usr/bin/python3 -B -' <<'PY'
from pathlib import Path
from cfguard.state import Store
Store.restore(Path('/var/lib/cloudflare-cost-guard/operator-backup.sqlite3'),
              Path('/var/lib/cloudflare-cost-guard-restore'))
PY
```

`Store.restore` validates SQLite integrity/current schema and refuses an occupied
target. It does not switch the running installation. With timer/service stopped,
an administrator must preserve the old state directory intact and activate the
restored directory at the configured `/var/lib/cloudflare-cost-guard` path using
a separately reviewed filesystem plan. The installed unit permits writes only
at its fixed state path. Check ownership and inspect local `status` before an
explicit restart; retain both original state and backup. Restore never reopens
provider endpoints. No database schema downgrade is implemented.

## Rollback and uninstall

Disable only this application's timer, stop its service and preserve configuration,
credentials and state. From a trusted root-controlled checkout:

```sh
sudo systemctl disable --now cloudflare-cost-guard.timer
sudo systemctl stop cloudflare-cost-guard.service
sudo sh -c 'umask 022; exec /usr/bin/python3 -B /root/cfguard-source/deploy/install.py uninstall'
```

Uninstall verifies ownership/hashes, removes only recorded package/config/unit
files, and retains state, secret files, service identity, marker and unrelated
backups. It makes no provider calls and never reopens endpoints. Operator changes
cause a refusal; review them instead of bypassing ownership protection. A retained
installation can be reinstalled through its marker. Revoke obsolete credentials
through the approved provider process when retiring it.

Code rollback means reinstalling a previous reviewed, root-controlled checkout
with a compatible state schema, while scheduling remains stopped. There is no
automatic remote rollback or downgrade migration. Do not turn monitoring back on
until local validation and approved read-only checks have been reviewed.
