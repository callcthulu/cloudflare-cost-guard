# Sanitized monitoring observation version 1

The sampler consumes the current guard SQLite schema 6 and emits this independent
JSON contract. Unknown database schemas fail closed. This is a format contract,
not a dependency on a historical source commit. Timestamps are timezone-aware UTC
ISO strings; missing values are `null`. Decimal amounts are exact normalized
fixed-point strings, without float conversion or rounding.

References are the first 16 lowercase hexadecimal characters of SHA256 over the
canonical JSON array `[account_id, product, identity]`. They allow stable scope
comparison without exporting raw identifiers, but remain correlatable private data.
This synthetic example is illustrative, not a healthy-total assertion:

```json
{
  "version": 1,
  "observed_at": "2026-10-28T12:00:00+00:00",
  "guard": {
    "status": "ok",
    "last_attempt": "2026-10-28T11:59:00+00:00",
    "last_finished": "2026-10-28T11:59:00+00:00",
    "last_collection_success": null,
    "pending_notifications": 0,
    "oldest_pending_at": null
  },
  "accounts": [{
    "account_ref": "aaaaaaaaaaaaaaaa",
    "snapshot_at": "2026-10-28T11:59:00+00:00",
    "subscriptions_status": "complete",
    "subscriptions": [{
      "resource_ref": "bbbbbbbbbbbbbbbb",
      "amount": "0",
      "currency": "USD",
      "quality": "good",
      "allowed": true
    }],
    "coverage": [{
      "source": "billing_account_coverage",
      "status": "unavailable",
      "known_limitation": true
    }],
    "inventory": {
      "workers": {"status": "complete", "refs": [], "expected": []},
      "zones": {
        "status": "complete",
        "refs": ["cccccccccccccccc"],
        "expected": ["cccccccccccccccc"]
      }
    }
  }]
}
```

All enrolled accounts appear even on failure. Unknown guard reads use
`guard.status=unknown` and null timestamps rather than raw errors. Source states
normalize to `complete`, `approximate`, `unavailable`, `unknown`, `stale`,
`unsupported`, `unverified`, `covered` or `parsed`. Source names are fixed allowlisted
keys; per-zone keys use hashed references. Known limitations are exact configured
source/status matches. No raw IDs, domains, subscription/plan names, tokens,
recipients or provider messages belong in the observation.

The sampler configuration contains an absolute `guard_database` path and accounts
with private `id`, `read_token_file`, `expected_workers`, `expected_zones` and
`known_limitations`. The last is a fixed-source to exact normalized-state map.
Supported inventory products are only `workers` and `zones`. The watcher separately
pins `expected_account_refs`; see the [synthetic configurations](monitoring.md#configure-and-preview).

Policy assessment returns `issues`, `limitations` and `verified_scopes`. Each issue
has a stable `key`, `scope`, `reason`, `resource_ref`, `level` and bounded numeric/enum
`details`. Only affirmative fresh evidence verifies a scope. A failed, missing or
stale whole observation verifies no previous scopes. Fresh independent inventory
can still be assessed when a guard snapshot is stale/missing; subscriptions and
coverage from that snapshot remain unknown.

Persistent watch remembers previously affirmative coverage and can alert when it
becomes an acknowledged limitation. Stateless preview cannot assess this historical
transition. Recovery is confined to freshly verified scopes; absence from a broken
observation is never recovery. Policy defaults are `max_age_seconds=900`,
`future_tolerance_seconds=60` and `backlog_age_seconds=900`.
