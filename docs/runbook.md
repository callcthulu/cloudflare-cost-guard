# Operations and rollout

## Prepare an observe installation

Use Linux with Python >=3.11 and systemd. Review the code and evidence first. No
Cloudflare plan purchase, DNS change, Access change or new hosted Worker is needed.
Inspect existing host services, timers, disk/RAM and backups read-only before choosing
the installation window. The installer uses only dedicated fixed application paths.
Never replace an existing foreign installation to force a test through.

1. Put a reviewed checkout under a root-controlled path, such as `/root/cfguard-source`.
   The checkout and all installed source/config ancestors must be protected from
   unprivileged replacement. Do not run the installer from a shared writable folder.
2. Run `python3 deploy/install.py prepare` as root. This creates the nologin service
   identity, `/opt/cloudflare-cost-guard`, `/etc/cloudflare-cost-guard` and
   `/var/lib/cloudflare-cost-guard`, recording installation ownership.
3. Copy `config.example.json` to `/root/cfguard-config.json`, mode 0600. Replace
   synthetic IDs, read-token file paths, billing day/currency/budget and deliberately
   enrolled resources. Verify billing period metadata before setting its verification
   flag. Do not copy example rates into production as current prices.
4. Create read-token files through your existing secure secret provisioning method,
   owned root:cloudflare-cost-guard, mode 0640, with protected parent directories.
   Put them under `/etc/cloudflare-cost-guard/secrets/`. No token content in JSON.
   See [capabilities](capabilities.md) for endpoint permissions and unavailable data.
5. Run `python3 deploy/install.py install --config /root/cfguard-config.json` as root.
   It refuses enforce mode, executor credentials, foreign paths or changed managed
   files. It does not enable the timer. Repeating the same install is safe.
6. From `/opt/cloudflare-cost-guard`, run the following as the dedicated user:

```sh
python3 -B -m cfguard validate --config /etc/cloudflare-cost-guard/config.json
python3 -B -m cfguard probe --config /etc/cloudflare-cost-guard/config.json
```

Record actual API accessibility, source timestamps/coverage and timing per account.
Denied billing or incomplete inventory is not a zero balance or safe enforcement.
Coverage is limited to configured accounts/zones and provider-visible data.

## Notifications and scheduling

There is no assumed messaging service. Use an existing owner-approved HTTPS webhook
which accepts JSON and responds with HTTP 2xx only after durable acceptance. Store
its URL in a root:service-group 0640 external file and configure `notification` with
`url_file` and optional `max_attempts` (1–10 events per run). The generic payload
contains incident digest, status/reason and metric, not resource inventory. Receiver
must deduplicate `incident_id`; delivery is at least once after an uncertain timeout.
The operator confirms actual receipt separately; HTTP acceptance is not human receipt.

The local outbox retains failures, retries with bounded backoff on later runs and
never marks silence as delivery. An unset destination leaves alerts pending. Monitor
pending count and collection health separately from successful process invocation.

After explicit live-install and notification approval:

```sh
systemctl enable --now cloudflare-cost-guard.timer
systemctl status cloudflare-cost-guard.timer cloudflare-cost-guard.service
journalctl -u cloudflare-cost-guard.service --since '15 minutes ago' --no-pager
cd /opt/cloudflare-cost-guard
sudo -u cloudflare-cost-guard python3 -B -m cfguard status --config /etc/cloudflare-cost-guard/config.json
```

Verify two scheduled runs and an approved alert receipt. Record a 24-hour source
availability window before judging latency/freshness. Configure an independently
hosted health check through an existing approved tool; this utility cannot notify
while its own host is down. `last_attempt`, `last_finished` and
`last_collection_success` distinguish scheduler progress from collection health.
The timer runs every five minutes, service timeout 240 seconds, no overlap.

## Rotation, rearm and state recovery

Rotate a read token by atomically replacing its file with protected ownership/mode;
run `probe`, then revoke the old token through your usual provider process. Do not
give an observe deployment an executor token. Adding accounts/domains means editing
the root-owned configuration and reinstalling through the same reviewed procedure.

Trips remain latched through healthy or unknown data. Explicit local rearm:

```sh
python3 -B -m cfguard rearm --config /etc/cloudflare-cost-guard/config.json --account-id ACCOUNT_ID --resource-id SCRIPT_NAME
```

This never changes provider state. Pending/partial or verified cutoff evidence
cannot be erased by rearm. Reopening endpoints requires a separate manual decision.

Reports and alerts identify resources by stable `resource_ref` hashes. For a local
private mapping, use `status --show-identities` with the same config. That explicitly
includes provider resource IDs: do not copy its output into shared evidence, Git or
support reports. Account billing latches can be rearmed with `rearm --scope account
--account-id ACCOUNT_ID --product billing` and the config argument.

To back up state, stop the timer, wait for the service to finish, and run the SQLite
backup API as the service identity from the installed directory:

```python
from pathlib import Path
from cfguard.state import RunLock, Store
root = Path('/var/lib/cloudflare-cost-guard')
with RunLock(root), Store(root) as store:
    store.backup(root / 'operator-backup.sqlite3')  # Must not already exist.
```

Keep a private external copy under your existing backup policy. To restore, stop
the timer/service, retain the old state directory intact, prepare a new empty mode
0700 service-owned directory and use `Store.restore(backup_path, new_directory)`.
It validates SQLite integrity/schema and refuses overwrites. Inspect `status` before
explicitly restarting. Never remove a latch to fix an unknown collection status.

## Rollback and uninstall

Stop/disable only `cloudflare-cost-guard.timer`, then stop its service. Preserve
config, credentials and state. From a trusted source checkout, run
`python3 deploy/install.py uninstall` as root. It verifies the ownership manifest,
removes only its recorded executable/config/unit files, and preserves state, secret
files, service identity, ownership marker and unrelated backups. It makes no
provider calls and never reopens endpoints. Operator-owned modifications cause a
refusal; review them manually rather than force-delete them.

Rollback of code means reinstalling a previously reviewed checkout with compatible
state schema. There is no schema downgrade or automatic remote-resource rollback.
Revoke credentials manually if retiring the utility. Production host capacity and
resource limits still need verification; disposable Linux measurements are not
capacity evidence for another host.
