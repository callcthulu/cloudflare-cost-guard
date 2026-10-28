# Budget warnings and optional cutoff

Configure a resource's `budget.warnings` independently of its optional
`hard_limit_usd`. Warnings send alerts; the hard limit can trigger the separately
approved action in enforce mode. Neither is a guaranteed maximum invoice.
Account-level `budget` is a separate older alert policy.

## Choose thresholds

Start from the complete [synthetic observe JSON](../config.cutoff.example.json).
It contains no credentials or approval references; quality acceptance is false
and rates are examples, not current provider prices. Keep a real source copy
outside Git. JSON has no comments; amounts and percentages are decimal strings.

Replace only its resource `budget` warning/limit fields with the desired policy:

```json
{
  "hard_limit_usd": "10.00",
  "warnings": [{"usd": "5.00"}, {"percent": "80"}, {"usd": "9.00"}]
}
```

This gives warnings at USD 5, 8 and 9, with a cutoff policy at USD 10. These
fragments are not standalone configuration: retain the resource identity, source,
pricing/provenance and quality fields from the full example. The source and
quality limitations in [automatic cutoff](automatic-cutoff.md#choose-one-budget-signal)
apply to warnings too; adding thresholds does not improve evidence quality.

For warning-only monitoring:

```json
{
  "hard_limit_usd": null,
  "warnings": [{"usd": "5.00"}, {"usd": "10.00"}]
}
```

Remove `permitted_action`, `executor_token_file`, `approved_manifest_file` and
`approved_manifest_digest` from this resource. It cannot authorize a provider
write, even alongside armed resources in an enforce configuration. Keep observe
for an initial installation. To track the signal without either warnings or
cutoff, use `"warnings": []` and a null/omitted hard limit.

Validation rejects:

- Entries with both `usd` and `percent`, neither field, or extra fields.
- Nonpositive values, JSON numbers, percentages at/above 100, or any percentage
  without a hard limit.
- USD warnings at/above an existing hard limit, or duplicate effective thresholds:
  with a USD 10 limit, `{"usd":"8.00"}` and `{"percent":"80"}` collide.
- A null/omitted hard limit with any remaining action, writer or manifest reference.

An omitted warnings array means no warnings. An omitted/null hard limit means no
cutoff for that budget. Source/pricing validation remains unchanged. Warnings can
report partial or approximate evidence without accepting it for enforcement;
quality acceptance is required only when arming a cutoff.
There is no fixed warning-count limit. Delivery is bounded per run, so many crossed
thresholds may take several runs to deliver.

## Inspect and update safely

`show-policy` parses config and pretty-prints sanitized resource references, mode,
source, currency, nullable hard limit, whether cutoff is enabled, and configured
warnings with their effective USD thresholds. It does not open state, read token
contents or contact Cloudflare. It describes configuration, not live source health
or proof that approval/provider checks will permit an action. `status` combines
current policies with local execution state.

On Linux, maintain a protected editable **source** file such as
`/root/cfguard-config.json`. The installed `/etc/cloudflare-cost-guard/config.json`
is hash-owned: direct editing makes managed updates refuse. Stop the timer and
wait for the service to be inactive, back up privately, then edit the source and
inspect it from the reviewed checkout:

```sh
CFGUARD_SOURCE=/root/REPLACE_WITH_REVIEWED_PINNED_SOURCE_DIRECTORY
sudoedit /root/cfguard-config.json
sudo sh -c 'cd "$1" && exec /usr/bin/python3 -B -m cfguard validate --config /root/cfguard-config.json' cfguard-config "$CFGUARD_SOURCE"
sudo sh -c 'cd "$1" && exec /usr/bin/python3 -B -m cfguard show-policy --config /root/cfguard-config.json' cfguard-config "$CFGUARD_SOURCE"
```

Apply with the [stopped managed update procedure](runbook.md#configuration-updates-upgrades-and-token-rotation),
including installed validation/probe before explicitly restarting scheduling.
An armed installation uses the [separate arming/update path](automatic-cutoff.md#arm-and-preview).
Editing warnings alone preserves version 2 cutoff approval. Changing the hard
limit, source, pricing/reserve, quality acceptance, currency or billing period
requires a fresh matching approval. Do not clear state to apply an edit.

To disarm, first use an observe source configuration through that procedure.
Preserve the original config/manifests while unresolved attempts require read-only
reconciliation; do not replace their semantics to force a retry. Once resolved,
remove action/writer/manifest fields before converting to a null hard limit.

Reviewed implementation including native notifications: `63ae782e95e3b8360541b0b539a4dc29e0c9384d`.
Use [getting started](getting-started.md) or the [agent guide](agent-deployment.md)
with that full pin. A moving branch is not a deployment pin.

## Notification behavior

Warnings are deduplicated per resource, source, UTC guard period and effective
USD threshold. Reordering warnings or changing `5.00` to `5` does not resend a
warning; the same threshold can notify again in the next period. A new threshold
introduced by an edit can alert on the next run if existing evidence crosses it.
Crossing several new thresholds can queue several warnings in one run.
A polling jump can cross warnings and the cutoff together. The cutoff does not
wait for alert delivery; some warnings may arrive after the cutoff result.

Notifications use a generic HTTPS JSON receiver. There is no native email or
Slack sender; an approved receiver can translate the payload. Budget events carry
value, nullable hard limit, threshold, period, quality and sanitized `resource_ref`
context. Critical confirmed/blocked/uncertain cutoff events use priority 100,
warnings 10 and routine events 0. All due events share one delivery cap per run:
`notification.max_attempts`, default 3 and maximum 10. Failed deliveries retry with
backoff; higher-priority due events take precedence over routine backlog.
HTTP acceptance is not proof a person received an alert. See
[notification setup](runbook.md#notifications-and-scheduling).

Run reports include crossed thresholds in `budget_warnings`. A crossing produces
warning exit code 4 when notifications have no failures or pending backlog; pending
or failed delivery takes precedence with exit 5. Partial collection still reports
`collection: unknown`. `probe` and `enforce-preview` display crossings but never
queue or deliver their alerts.

See [delivery evidence](budget-alerts-evidence.md) for offline tests, independent
review and disposable Linux checks. No live notification or cutoff claim is made.
