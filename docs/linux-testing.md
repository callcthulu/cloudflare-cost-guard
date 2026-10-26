# Linux installation and disposable testing

Python 3.11+ and booted systemd are required. No pip dependencies. Review code and
configuration before running the root installer. The initial installer accepts
only `observe` mode without executor credential references.

## Administrator installation

Use the canonical [getting-started guide](getting-started.md) for source review,
administrator-owned source, token provisioning, installation and first reports.
Use the [runbook](runbook.md) for updates, notifications and explicit scheduling.
These instructions also explain why ordinary users must run installed commands
with both working directory and interpreter inside the dedicated service identity.

Installed unit syntax can be checked without starting the timer:

```sh
sudo systemd-analyze verify /etc/systemd/system/cloudflare-cost-guard.service /etc/systemd/system/cloudflare-cost-guard.timer
```

The source JSON must reference the destination token path and
`state_dir=/var/lib/cloudflare-cost-guard`. Notification URLs, if configured,
also live in separately provisioned root:service-group files with mode 0640.
Source JSON must be root-owned and protected against replacement. Each account
may reference its own credential file. The installer checks the dedicated user
can read all referenced files without printing them. Do not provision executor
credentials for observe mode.

`prepare` creates the locked service identity and marked application directories;
repeat calls preserve them. `install` copies only the Python package, config and
two units into root-owned paths. It never enables or starts the timer. Repeat
installation verifies the recorded file hashes first and rejects changed files,
foreign targets, symlinks, unsafe permissions and identity drift. It does not
edit or replace unrelated services/backups. Deliberate local changes require
administrator review; restore reviewed tracked files before rerunning.

The service runs as `cloudflare-cost-guard`, uses private state mode 0700, a
240-second systemd start deadline, a 128 MiB memory limit and 25% CPU quota.
The timer requests a run every five minutes. systemd serializes this oneshot
unit; the application additionally rejects simultaneous direct CLI invocations.
Collection incidents and undelivered alerts retain nonzero exit status and may
show a failed service; the timer keeps scheduling subsequent checks.

For removal, follow the [runbook's rollback/uninstall procedure](runbook.md#rollback-and-uninstall)
from the reviewed root-controlled source snapshot.

This stops/disables the exact application timer, stops its service, verifies
ownership/hashes, and removes tracked code/config/unit files. State, latches,
secrets, unrelated backups, the service identity and ownership marker remain.
No provider request occurs and endpoints are never reenabled. Repeating removal
is safe. Manually inspect and archive retained data before any separate purge.

## Offline disposable Linux check

Never execute this lifecycle harness on a production or shared server. It creates
the exact application paths and systemd drop-ins. Use a fresh expendable VM or
WSL2 distribution with systemd PID 1. No real credentials are needed or allowed.

```sh
sudo sh -c 'umask 022; exec env CFGUARD_DISPOSABLE=1 python3 tests/linux_lifecycle.py'
python3 -m unittest discover -s tests -v
```

The harness copies source into `/root/cfguard-lifecycle-source` and replaces the
collector only in that staging copy with synthetic observations and a fake token.
The real installed CLI, policy, SQLite state, process lock and systemd units run.
A fixture-only private network namespace prevents external provider access.
Temporary timer drop-ins request another run two seconds after completion.

Checks: unsafe token mode refused; install twice; timer remains disabled until
explicit start; installed-unit verification; two actual scheduled processes;
specific overlapping-run refusal; a trip surviving a healthy second sample;
unrelated-user secret denial; journal excludes the fake token/tracebacks;
uninstall retains the identical SQLite file, token and unrelated backup.
The harness leaves retained files and fixture drop-ins for inspection. Destroy
the entire disposable fixture after recording results; do not reuse it as a
production installation.

## Measured local evidence (2026-10-26)

Ubuntu 24.04 / Python 3.12.3 / systemd 255 in a disposable WSL2 distribution:
deployment tests passed, installed unit verification emitted no diagnostics,
and the complete lifecycle above passed with two scheduled runs. Sampled process
RSS/high-water mark was 26,412 kB; systemd recorded about 0.154 CPU seconds for
the second run. Retained cgroup `MemoryPeak` was 15,011,840 bytes on the final fresh
run. These are tiny
offline fixture measurements, not production capacity or live API validation;
confirm limits against the actual target host's memory and account/resource count.
