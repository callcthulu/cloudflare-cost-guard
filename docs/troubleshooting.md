# Troubleshooting

Start with the JSON report, not a single exit code. Never paste tokens, webhook
URLs, actual config, raw provider payloads, database files or `--show-identities`
output into support/Git/chat. Use [support](../SUPPORT.md) for sanitized reports.
Commands below assume the installation from [getting started](getting-started.md).

Define this helper in your ordinary login-user Bash shell before CLI examples:

```sh
cfguard() {
  sudo -u cloudflare-cost-guard sh -c 'cd /opt/cloudflare-cost-guard && exec /usr/bin/python3 -B -m cfguard "$@"' cfguard "$@"
}
```

It enters the mode-0750 installed directory **as the service user**. Do not add
your login user to the service group or weaken directory permissions. Redefine
the helper when opening a new shell.
## Exit codes and apparently failed services

| Exit | Meaning | First checks |
| --- | --- | --- |
| 0 | Command completed; for a run, no incident/unknown/failure condition. | `validate` and `status` success say nothing about live source health. |
| 2 | Invalid config or unsafe config ownership. Installer also uses 2 for refused deployment. | Strict JSON schema, root ownership, protected parents, installer manifest. |
| 3 | Unknown source/quality, deadline, overlapping run or local runtime failure. | JSON error/coverage/reason codes, lock holder, state permissions, capacity. |
| 4 | Warning or tripped policy condition. | Each account's decisions; approximate analytics warns even below its limit. |
| 5 | Pending/failed notifications or blocked/failed action. | Notification pending/failed fields plus independent collection/action results. |

For `run`, precedence is **5 > 4 > 3 > 0**. Multiple conditions coexist: exit 5
can accompany unknown collection and a subscription incident. `collection:
"complete"` describes this policy result, not complete product/billing coverage;
read every source's `coverage`. `collection: "unknown"` may be expected because
complete billing data is unavailable, even when subscriptions were read.

systemd treats nonzero exits as service failures. A timer can keep scheduling
while its latest service is failed due to an incident or undelivered alert. Do
not change `SuccessExitStatus` to hide it; confirm subsequent scheduled processes
and investigate JSON health separately.

```sh
sudo systemctl status cloudflare-cost-guard.timer cloudflare-cost-guard.service --no-pager
sudo systemctl list-timers cloudflare-cost-guard.timer --all --no-pager
sudo journalctl -u cloudflare-cost-guard.service --since '30 minutes ago' --no-pager
cfguard status --config /etc/cloudflare-cost-guard/config.json
```

## Configuration or install is refused

- Use JSON, not JSON with comments, trailing commas or duplicate keys. Amounts
  and thresholds are decimal strings; IDs are exact, account/zone IDs 32 hex.
  Check [configuration](configuration.md). `validate` does not read token contents.
- On Linux configuration and source must be root-owned and protected from
  unprivileged replacement. Check file **and parent** ownership/modes without
  printing contents. Do not run the root installer from your login-user checkout.
- Use the documented installer wrapper with scoped `umask 022` for fresh directory
  creation. An existing installation created with restrictive permissions is not
  automatically repaired by changing umask later; preserve it for owner-reviewed
  diagnosis. Do not add your login user to the secret-reading service group.
- `prepare` refuses an unowned existing application directory/user/group/unit,
  unit drop-ins or foreign enabled-unit links. Inspect conflicts; never remove
  another service or symlink just to proceed.
- Installed code, config and units are hash tracked. Editing installed config
  directly is drift. Preserve the files and marker, review/restore recorded
  content, and use the protected source config plus stopped-timer reinstall
  procedure in the [runbook](runbook.md#configuration-updates-upgrades-and-token-rotation).
  Do not rewrite hashes, delete markers or force-delete the installation.
- Initial install requires observe mode, fixed state directory and no executor
  credential reference. A referenced secret must already exist as a readable
  regular root:cloudflare-cost-guard file with mode 0640; no symlinks.

For local file metadata, not contents:

```sh
sudo stat -c '%U:%G %a %n' /etc/cloudflare-cost-guard /etc/cloudflare-cost-guard/config.json /etc/cloudflare-cost-guard/secrets /var/lib/cloudflare-cost-guard
```

Inspect the metadata for each exact configured secret path similarly; do not
attach real path/identity lists publicly. Avoid blanket `chmod -R` repairs on an
installed directory: code/config/secrets and writable state have different owners
and modes. See [getting started](getting-started.md#3-move-approved-source-under-administrator-control).

## Imports, permissions, locks and deadlines

`No module named cfguard`: use `/usr/bin/python3 -B -m cfguard` from
`/opt/cloudflare-cost-guard`; no pip installation is required. A historical
bootstrap checkout is not the implementation; current `main` is
integrated, but deployment still uses the reviewed pin in the guide.
A different working directory is not fixed by giving the service root access.

`runtime_failure` after running as root: state must be owned by the service user,
mode 0700, with no symlink components. Stop scheduling, inspect ownership and
preserve the database before a reviewed repair. SQLite/disk errors can have the
same sanitized result; check capacity, permissions and supported schema.

`overlapping_run`: another process holds the lock. systemd serializes the unit,
but a direct CLI command can overlap. Wait for the holder to finish; do not delete
`run.lock`, kill an arbitrary process or launch retry loops. A stale filename
alone is harmless because the lock is held by the process, not file existence.

`run_deadline_exceeded` or systemd timeout: request bounds and the 240-second unit
deadline were exceeded. Inspect account volume, transport latency and host load.
Do not disable timeouts or raise CPU/memory limits without target-host review.
Windows offline tests do not exercise the Linux alarm/systemd deadline.

## Unknown sources, warnings and zero-spend assumptions

| Result | Interpretation and next step |
| --- | --- |
| `billing_period_unverified`, `price_unknown`, `period_coverage_unknown` | No supported complete monthly estimate. Verify billing metadata/prices if appropriate, but rolling five-minute metrics still cannot produce a monthly total. |
| `rated_unknown`, rated freshness unknown | Billable Usage is Alpha and lacks a proven update heartbeat/complete ledger. Access denial, empty rows and parsed rows are not a complete zero balance. |
| `billing_account_coverage: unavailable`, `billing_info: parsed` | V1 info explicitly returned `covered:false`. This is unavailable account coverage, not a permission error or zero bill. Keep the total unknown; do not broaden tokens or buy a plan to make it healthy. |
| `billing_info: unknown:<code>` or `billing_period: unverified` | Missing/invalid metadata, absent/ambiguous active anchors, stale cache or unverified configuration. Inspect the sanitized code and current read-only evidence after authorization. Subscription inventory and positive rated-line alerts remain separate. |
| `positive_rated_line_total_unknown` | A positive in-period row was seen; alert evidence, not a reconciled full bill. Review provider records independently. |
| `approximate` Workers decision | Adaptive sampling status is unknown. Policy warns even below threshold; no cutoff is authorized. |
| Missing/empty Workers partitions | Unknown rather than proven zero traffic. Confirm exact account/script name and source availability; no synthetic traffic is required to force success. |
| CPU or other product unsupported | No current fast adapter. Raising permissions or adding a threshold does not implement one. |
| `forbidden_subscription` | Returned `rate_plan.id` is not expected. Verify it against provider records; free plans can also be unexpected. Do not replace with subscription record IDs. |
| HTTP/API denied, incomplete inventory, collection failed | Verify exact account token scope, expiry, configured zones and CA/network/time. Keep evidence unknown; never add writes or a Global API key merely to pass. |

Actual token errors are sanitized. Never print credentials or enable raw HTTP
logging. The application ignores environment proxies, refuses redirects and uses
OS CA certificates. A proxy-only network or missing CA store needs an approved
host/network fix, not disabled TLS verification.

## Notifications and latches

No receiver configured means incidents stay pending and runs exit 5. This is
expected during first setup. `delivered` means HTTP 2xx accepted the generic JSON
body; it does not prove human receipt or Slack/Discord format compatibility.
The receiver must deduplicate `incident_id`. Check URL-file protection, direct
HTTPS reachability, certificates, receiver contract and pending retry timing.
No notification-test command exists; use an approved real queued incident and
confirm actual receipt. `max_attempts` bounds due events per run, not lifetime
retries. A future-due event still counts as pending.

A trip remains latched after healthier data or config changes. Verify the cause,
then explicitly rearm the exact enrolled local resource/account as described in
the [runbook](runbook.md#latches-and-private-identity-mapping). Do not delete the
SQLite database to clear it. Rearm never restores provider endpoints; unresolved
or completed cutoff evidence cannot be erased that way. Real enforcement remains
blocked in the current release.

If `last_attempt` advances but `last_finished` does not, investigate interrupted
runs. If `last_finished` advances while `last_collection_success` stays old,
collection remains unknown. `status` returning 0 proves only local state access.
A stopped host requires the external monitor described in the runbook.
