# Automatic Worker budget cutoff

Once explicitly armed, a scheduled `run` acts automatically when the selected
budget signal reaches `hard_limit_usd`. It does not ask for approval for each
incident. Initial installation remains observe-only with no writer token.

**This threshold triggers an action; it is not a guaranteed maximum Cloudflare
invoice.** The implementation has offline tests, including the real HTTP adapter
with injected provider responses. No live Cloudflare canary or deployed cutoff is
claimed by this change.

## Choose the action and scope

| Action | Provider operation | Result and remaining scope |
| --- | --- | --- |
| `delete_worker` | `DELETE /accounts/{account_id}/workers/scripts/{script_name}?force=false` | Destructively removes the selected script. Requires independent restore source and explicit deletion/stateless acknowledgements. There is no automatic backup or restore. |
| `disable_worker_endpoints` | POST script subdomain with `enabled=false`, `previews_enabled=false` | Disables workers.dev and preview flags only. Custom-domain routes and internal invocations can continue. It is not service-wide shutdown. |

[Deletion](https://developers.cloudflare.com/api/resources/workers/subresources/scripts/methods/delete/)
is not a reversible suspend. `force=true` is never sent. Cloudflare documents that
forcing deletion can break references and delete implemented Durable Object
namespaces; this guard rejects owned namespaces independently of the force flag.
The [subdomain controls](https://developers.cloudflare.com/api/resources/workers/subresources/scripts/subresources/subdomain/)
cover distinct flags. [Routes and custom domains](https://developers.cloudflare.com/workers/configuration/routing/)
are separate entry points.

The first supported target is a standalone, stateless HTTP Worker using the
`standard` usage model, with a single active version receiving 100% of traffic,
default `fetch` handler/exports, no
assets, Durable Object classes/owned namespaces, migrations, containers or service/data
bindings. Only plain-text, secret-text, JSON and version-metadata bindings are
accepted. Missing/ambiguous provider identity, settings or deployment/version
metadata blocks a write. Owned namespace enumeration must be complete.
Keep the enrolled script identity within these limits across future deployments.
Do not use a request-based CPU reserve for WebSockets or other work that is not
represented by incoming request counts.

R2, D1, Queues, Pages and other products have **no cutoff implementation here**.
Configuring these products with a guard budget or either action is rejected.
The guard never changes DNS, Access, routes, subscriptions or arbitrary commands.

## Choose one budget signal

The guard period uses the enrolled account's `billing_day` in UTC, clamped at
month end. It is an accounting window for the guard, not proof of an invoice
period. USD is required; a configured `hard_limit_usd` is a positive Decimal string.
It can be omitted/null for warning-only resources, which cannot authorize a write.
Optional [budget warnings](budget-alerts.md) operate independently of cutoff approval.
Account `budget` remains the older alert threshold; the resource's `budget` object
controls automatic cutoff.

### `workers_usage_estimate`

The ledger accumulates captured, disjoint one-minute request buckets for the exact
Worker within the guard period. Overlapping polls do not add the same minute
again; revisions retain that minute's maximum count. State survives restarts.
The estimate is:

```text
captured_requests / 1,000,000 *
(request_usd_per_million + cpu_ms_per_request * cpu_usd_per_million_ms)
```

All three rate/reserve values must be positive Decimal strings. Record the
pricing source and its ISO date. Consult [current Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/)
and your contract before choosing them; the example file's rates are deliberately
synthetic. No shared/free allowance is subtracted.

`cpu_ms_per_request` is your **planning reserve**, not observed aggregate CPU,
a provider-enforced maximum or a proven upper bound. Adaptive sampling, missing
pre-install history and downtime make the series partial. Below the threshold,
the result remains `unknown`, not healthy or zero. Explicit `accept_approximate`
and `accept_partial` are both required for this signal to authorize a cutoff.

### `account_rated_observed`

This signal uses the **largest individually validated incremental USD charge
line** observed for the account in the guard period. Distinct row identities do
not prove disjoint consumption, so lines are never summed. Repeated identities
are deduplicated; conflicting rows leave the signal unknown. It is a floor of
observed gross charges, not a complete or net account balance. No usage-price
fields are permitted for this source.

The target means “cut this approved Worker when the account signal reaches the
threshold”; it does not identify the Worker responsible for account charges.
Accept partial coverage explicitly. Billing rows can arrive very late or remain
unavailable, making this unsuitable for a prompt usage cutoff.

For either signal, unknown/partial evidence below the limit cannot promise safety.
At or above the limit, accepted quality can trigger the one approved action.
Polling and analytics delay, outages, API failures, in-flight work, CPU variability,
storage, base fees and other resources can all produce overshoot. No finite
maximum overshoot is guaranteed. An independent host heartbeat is still needed.

## Prepare while remaining in observe mode

Start with [getting started](getting-started.md), using reviewed source
`2d530d674e330473208bc75169289af9467ceca0`. It includes native notifications,
warnings, optional cutoff and `show-policy`; see [delivery evidence](native-notifications-evidence.md). Do not
substitute a moving branch. Later guide-only updates leave this runtime pin intact.
If installed code predates the feature, first upgrade it in observe mode using the
[reviewed-source update procedure](runbook.md#configuration-updates-upgrades-and-token-rotation).

Use [config.cutoff.example.json](../config.cutoff.example.json) as the structural
example. Replace synthetic IDs/rates, choose the exact Worker and action, and keep
configuration outside Git. It is `observe`, has no writer/approval references,
and its quality-acceptance flags default to false. Neither an action name nor
accepted quality alone can cause a provider write in observe mode.

After reviewing the source limitations, set the appropriate quality flags in your
protected **observe** source config. Choose the final budget, currency, billing day
and action before preparing approval. These semantics are included in its digest.
The administrator can generate a new root-only template from trusted installed
code; replace the synthetic command placeholders locally:

```sh
sudo sh -c 'cd /opt/cloudflare-cost-guard && exec /usr/bin/python3 -B -m cfguard prepare-cutoff --config /root/cfguard-config.json --account-id ACCOUNT_ID --resource-id SCRIPT_NAME --output /root/cfguard-cutoff.pending.json'
```

This special command writes only the new template: it does not contact Cloudflare,
read writer credentials or initialize usage/state. It refuses an existing output
or an output inside the source tree. Standard output contains a `resource_ref`
and `armed: false`, not raw target IDs. The private template does contain identity.
The default invalid expiry and false deletion acknowledgements leave it unarmed.

## Review and pin approval

The version 2 manifest has exactly these fields:

| Field | Required value |
| --- | --- |
| `version` | Integer `2` |
| `approval_reference` | Actual owner approval reference; replace the pending label |
| `expires_at` | Future explicit UTC ISO timestamp |
| `resource` | Exact enrolled `account_id`, `product`, `resource_id` |
| `action` | The configured action |
| `budget_digest` | Generated digest of identity/action/budget and account billing-day/currency semantics |
| `accept_approximate`, `accept_partial` | Exactly match the configured budget flags |
| `acknowledge_deletion`, `restore_source_confirmed`, `stateless_worker_confirmed` | All true for deletion, after the owner accepts destruction, verifies independent restore source and confirms the supported Worker scope |

The manifest is limited to 64 KiB; unknown/duplicate fields are rejected. It must
remain a root-owned regular file with protected parents and no group/world write.
Review it locally; do not invent approval or backup evidence.
Approval enrolls the exact account/script name, including its future versions;
it is not pinned forever to the current deployment. Changing the hard limit, source,
price, quality choice, billing day, currency or action requires a fresh matching
approval. Editing warning thresholds alone does not change the approval digest.
The file-byte digest additionally pins the exact manifest content.

Install a reviewed manifest under administrator control and hash the installed
bytes. Commands assume the installation's dedicated group already exists:

```sh
sudo install -d -o root -g cloudflare-cost-guard -m 0750 /etc/cloudflare-cost-guard/approvals
sudo install -o root -g cloudflare-cost-guard -m 0640 /root/cfguard-cutoff.pending.json /etc/cloudflare-cost-guard/approvals/example-worker.json
sudo sha256sum /etc/cloudflare-cost-guard/approvals/example-worker.json
```

Set `approved_manifest_file` to that external path and `approved_manifest_digest`
to the resulting lowercase SHA-256 in the protected source config. Provision a
**separate** root:service-group mode `0640` token file using the secure-file method
in getting-started; set `executor_token_file` to its path. Use Workers Scripts
Write restricted to the enrolled account as far as the provider permits. The
read token needs approved Scripts Read access for script/settings/deployment/version
and owned-namespace checks, alongside telemetry permissions. A denial blocks the
write; do not broaden to Global API keys or account-admin permissions to clear it.
A local target approval does not narrow the provider token's actual permissions.

## Arm and preview

Initial `deploy/install.py install` remains observe-only and rejects writer-token
references. The explicit `--allow-enforce` option arms or upgrades an **existing**
valid managed installation; it cannot bootstrap an enforce installation. Keep the
timer stopped and wait for the service to become inactive, as described in the
[upgrade procedure](runbook.md#configuration-updates-upgrades-and-token-rotation).
Do not interrupt an action in flight or edit installed config/ownership hashes.

Copy your prepared protected source config to a separate arming file, edit its
mode to `enforce`, and add the reviewed approval path/digest and writer-token path:

```sh
sudo install -o root -g root -m 0600 /root/cfguard-config.json /root/cfguard-enforce.json
sudoedit /root/cfguard-enforce.json
```

Use the root-controlled directory exported from the exact reviewed feature commit,
not the old monitoring-only source. After operator authorization, with both timer
and service inactive:

```sh
CFGUARD_SOURCE=/root/REPLACE_WITH_REVIEWED_FEATURE_SOURCE
sudo sh -c 'umask 022; exec /usr/bin/python3 -B "$1/deploy/install.py" install --config /root/cfguard-enforce.json --allow-enforce' cfguard-install "$CFGUARD_SOURCE"
cfguard validate --config /etc/cloudflare-cost-guard/config.json
cfguard enforce-preview --config /etc/cloudflare-cost-guard/config.json
```

The last commands use the installed `cfguard` helper from getting-started.
Resources with a hard limit require a supported budget action. Warning-only
budget resources can remain in the same enforce configuration, without
`permitted_action`, `executor_token_file`, `approved_manifest_file` or
`approved_manifest_digest`. It validates existing
ownership/hashes and protected credential/approval paths; it does not start the
timer. Once armed, scheduled runs can perform the approved write without another human confirmation. Review preview
and deployment checks before explicitly restarting scheduling.

Preview performs provider reads but constructs no writer, sends no mutation and
adds no ledger, outbox or action intent. An eligible preview reports `not_applied`
with reason `preview_eligible`; it does not establish a live cutoff. It may need
existing accumulated ledger evidence to reach the budget. `probe` is also read-only.

To convert an armed resource to warning-only, stop scheduling and first prepare
an observe source configuration. Preserve the original configuration and manifests
for any unresolved intent and reconcile it read-only before changing its semantics.
Then remove the resource's action/writer/manifest fields and set its hard limit to
null (converting any percentage warnings to USD). A null limit with remaining
action fields is rejected. Apply through the [managed update procedure](runbook.md#configuration-updates-upgrades-and-token-rotation);
never edit the installed config directly.

## Result and recovery

The guard rechecks budget, expiry and deployment fingerprint immediately before
one write, after persisting intent. Provider APIs have no conditional deletion by
fingerprint: a concurrent deployment can still race with deletion. Keep unsupported
state out of enrolled script identities and coordinate deployments with the guard.

| Result | Meaning |
| --- | --- |
| `worker_deleted` | Authenticated complete script inventory no longer contains the exact Worker. It does not prove a final bill. |
| `endpoints_disabled` | Both provider flags are false; routes and internal paths are outside this result. |
| `not_applied` | Preflight blocked, read-only preview, or definite writer 401/403 rejection with successful read-back. Inspect the reason; a recorded attempt needs manual rearm. |
| `uncertain` | The provider outcome cannot be confirmed. A timeout may still have applied the action. |

Subsequent runs reconcile saved attempts read-only. They never automatically retry
writes, recreate a script or re-enable endpoints. Retain the pinned manifest for
reconciliation; its expiry forbids a new action but does not prohibit reading back
an existing attempt. Review uncertainty without deleting state or replacing an
approval to force another call.

Manual [rearm](runbook.md#latches-and-private-identity-mapping) archives known terminal
budget intents (`worker_deleted`, `endpoints_disabled`, `not_applied`), preserves
all usage and audit history, and resets the local latch only. Pending/uncertain
attempts block rearm. If the same period's usage is still above budget, a later
armed run can act again. Restoration is a separate operator action; first disarm
and review the cause, independent source and remaining budget.

State schema 4 added the ledger and intent history; schema 5 adds notification
priority while preserving existing data and promotes queued legacy cutoff events.
Back up before upgrade; there is no downgrade migration. Historical implementation
and publication records describe their dated scope, not live proof of this feature.
