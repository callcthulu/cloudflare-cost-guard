# Enforcement paths

For automatic USD-budget cutoff, use [automatic cutoff](automatic-cutoff.md).
It supports explicitly armed stateless HTTP Workers with a version 2 approval,
a separate writer token and either non-forced script deletion or workers.dev/
preview-only disablement. Initial installation remains observe-only. Source tests
exercise the real HTTP adapter with injected responses; no live canary is claimed.

## Legacy raw-threshold path

The older version 1 endpoint-containment path remains separate. It only disables
workers.dev/preview flags and requires exact, complete, unsampled raw usage,
complete endpoint inventory, a pinned inventory baseline and authoritative cutoff
probes. The current real adapter cannot establish these gates. It cannot execute
a raw-threshold deletion or treat an approximate monetary estimate as exact usage.
New budget-cutoff users should use the version 2 guide instead.

Legacy approval includes the exact resource/action, raw metric/limit/unit/window,
endpoint baseline, explicit excluded resources, approved workers.dev URLs and a
future UTC expiry. The external root-owned file is byte-digest pinned and rejects
unknown/duplicate fields. Keep existing manifests and action evidence intact;
version 1 and version 2 files are not interchangeable.

## Shared rules

Observe mode and probe/preview make no provider writes. An action persists intent
before its one write attempt, then reads back provider state. Timeouts are
ambiguous; later runs reconcile rather than retrying writes. No automatic recovery,
endpoint re-enable, script restoration or new deployment is performed.

Manual rearm is local. For budget attempts it archives known terminal results and
preserves the ledger; pending/uncertain attempts remain blocked. Legacy partial or
verified-public-cutoff evidence retains its existing rearm restriction. See
[the runbook](runbook.md#latches-and-private-identity-mapping).
