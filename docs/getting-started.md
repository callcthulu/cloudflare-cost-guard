# Getting started: Linux observe mode

This guide gets one reviewed account to a first read-only report. It does not
buy a Cloudflare plan, deploy a Worker, change DNS or enable enforcement.
Use an existing host only with its owner's approval. Initial installation is observe
only. For optional destructive Worker cutoff, follow the separate
[budget and arming guide](automatic-cutoff.md) after observing and reviewing the target.

## 1. Check the host and prerequisites

Commands below use **Bash on Linux**. Blocks beginning with `sudo` require an
administrator; other commands run as your ordinary login user. Do not run the
whole guide as the service user. The installer creates that identity later.

Supported deployment: Linux with booted systemd, `/usr/bin/python3` 3.11+ including
its standard-library SQLite module, an OS CA certificate store, `git`, `tar`, `sudo`,
`groupadd`, `useradd` and `runuser`. Runtime has **no pip dependencies** and no
virtual environment/package installation step. Tested deployment evidence is
Ubuntu 24.04 / Python 3.12 / systemd 255; Windows Python 3.14 is offline test
coverage, not service support. Offline CI covers additional Python versions; that
is separate from service lifecycle evidence on a real Linux fixture.

Run these read-only checks as your login user:

```sh
/usr/bin/python3 --version
/usr/bin/python3 -c 'import sqlite3, ssl; print("SQLite", sqlite3.sqlite_version); print(ssl.get_default_verify_paths())'
ps -p 1 -o comm=
systemctl --version
command -v git tar sudo groupadd useradd runuser
systemctl list-timers --all --no-pager
df -h / /var/lib
free -h
```

PID 1 must be systemd; a non-systemd container or ordinary WSL session is
insufficient. Ensure time synchronization and outbound DNS/HTTPS to
`api.cloudflare.com` work under the host's policy. The application bypasses
proxy environment variables and refuses redirects. Later notifications also
need direct HTTPS to the approved receiver. Never disable certificate checking.

On a new Ubuntu host, missing prerequisite packages can be installed by its
administrator **after approving host changes**:

```sh
sudo apt-get update
sudo apt-get install --no-install-recommends python3 ca-certificates git tar sudo passwd util-linux
```

This does not upgrade an old Ubuntu Python to the required version or convert
an incompatible host. Choose a supported host instead of modifying production
Python in place. Do not apply package commands blindly on a shared server.

The service unit limits memory to 128 MiB, CPU quota to 25% and runtime to
240 seconds. These are process limits, not provider spending limits. There is
**no application disk quota or retention job**: size state, journal and backups
for your actual account/event volume and monitor free space. Disposable fixture
measurements are not a production capacity guarantee.

## 2. Obtain and review the exact source

As the login user, clone the source over HTTPS. A public clone needs no GitHub
credential. Do not embed tokens in clone URLs, commands or shell history.

```sh
git clone https://github.com/callcthulu/cloudflare-cost-guard.git "$HOME/cloudflare-cost-guard-review"
cd "$HOME/cloudflare-cost-guard-review"
DELIVERY_COMMIT=ba00e2a1d6790654219a3d141015de2b2580daf8
test "${#DELIVERY_COMMIT}" -eq 40 || exit 1
git fetch origin "$DELIVERY_COMMIT" || exit 1
git switch --detach "$DELIVERY_COMMIT" || exit 1
test "$(git rev-parse HEAD)" = "$DELIVERY_COMMIT" || exit 1
git rev-parse HEAD
/usr/bin/python3 -B -m unittest discover -s tests -v
```

This full SHA pins the independently reviewed source including multiple budget
warnings and optional automatic Worker cutoff. Initial installation uses observe
mode; arming is a separate step in the [cutoff guide](automatic-cutoff.md).
See [budget-alert evidence](budget-alerts-evidence.md)
for offline, disposable Linux and live-verification boundaries. Later documentation
commits may update this guide without changing the pinned runtime.
Retain `DELIVERY_COMMIT` for the export below.
No separate evidence package or release tag is required. Review any later revision
before substituting its full SHA. If this commit cannot be fetched, stop and check
repository history; do not silently fall back to a moving branch.

Review at least `cfguard/`, `deploy/install.py`, the two systemd units, the
[capability matrix](capabilities.md), [threat model](threat-model.md) and
[budget-alert evidence](budget-alerts-evidence.md). Tests are offline and use no provider credentials.

## 3. Move approved source under administrator control

Only after source review, export its pinned snapshot into a **new**, root-controlled location.
`/root/cfguard-source` must not already exist or be a symlink. Check first:

```sh
sudo ls -ld /root /root/cfguard-source
```

An absent `/root/cfguard-source` is expected; `/root` must be root-owned and
protected. If a source directory already exists, review it or choose a separate
root-controlled path; do not overwrite it blindly.

Export only the pinned tracked source, excluding working-tree changes, local
artifacts and Git credentials/metadata. From your login-user Bash shell:

```sh
set -o pipefail
sudo mkdir -m 0750 /root/cfguard-source &&
  git -C "$HOME/cloudflare-cost-guard-review" archive --format=tar "$DELIVERY_COMMIT" |
  sudo tar -x --no-same-owner --no-same-permissions -C /root/cfguard-source
```

Stop if any command fails; inspect the partial directory rather than retrying
over it. After successful extraction, prepare the installation:

```sh
sudo sh -c 'umask 022; exec /usr/bin/python3 -B /root/cfguard-source/deploy/install.py prepare'
```

The wrapper sets `umask 022` for the installer process only: newly created package
directories must be traversable by the service. Secret/config file modes are still
set explicitly, and state stays 0700. It does not change your login shell's umask.
This is a fresh-install prerequisite, not a repair for directories already created
with different permissions. Preserve a failed installation and review it rather
than retrying blindly or applying recursive chmod.

The root source is a pinned snapshot, not a Git working copy. For a later version,
review and export its exact commit into a new protected directory.

All source files and ancestors must be root-owned, non-replaceable and free of
symlinks. Do not run the installer from a user-writable checkout. It verifies
source trust before importing application code as root. `prepare` creates only
the dedicated nologin user/group and protected application directories, records
ownership and refuses foreign installations. A refusal requires investigation,
not deleting the marker, service account or existing directories.

| Path | Purpose / owner |
| --- | --- |
| `/opt/cloudflare-cost-guard` | Installed Python package; root-controlled. |
| `/etc/cloudflare-cost-guard` | Config, installation ownership marker, external secret directory; root-controlled. |
| `/var/lib/cloudflare-cost-guard` | Private SQLite state, incidents, outbox, action evidence and lock; service-owned mode 0700. |
| `/etc/systemd/system/cloudflare-cost-guard.{service,timer}` | Dedicated managed units; root-controlled. |

## 4. Configure accounts and provision read tokens

For each account, create one custom **read-only** token restricted to the exact
account and approved zones wherever Cloudflare permits. See the current
[read-token permission recipe](capabilities.md#read-token-setup): Account Analytics
Read for analytics, Billing Read for subscription inventory. Billable Usage Alpha
access/permissions remain an account-specific probe gate. A denial is unknown;
do not broaden to writes or use a Global API key to silence it. Install no executor
token.

Create a protected source config, then edit it locally as administrator:

```sh
sudo install -o root -g root -m 0600 /root/cfguard-source/config.example.json /root/cfguard-config.json
sudoedit /root/cfguard-config.json
```

Use the [complete minimal observe configuration](configuration.md) as the starting
point. Replace all synthetic IDs. For the shortest first setup, set `resources`
to `[]`, use no zones unless deliberately enrolling them, leave `prices: []` and
`billing_period_verified: false`, and omit `notification`. Use verified expected
subscription **plan IDs**; an empty list marks every returned plan unexpected.
Set the token path to `/etc/cloudflare-cost-guard/secrets/example-account-read.token`
if using the provisioning command below. A budget of zero is an alert policy,
not a hard cap. Each additional account needs its own token file and unique ID/key.

Provision the token through your existing secure channel. For example, if a
root-only token file has already been securely placed at
`/root/secure-import/example-account-read.token`, use:

```sh
sudo install -o root -g cloudflare-cost-guard -m 0640 \
  /root/secure-import/example-account-read.token \
  /etc/cloudflare-cost-guard/secrets/example-account-read.token
```

Alternatively, **in an interactive terminal**, this Bash builtin prompt reads the
token without echo or putting its value in argv/history. Do not use a recorded
terminal, shell tracing, chat-driven token entry or automation that captures input.
The command contains a variable reference, not a secret string:

```sh
sudo bash -c 'set +x; umask 077; IFS= read -r -s -p "Read-only token: " cfguard_secret; printf "\n" >&2; test -n "$cfguard_secret" || exit 1; printf "%s\n" "$cfguard_secret" > /etc/cloudflare-cost-guard/secrets/example-account-read.token; unset cfguard_secret; chown root:cloudflare-cost-guard /etc/cloudflare-cost-guard/secrets/example-account-read.token; chmod 0640 /etc/cloudflare-cost-guard/secrets/example-account-read.token'
```

Use **one** provisioning method, and the exact path in your config. Do not use
`echo TOKEN`, environment variables holding tokens, inline JSON secrets or command
substitution to pass credentials. Retire any temporary secret copy through your
established secret-handling procedure. Never print token contents to verify them.

## 5. Install, validate and probe

The installed directory is root:service-group mode 0750; your login user cannot
normally enter it. Define this helper in your **login-user Bash shell**. It changes
directory inside the service identity and passes arguments without interpolation:

```sh
cfguard() {
  sudo -u cloudflare-cost-guard sh -c 'cd /opt/cloudflare-cost-guard && exec /usr/bin/python3 -B -m cfguard "$@"' cfguard "$@"
}
```

The helper lasts only for this shell; redefine it in a new session. No group
membership changes or relaxed directory permissions are needed.

For the initial installation there is no existing application timer. The installer
never enables a timer; for updates, stop it first as described in the runbook.

```sh
sudo sh -c 'umask 022; exec /usr/bin/python3 -B /root/cfguard-source/deploy/install.py install --config /root/cfguard-config.json'
sudo systemd-analyze verify /etc/systemd/system/cloudflare-cost-guard.service /etc/systemd/system/cloudflare-cost-guard.timer
cfguard validate --config /etc/cloudflare-cost-guard/config.json
cfguard probe --config /etc/cloudflare-cost-guard/config.json
printf 'probe exit: %s\n' "$?"
```

`validate` should report `valid: true`; it does not test token content or provider
access. `probe` makes real read-only provider requests, initializes local state
if needed, and sends no notifications. Expect unknowns: monthly estimates, CPU
and full rated totals are unavailable; Workers data is approximate or unknown.
Inspect each account's `coverage` and decision `reason_code`, not only the exit
code. Record actual endpoint availability and timestamps without raw provider
payloads or identities. See [troubleshooting](troubleshooting.md).

Using the same helper, perform one approved observe run and inspect
local status:

```sh
cfguard run --config /etc/cloudflare-cost-guard/config.json
printf 'run exit: %s\n' "$?"
cfguard status --config /etc/cloudflare-cost-guard/config.json
```

With no notification receiver, unknown/warning/tripped decisions enter the outbox
and **exit 5 with pending notifications is expected**. It is not proof that alerts
were delivered, nor that collection is healthy. `status` itself exits 0 when it
successfully reads local state; it is not a provider health check.

## 6. Complete operational acceptance before scheduling

Follow [notifications and scheduling](runbook.md#notifications-and-scheduling) to
approve a generic HTTPS receiver, securely provision its URL, reinstall the
updated source config and confirm actual receipt. Native Slack/Discord webhook
compatibility is not implemented. Set up an independently hosted heartbeat using
your existing approved monitoring tool; this utility cannot alert while its host
is down. Do not enable a timer merely because validation passed.

After those owner decisions, enable observe scheduling using the runbook. Verify
two actual scheduled processes and retain a 24-hour source-availability record.
These are live checks, separate from offline tests. No executor credential belongs
in this initial observe installation. Automatic Worker cutoff has a separate
[scope, approval and arming procedure](automatic-cutoff.md); source tests do not
establish a live canary or a guaranteed maximum bill.
