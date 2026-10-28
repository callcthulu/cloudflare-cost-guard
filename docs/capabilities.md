# Provider capabilities

Official contracts checked 2026-10-27. This describes implemented offline adapters;
account access, actual latency and live endpoint containment remain unverified.

Cloudflare also offers [native budget alerts](https://developers.cloudflare.com/billing/manage/budget-alerts/)
for eligible Pay-as-you-go accounts; these notify rather than cap usage. See
[the launch plan](launch-plan.md) for current positioning alongside native controls.
This utility is an additional local usage/subscription view, not proof of a complete
bill or a substitute for evaluating native controls. No billing settings are changed.

| Source | Implemented evidence | Limits and failure behavior |
| --- | --- | --- |
| Workers GraphQL | `sum.requests`, one account aggregate and distinct script breakdowns | Five disjoint one-minute partitions covering the previous five completed minutes. Adaptive analytics; sampling status is unknown, so every value is approximate. No provider monthly total. An explicit budget policy can accept captured minute buckets as a partial estimate. |
| Workers CPU | None | The documented tutorial exposes CPU quantiles. No conversion of quantiles into a total; `workers.cpu_ms` is unsupported. |
| Account subscriptions | Separate commitment inventory | Billing Read. Explicit subscription IDs and plan IDs required. Missing price/currency/identity is unknown. Plan IDs, such as `free`, match `expected_subscriptions`. |
| Configured zone subscriptions | Singular subscription object per configured zone | Billing Read; `GET /zones/{zone_id}/subscription`. Endpoint appearances retain zone provenance but share account/provider identity with the account list. No automatic zone discovery. |
| Billable Usage V1 info | Explicit account coverage and billing metadata | `GET /accounts/{account_id}/billable-usage/info`. `covered:false` is unavailable coverage, not zero spend or a permission failure. Missing/invalid info is unknown. Missing anchors leave the period unverified. |
| Billable Usage V1 Alpha | Parsed incremental rated rows | Access must be probed. PascalCase contract only. Missing source update heartbeat prevents a complete/fresh total; positive parsed charges can still alert. Empty/denied responses mean unknown. |
| Other products | Possible subscription/rated rows only | No fast usage adapter or containment. No complete account product inventory is claimed. |
| Legacy endpoint inventory | Subdomain flags, account custom domains, configured-zone routes, cron schedules | Inbound bindings/queues and routes in other zones are not proven absent. `complete=false` blocks the legacy version 1 exact-evidence path. |
| Usage-budget ledger | Captured disjoint one-minute requests per enrolled Worker, deduplicated across polls/restarts | Decimal gross estimate with explicit CPU planning reserve and no shared allowance; approximate/partial, unknown below threshold. Both quality acceptances required to act. |
| Account-rated guard | Largest validated incremental USD account charge line | No sum without proven disjoint rows; delayed/partial floor. Explicit Worker target binding and partial acceptance, not attribution or complete invoice. |
| Budget cutoff preflight | Exact script identity, settings, current deployment/versions, complete owned-namespace list | Single-version stateless HTTP only; missing metadata, assets, stateful/export/handler/binding features block. Does not freeze future deployments or eliminate read/write races. |
| Subdomain disable | One POST setting both flags false | Version 2 armed budget action confirms API flags only; routes/internal invocations can continue. No automatic write retry. |
| Worker deletion | One DELETE of exact script with fixed `force=false` | Destructive version 2 armed budget action; independent restore source and explicit owner acknowledgements. Read-only authenticated absence confirms script removal, not a final bill. |
| Public probe | HTTPS GET without credentials | Only `*.workers.dev`, no redirects. A 2xx means reachable; other responses are unknown. Arbitrary Worker-generated 403/404 responses never prove provider cutoff. |

## Optional independent monitoring

[`cfguard.monitoring`](monitoring.md) adds a read-only view of the guard's current
schema-6 SQLite state and bounded GET-only Worker/zone inventory. A sampler on the
guard host exports a sanitized observation; a watcher on another host detects
stale/missing runs, delayed notification backlog, inventory drift and validated
positive USD subscription rows, including allowed plans. Subscription rows remain
separate; they are never summed into a complete bill. Explicit private baselines
do not enroll resources or expand the cutoff scope.

Complete inventories support drift assessment only for Workers and zones. Missing,
incomplete or account-mismatched data stays unknown. A configured exact known
coverage limitation remains visible, and persistent watch detects loss of formerly
affirmative coverage. Default watch is stateless preview; `--apply` persists its
own incidents and `--apply --send` can send due monitoring emails. It never runs
the guard, writes guard state or performs Cloudflare mutations. The main installer
does not enable the optional templates. See the [schema](monitoring-schema.md)
and [verification limits](monitoring-verification.md).

## Contract and pagination details

The [Workers tutorial](https://developers.cloudflare.com/analytics/graphql-api/tutorials/querying-workers-metrics/)
provides the query fields. [Adaptive sampling](https://developers.cloudflare.com/analytics/graphql-api/sampling/)
prevents assuming exactness from a low count. Each time partition requests up to
10,000 rows; reaching that limit rejects the entire observation. Empty partitions,
out-of-window/missing timestamps, duplicated bucket identities, malformed sums or
GraphQL errors inside HTTP 200 also produce unknown evidence. Rows are grouped by
provider timestamp, script name and status. Discovered scripts are evidence only;
they are never enrolled for modification. Account totals and breakdowns must never
be added together.

The [account subscriptions endpoint](https://developers.cloudflare.com/api/resources/accounts/subresources/subscriptions/methods/get/)
returns a list with optional `result_info`, but no documented pagination
query parameters. This adapter accepts an unpaginated result, or a
result whose `total_count` equals the returned count. A larger/ambiguous total
fails closed as incomplete rather than guessing `page` parameters. The same
principle applies to [routes](https://developers.cloudflare.com/api/resources/workers/subresources/routes/methods/list/)
and [custom domains](https://developers.cloudflare.com/api/resources/workers/subresources/domains/methods/list/).
Consequently an account whose endpoint needs undocumented pagination is not
fully supported until its actual contract is verified.

The [zone subscription endpoint](https://developers.cloudflare.com/api/resources/zones/subresources/subscriptions/methods/get/)
is singular and returns an object. A list, null, absent object or malformed
identity/plan/price/currency is unknown. The plural zone route is not used.
An empty account list with a nonzero `total_count` still fails completeness.
Completeness here describes that endpoint response, never an all-product inventory.

Commitments reconcile by owning account plus verified provider subscription ID,
independent of endpoint. Both endpoint appearances remain in the private snapshot;
the zone appearance supplies its zone attribution. A shared zero or positive
subscription counts once. Conflicting amount, currency, plan, identity or zone
attribution makes the commitment total unknown. Two distinct IDs remain distinct;
display names do not identify subscriptions. Declared plan scope must be compatible
with zone attribution. A forbidden plan can still raise an account alert when the
commitment total is unknown; it never selects a site or authorizes containment.

The [V1 info contract](https://developers.cloudflare.com/api/resources/billing/subresources/usage/methods/get_account_usage_info_v1/)
supplies `covered` and subscription metadata separately from usage rows.
`billing_account_coverage` reports `covered`, `unavailable`, or `unknown:<code>`;
`billing_info` distinguishes parsed, unknown and not fetched. A later covered
response can replace unavailable coverage on the next hourly fetch. Neither
state proves a complete rated balance. `billing_period` remains `unverified`
unless the operator has independently verified configuration and valid active
metadata has one common, nonfuture UTC-midnight anchor matching `billing_day`.
Empty, inactive or ambiguous subscription metadata cannot verify a period.
These fields are cached with rated evidence between hourly fetches, retaining
their original fetch time. Stale/future cache entries, old cache formats, billing-day
changes and period rollover cannot promote period verification. Positive rated
rows remain separate alert evidence even when account coverage is unavailable.
Verified metadata carries `billing_period_valid_until`, bounded by the period
end, active subscription endings and known future subscription starts. Cached
proof expires at that boundary; it never outlives a known metadata transition.
Policy requires explicit parsed info, covered-account and verified-period flags;
absent flags cannot establish a zero total, even for synthetic complete rows.

The [V1 billing schema](https://developers.cloudflare.com/api/resources/billing/subresources/usage/methods/get_account_usage_v1/)
documents `ContractedCost` per charge window, `CumulatedContractedCost` per billing
period and `BillingCurrency`. Only `ContractedCost` becomes an incremental row;
cumulative costs are not added. Source identity hashes the non-monetary account,
billing/charge windows, category, service, charge description, units, subscription
and zone dimensions. Exact duplicates collapse; conflicting costs with the same
identity invalidate the stream. Missing dimensions invalidate it. There is no
documented unique line ID: this composite identity must be checked against actual
account records before relying on reconciliation. No `BillingPeriodEnd`, update
timestamp or currency is invented. `ChargePeriodEnd` is preserved as charge-window
coverage, not a provider update heartbeat. V2 is never substituted for V1.

## Transport and credential boundary

API requests use only `https://api.cloudflare.com/client/v4`, verified TLS, disabled
environment proxies and denied redirects. Default bounds: 10-second request
timeout, two read attempts, 80 requests/client, 2 MB response body, short bounded
backoff. The runner also enforces its Linux run deadline. Writes use one attempt;
timeouts require reconciliation. Raw payloads, headers and tokens never enter
exception messages. A client binds to one account and one token-file reference.

Tokens are read from bounded regular files, with symlinks/file replacement rejected.
Linux permits service-owned `0600`, or root-owned `0640` for the current effective
service group; group/world writable or world-readable files are rejected.
Administrator ownership of parent directories remains an installation requirement.
Windows does not implement POSIX ACL verification; production permission validation
must run on Linux. Observe installations require no executor credential.

## Read-token setup

Use one custom token per configured account, limited to that exact account and
explicit zone resources wherever Cloudflare permits that scope. Start with
**Account > Account Analytics > Read** for GraphQL and **Billing Read** for
subscription inventory. Review the token summary; do not grant Billing Write,
DNS Edit, Access Edit or Workers Scripts Edit to an observe token. Use an expiry
and a stable host-IP restriction if they fit your existing operation.

The [Analytics authentication guide](https://developers.cloudflare.com/analytics/graphql-api/getting-started/authentication/api-token-auth/)
documents the analytics permission; the subscription endpoint above documents
Billing Read. V1 billing is Alpha and its current reference does not state a
complete accepted-permission recipe: probe with the approved read token and
record denial as unknown. Do not switch to a Global API key or broaden permissions
to make a test pass. Exact account availability and token scopes remain a live gate.

Observe collection does not need script write permissions. Budget-cutoff preflight
uses the reader for Scripts Read metadata and owned-namespace inventory. The
separate writer needs Workers Scripts Write for its one action, without Analytics
or Billing permissions. Exact availability/scope remains an authorized deployment
check. Executor permissions can be broader than one Worker and are not contained
by a local allowlist. No executor token is installed initially.

Before enabling any complete rated total, verify the composite source identity
against provider records and prove non-overlap per source series. Current code
does not claim that proof: the real rated total stays unknown, with positive
parsed rows reported as alerts rather than a complete account balance.

The [subdomain API](https://developers.cloudflare.com/api/resources/workers/subresources/scripts/subresources/subdomain/)
and [script deletion API](https://developers.cloudflare.com/api/resources/workers/subresources/scripts/methods/delete/)
document the two writes. [Script settings](https://developers.cloudflare.com/api/resources/workers/subresources/scripts/subresources/script_and_version_settings/methods/get/),
[active deployments](https://developers.cloudflare.com/api/resources/workers/subresources/scripts/subresources/deployments/methods/list/),
[version details](https://developers.cloudflare.com/api/resources/workers/subresources/scripts/subresources/versions/methods/get/)
and [owned namespaces](https://developers.cloudflare.com/api/resources/durable_objects/subresources/namespaces/methods/list/)
provide the stateless preflight evidence. No provider conditional DELETE contract
eliminates a concurrent-deployment race. See [automatic cutoff](automatic-cutoff.md)
for explicit approvals, scope, overshoot and recovery. Offline HTTP-adapter tests
are not a live provider canary or proof of a maximum invoice.
