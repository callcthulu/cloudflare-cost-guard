# Monitoring verification boundaries

The integrated monitoring implementation is reusable source and synthetic examples.
It does not establish that any installation is live. Earlier dated cutoff,
notification, publication and Linux lifecycle records remain historical evidence;
they do not verify this optional sampler/watcher on an operator's hosts.

## Offline verification

On 28 October 2026, Windows/Python 3.14.7 ran the integrated full suite:
344 tests, 341 passed and three platform skips, in 15.110 seconds. The added
monitoring suite contributes 92 tests; native integration additionally exercises a
real guard runner/schema-6 state file and confirms read-only positive-fee assessment.
Installer tests verify nested module delivery, destination/hash safety and no
automatic monitoring configuration, service activation or extra token reads.

Run from the repository root without provider credentials or external messaging:

```sh
python3 -B -m unittest discover -s tests -v
git diff --check
```

Configuration validation reads no credentials or providers, but Linux rejects
unprotected input files. In Bash, validate private copies of the synthetic examples:

```sh
MONITOR_CHECK=$(mktemp -d)
install -m 0600 config.monitoring-sample.example.json "$MONITOR_CHECK/sample.json"
install -m 0600 config.monitoring-watch.example.json "$MONITOR_CHECK/watch.json"
python3 -B -m cfguard.monitoring validate --config "$MONITOR_CHECK/sample.json"
python3 -B -m cfguard.monitoring validate --config "$MONITOR_CHECK/watch.json"
```

Use `python` on Windows and pass an absolute config path, for example with
`--config (Resolve-Path .\config.monitoring-sample.example.json).Path` in PowerShell.
POSIX permission verification remains a Linux gate. Record actual command results and platforms in the review
evidence for the change; do not infer results from this command list. Meaningful
regressions cover read-only guard state access, malformed/stale/missing evidence,
positive fees, complete/incomplete inventory, account binding, historical coverage
loss, reminders/recovery, retry/restart, destination changes and preview isolation.
Synthetic adapters and local SMTP fixtures do not prove provider visibility or
human receipt. Root Linux lifecycle testing belongs only in the disposable fixture
described in [Linux testing](linux-testing.md).

## Installation acceptance

Keep actual identities, source hashes, private configuration, token scopes, raw
observations and receipt evidence outside Git. For each separately authorized
installation verify:

1. Reviewed source/module paths, schema-6 guard state, protected ownership and
   permissions, unchanged guard configuration/state and read-only token scope.
2. Complete account-bound Worker/zone inventory compared to the provider view,
   explicitly reviewed baseline and expected account references. Record denied or
   unsupported sources as limitations/unknown, never zero or all-product coverage.
3. Sanitized export, forced bounded SSH read, strict known-host handling and no
   remote database, credentials or administration access for the watcher.
4. Stateless preview isolation and persistent history/reminder/recovery behavior
   with synthetic outage, stale source, positive-fee, drift and mail-failure cases.
5. Exact send scope, destination binding and owner-confirmed receipt. SMTP
   acceptance alone is insufficient; the real watch command may deliver due backlog.
6. Adapted Linux units and writable paths, two actual scheduled processes, a
   24-hour source-availability/freshness record, independent-host outage detection
   and a check for the watcher itself.

No live provider reads, installation, service activation, SSH provisioning,
notification receipt, 24-hour record or financial guarantee follows from offline
tests or publication. New resources can spend between polls. The complete setup,
send gate and rollback are in [independent monitoring](monitoring.md).
