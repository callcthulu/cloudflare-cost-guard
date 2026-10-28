# Configuration

Use strict JSON in an administrator-controlled file. Keep actual configuration
outside Git. This is a **complete synthetic observe example** for one account;
replace its account ID, billing day, budget, expected plan IDs and token path
after review. It enrolls no Worker and no notification target.

```json
{
  "mode": "observe",
  "state_dir": "/var/lib/cloudflare-cost-guard",
  "run_timeout_seconds": 240,
  "heartbeat_max_age_seconds": 660,
  "accounts": [
    {
      "key": "example-account",
      "account_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "read_token_file": "/etc/cloudflare-cost-guard/secrets/example-account-read.token",
      "billing_day": 1,
      "billing_period_verified": false,
      "budget": "0.00",
      "currency": "USD",
      "expected_subscriptions": [],
      "zones": [],
      "prices": [],
      "max_data_age_seconds": 900
    }
  ],
  "resources": []
}
```

`resources: []` is valid for account/subscription monitoring without per-Worker
thresholds. The collector still queries account Workers analytics and rated usage;
there is no switch to disable those sources. Empty `expected_subscriptions` means
every returned plan is unexpected, including a free plan; fill it with verified
expected `rate_plan.id` values. `budget: "0.00"` is a local policy threshold,
not a provider billing restriction.

## Schema and defaults

Unknown fields, duplicate JSON keys/identities, cross-account zone references,
invalid values and relative secret paths are rejected. Decimal amounts, allowances
and thresholds are **strings**, not JSON numbers. No currency conversion occurs.
Account and zone IDs have exactly 32 hexadecimal characters. `key` and `name` are
local labels; neither selects a provider resource.

| Field | Meaning and permitted values |
| --- | --- |
| `mode` | `observe` (default) or `enforce`; initial installer accepts observe only. |
| `accounts` | Required nonempty list. Each account ID and key must be unique. Use a separate read token limited to each account. |
| `resources` | Optional list, default `[]`; explicit per-resource enrollment only. |
| `state_dir` | Absolute path, default `/var/lib/cloudflare-cost-guard`; installer requires this exact path. |
| `run_timeout_seconds` | Integer 1–299, default 240. systemd still imposes 240 seconds; keep this at or below 240. |
| `heartbeat_max_age_seconds` | Integer 301–86400, default 660. Detects gaps when a later run occurs; cannot detect a stopped host alone. |
| `notification` | Omitted/null initially. Otherwise external HTTPS `url_file` and optional `max_attempts` 1–10, default 3. |

Each account requires `key`, `account_id`, `read_token_file`, `billing_day`,
`budget` and `currency`. Optional account fields:

| Field | Meaning |
| --- | --- |
| `zones` | Explicit 32-hex zone IDs, default `[]`. A zone cannot belong to two configured accounts. No automatic zone discovery/enrollment. |
| `expected_subscriptions` | Expected **rate plan IDs** from `rate_plan.id`, not subscription record IDs; default `[]`. Applies to account and configured-zone inventory. |
| `billing_period_verified` | Boolean, default false; operator assertion after independently checking the billing anchor. The collector also requires covered V1 info and consistent active anchors matching `billing_day`; missing metadata leaves the period unverified. Does not prove source completeness. |
| `prices` | Default `[]`; verified pricing metadata for estimates, detailed below. |
| `max_data_age_seconds` | Integer 1–86400, default 900. Uses data timestamps, not just successful fetch time. |

`billing_day` is an integer 1–31 interpreted in UTC. Missing days clamp to month
end, then return to the original anchor: day 31 gives February 28 to March 31 in
a non-leap year. Billing intervals are half-open; a row ending at the next period
start belongs to the previous period. Currencies are uppercase three-letter codes;
the subscription adapter currently requires provider USD rows. Other configured
currencies cannot be assumed to yield a usable subscription commitment.

## Enroll one Worker

Add this object to `resources` after replacing the synthetic account and exact
deployed script/service name. Keep the matching account enrolled above.

```json
{
  "account_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "product": "workers",
  "resource_id": "example-worker",
  "name": "Example Worker",
  "zones": [],
  "hostnames": ["example-worker.example.invalid"],
  "thresholds": [
    {"metric": "workers.requests", "limit": "100000", "warning": "80000", "unit": "requests"}
  ]
}
```

`resource_id` is the exact name used in
`/accounts/{account_id}/workers/scripts/{script_name}/...`: not a hostname,
route, display name or deployment-version ID. Provider adapter identifiers accept
1–128 letters, digits, underscores or hyphens. Names are case-sensitive. Repeating
`(account_id, product, resource_id)` is an error. A resource's `zones` must be a
subset of its account's zones. `hostnames` documents associations; it does not
configure DNS, routing or remote resources.

Thresholds use `metric`, decimal-string `limit`, `unit`, and optional decimal-string
`warning` no higher than the limit. Current request metrics are
`workers.requests` / `requests` for the **rolling five completed minutes**, not
a monthly allowance. The real adapter marks them approximate and policy emits
a warning even below the threshold. The legacy raw-threshold action cannot use
approximate data. A separately approved budget signal can explicitly accept it.
Missing activity/empty partitions can yield unknown rather than zero. Configuring
`workers.cpu_ms` does not add CPU collection: it remains unsupported.

## Estimates and rated charges

A price requires `metric`, `unit`, `currency`, decimal strings `amount`,
`per_quantity` (>0) and `allowance`, plus provenance `source` and ISO date `as_of`.
Use verified current contract data, never copied fixture/example rates. An
allowance applies once per complete account/product billing period. Only a complete
account billing-period series can produce an estimate; the current five-minute
Workers adapter cannot. Adding prices or verifying the billing anchor does not
remove this limitation.

Estimates, rated usage and subscription commitments stay separate. Current rated
rows lack a provider source-update heartbeat and verified complete ledger coverage,
so the real rated total stays unknown. A positive parsed rated row may alert below
the budget while the total remains unknown. Missing units, currency, timestamps,
prices or coverage never become a guessed zero. Trips persist until explicit rearm.

## Files, notifications and enforcement fields

On Linux, configuration must be a root-owned regular file, not group/world
writable; parent directories must prevent unprivileged replacement. Secret paths
are absolute external files. The parser validates paths without reading contents.
The installer requires root:cloudflare-cost-guard mode `0640` secrets and protected
ancestors; state is service-owned mode `0700`. Windows checks do not validate
POSIX ownership, so use Linux for deployment security validation.

For an owner-approved generic HTTPS JSON receiver, add this top-level member:

```json
{
  "notification": {
    "url_file": "/etc/cloudflare-cost-guard/secrets/notification.url",
    "max_attempts": 3
  }
}
```

Merge this member into the full config; this object is not a standalone config. The URL belongs in the protected
file, never JSON/Git. `max_attempts` limits due **events per run**; failed events
retry on later runs. This payload is not a native Slack/Discord message format.
See [delivery setup](runbook.md#notifications-and-scheduling). Omitting notification
is safe for a first probe; a later run queues incidents and exits 5 while alerts
remain pending.

Optional resource enforcement fields are `permitted_action`,
`executor_token_file`, `approved_manifest_file` and `approved_manifest_digest`
(lowercase SHA-256). Actions are `delete_worker` or `disable_worker_endpoints`,
only for explicitly enrolled Workers. Deletion always requires a resource budget.
In enforce mode, each resource with a hard limit requires an action, a separate
writer path and pinned approval. Warning-only budget resources may coexist with
armed resources, but must omit all action, writer and manifest fields. Initial installation stays observe-only with no writer references.
These fields alone do not establish owner approval or provider permissions.

## Automatic cutoff budget

A resource may have a `budget` object. This is distinct from the account's alert
`budget` amount. Start with [the synthetic observe example](../config.cutoff.example.json)
and follow [automatic cutoff](automatic-cutoff.md) for scope, approval and arming.
The example's prices are synthetic, its acceptance flags are false, and it contains
no writer or approval references.

| Budget field | Meaning |
| --- | --- |
| `hard_limit_usd` | Optional/null, or one positive Decimal string. A value enables a cutoff policy; it is an action trigger, not a maximum invoice. Account currency must be USD. |
| `warnings` | Optional array, default `[]`. Each entry has exactly one positive Decimal-string `usd` or `percent`. USD values must be below an existing hard limit. Percentage values must be greater than 0 and less than 100 and require a hard limit. Effective USD thresholds must be unique. |
| `source` | `workers_usage_estimate` or `account_rated_observed`. |
| `request_usd_per_million` | Positive Decimal request rate for the usage source. |
| `cpu_usd_per_million_ms` | Positive Decimal CPU-millisecond rate for the usage source. |
| `cpu_ms_per_request` | Positive Decimal planning reserve per request; not measured CPU or a proven bound. |
| `pricing_source`, `pricing_as_of` | Nonempty provenance and ISO date; required for the usage source. |
| `accept_approximate` | Default false; must be true to enforce a usage estimate. |
| `accept_partial` | Default false; must be true to enforce either source. |

Usage cost accumulates captured per-minute request buckets in the account's UTC
billing-day guard period, with maximum-count deduplication across polls. It applies
request rate plus the CPU planning reserve, without subtracting shared allowances.
The rated source uses the largest validated account charge line, not a sum or full
balance, and rejects all five pricing/reserve/provenance fields. It binds an account
trigger to an explicitly chosen Worker, without attributing its costs to that Worker.
Both sources remain partial/unknown below budget. No R2/D1/Queues budget actions
are implemented; unsupported product/action combinations are rejected.

No hard limit means warning-only monitoring and no provider write for that resource.
Only USD warnings are valid without a limit; `warnings: []` with a null/omitted
limit tracks the signal without warnings or cutoff. See [budget alerts](budget-alerts.md)
for examples, notification behavior and configuration updates.

The version 2 approval digest covers identity, action, cutoff/source/pricing/quality
semantics and account billing day/currency. Editing warnings alone does not invalidate
the cutoff approval; changing a hard limit or the other covered semantics does.
Quality acceptance alone never arms a write. See
[the complete procedure](automatic-cutoff.md#review-and-pin-approval).
