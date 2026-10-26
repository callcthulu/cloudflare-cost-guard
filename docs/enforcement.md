# Narrow public-endpoint containment

The initial release runs in `observe`. **Live enforcement remains unavailable**:
the real client cannot currently prove complete internal reachability inventory,
exact non-sampled request evidence, or an authoritative public cutoff signature.
Fake tests prove local control flow, not a live Cloudflare result. An independent
review and separately approved disposable canary are required before enabling it.

The sole action is `disable_worker_endpoints`, which calls the script-subdomain
update with exactly `enabled=false` and `previews_enabled=false`. No Worker,
Access policy, DNS record, route, subscription or other resource is deleted or
modified. The pilot must have no routes, custom domains or known internal
triggers. A verified result covers the approved workers.dev/preview public
endpoints only. It does not prove that internal invocations or other charges stop.

## Approval file

An administrator installs a root-owned regular JSON manifest with no group/other
write permissions, in a protected directory. Its SHA-256 **file-byte digest** goes
in the enrolled resource's `approved_manifest_digest`; the external file path goes
in `approved_manifest_file`. A service-writable manifest is rejected even when its
digest matches. The file is limited to 64 KiB, duplicate/unknown keys are rejected,
and approval metadata must have exactly these fields:

| Field | Meaning |
| --- | --- |
| `version` | Integer `1` |
| `approval_reference` | Nonempty reference to the owner's actual approval |
| `expires_at` | Explicit future UTC ISO timestamp |
| `resource` | Object with exact `account_id`, `product`, `resource_id` |
| `action` | `disable_worker_endpoints` |
| `trigger` | Object with `metric`, decimal-string `limit`, `unit`, integer `window_seconds` |
| `baseline_digest` | SHA-256 of canonical complete endpoint inventory |
| `protected_resources` | Explicit array of excluded resource identity objects |
| `endpoints` | Exact nonempty list of approved HTTPS workers.dev/preview URLs |

Each excluded resource object has the same three identity fields as `resource`.
An empty exclusion list is explicit, not an omitted check. The target cannot be
one of the exclusions. URLs must have a workers.dev hostname, no credentials,
query or fragment, no non-HTTPS scheme and no nonstandard port. No arbitrary
origin probing or redirects are used to prove a cutoff.

Compute `baseline_digest` with `cfguard.actions.inventory_digest(inventory)` over
the complete inventory returned by the approved adapter. It includes identity,
endpoint flags, routes, custom domains, internal triggers, completeness and every
approved endpoint, plus any additional inventory fields. The baseline requires
both endpoint flags initially true. For this pilot routes/custom domains/internal
triggers must be empty and completeness must be true. Unknown reachability blocks
the action. The real adapter currently reports it unknown.

The trigger metric is an explicitly implemented raw `workers.requests` / `requests`
or `workers.cpu_ms` / `milliseconds` aggregate. The threshold and unit must exactly
match enrolled resource configuration. The manifest fixes the observation window
in seconds (1–3600). CPU is currently unavailable from the real adapter. Monetary
estimates, account totals, unknown units, sampled observations and unknown
sampling status cannot authorize an action. A zero currency price is unnecessary
for a correctly approved raw usage threshold.

A file and digest are technical controls, not evidence that a human reviewed
the change. Preserve the approval reference and actual owner approval in the
private deployment report. Do not fabricate approval while preparing a template.

## Execution and recovery

`preflight(proposal, config, client)` performs reads only. It requires enforce
mode, unique enrolled identity, separate executor credential path, current pinned
manifest, fresh complete exact evidence matching the proposal's evidence ID,
known units/window and the approved inventory. It returns an immutable prepared
plan. Arbitrary hand-created `ActionPlan` objects cannot be executed.

`execute(plan, client, store)` rechecks approval/evidence/inventory, writes a
durable pending intent, then rechecks immediately before the sole mutation.
Any operator/config/inventory drift blocks the call. The executor credential
must be different from the read credential; where the adapter exposes its token
path, execution checks that it is the configured executor path. Provider token
permissions may still be broader than one Worker; local approval is not a
provider-enforced permission boundary.

After the call, actual flags are read back and every approved endpoint must have
a decisive adapter result of `blocked`. HTTP 2xx from the mutation alone is not
success. Both flags false plus every decisive probe produce
`verified_public_cutoff`; unknown/reachable endpoints or incomplete verification
produce `partial`. An unapplied write with both flags still true is `failed`.
No response text, token or arbitrary provider error payload is returned.

There are **no automatic mutation retries**. A timeout can mean the provider
applied the write, so the guard reads actual state rather than resending it.
After a crash, `reconcile(resource, config, client, store)` verifies the existing
intent using read-only manifest/identity/inventory/probe checks. It deliberately
does not require the old spike to persist: an effective cutoff may remove that
spike. It cannot create a new intent or make a provider write. Partial/failed
attempts remain latched for operator handling; repeated runs do not resend writes.
Completed results retain their original attempt ID and verification timestamp.

Read-only recovery still requires the pinned original approval, valid timestamp
format and matching inventory. The original approval may have expired because
recovery only reads back a previously authorized attempt. Expiry continues to
forbid a new mutation. Changed approval or drift stays partial rather than being
treated as proof. Replacing an expired approval does not silently authorize or
erase an existing attempt. An operator must review that situation explicitly.

Observe and `enforce-preview` never invoke execution. The initial deployment
must not install an executor token. Rearm is a local operator action; it never
reenables provider endpoints. Uninstall and rollback also leave endpoint state
untouched. A read-check-write race cannot be eliminated without provider-side
conditional mutation; the narrow operation only disables approved public flags.
