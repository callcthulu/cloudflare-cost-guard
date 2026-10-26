# Configuration

Copy `config.example.json` to an administrator-controlled location and replace
its synthetic IDs. Run `validate` before enabling scheduled collection. The
example contains no credentials and no executor. Keep actual configuration,
tokens, notifications and evidence outside Git.

The parser rejects unknown fields, duplicate JSON keys and identities, malformed
account/zone IDs, cross-account zone references, relative secret paths, numeric
JSON money and non-finite or negative values. All amounts, allowances and limits
are decimal **strings**; currencies use explicit three-letter uppercase codes.
No currency conversion is performed. Provider resource IDs cannot contain URL
path delimiters. A display name or hostname never becomes a resource identity.

On Linux the configuration must be a root-owned regular file without group or
other write permission. Its parent directories must prevent non-admin replacement
(standard root-owned sticky directories are permitted). Ownership checks are not
performed on Windows; use the Linux installation for service security validation.
The parser validates secret **paths**, without reading secret contents.

Each account specifies its ID, read-token file, UTC billing anchor day (1–31),
budget, currency and enrolled zone IDs. `billing_period_verified` defaults to
false: set it true only after verifying the actual account billing boundary.
Days missing from a month clamp to its last day, then return to the original
anchor next month. For example day 31 produces February 28 to March 31 in a
non-leap year. Periods are half-open: a row ending at the new period start belongs
to the old period. `max_data_age_seconds` defaults to 900; data time determines
freshness, never fetch time.

`expected_subscriptions` contains expected **rate plan IDs**, such as `free`,
from `rate_plan.id`; it does not contain each subscription record's random `id`.
An empty list does not establish that products have no metered charges. Resource
enrollment is explicit: one `(account_id, product, resource_id)` may have several
hostnames/zones. Repeating its identity is an error. Discovery never enrolls a
resource for modification. Each threshold has a metric, limit, unit and optional
`warning` value no higher than its limit. Metric and unit names must match the
collector. Initial request metrics use `workers.requests` / `requests`; CPU totals
remain unsupported unless an aggregate with known semantics is available.

For Workers, `resource_id` is the exact deployed **script/service name** used in
`/accounts/{account_id}/workers/scripts/{script_name}/...`, not a hostname, route,
display name or deployment-version ID. Request limits currently apply to the
collector's rolling five completed minutes, not a monthly allowance.

Prices are optional; missing prices produce an unavailable estimate. A price
requires `metric`, `unit`, `currency`, `amount`, `per_quantity`, `allowance`,
`source` and ISO `as_of` date. The allowance is shared once per account/product
period. Synthetic fixture pricing would be amount `"0.30"`, quantity
`"1000000"` and allowance `"10000000"`; that is a test input, not live pricing.
Only a verified complete account billing-period series can use it. Five-minute
observations and resource subsets cannot stand in for monthly account totals.

Estimates, rated usage and subscription commitments remain separate report
dimensions. A positive rated charge alerts even below the configured budget.
Unknown coverage, timestamps, units, currency, duplicate charge identity or price
produce unknown, never a guessed zero. Approximate/sampled data can warn but
cannot authorize a cutoff. Trips persist until explicit operator rearm.

Missing `mode` means `observe`. The sole supported action name is
`disable_worker_endpoints` for Workers. Configuring that name only permits a
proposal; the executor independently requires an exact approved manifest,
executor token, current complete evidence and eligible endpoint inventory.
Optional resource fields are `permitted_action`, `executor_token_file`,
`approved_manifest_file` and `approved_manifest_digest` (lowercase SHA-256).
Install no executor credential for the initial observe deployment.

Optional notification configuration is `{"url_file": "/etc/cloudflare-cost-guard/notification.url",
"max_attempts": 3}`. The destination is read from a protected external file;
the JSON must not contain the URL or any notification secret. Run timeout defaults
to 240 seconds and must stay below the five-minute interval. Heartbeat maximum
age defaults to 660 seconds; an independent approved monitor is still needed to
detect a stopped host.
