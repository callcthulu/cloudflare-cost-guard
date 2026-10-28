# Threat model

Assets: read/executor tokens, private inventory, notification destination, state/latches,
approved action scope and availability of unrelated resources.

Trusted: system administrator, root-owned installed code/config/manifests and OS/TLS
trust store. The dedicated service user is not an approval authority. Anyone who can
write installed code or the action manifest can defeat local policy; provider token
scope is still the ultimate remote permission boundary.

Untrusted: provider payloads, API errors, analytics quality, network timeouts, public
endpoint responses, local unprivileged users and notification failures. Treat URLs
and provider strings as data. Do not execute them or interpolate them into commands.

Defenses: strict identifiers and enrollment, fixed API origin, no redirects, TLS,
bounded parsing/query/retry budgets, protected secret files, one process lock,
transactions, exact action manifest/digest, fresh evidence and inventory, prewritten
intent, read-back and conservative public probes, idempotent outbox.

Residual risks: delayed billing/analytics, unavailable Alpha billing, unsupported
products and attribution, broad account permissions on executor tokens, concurrent
provider edits between final check and write, ambiguous probes, service account
compromise, stopped host and failed notification channel. Independent heartbeat
monitoring is an operator responsibility; a dead host cannot send its own alarm.

Automatic budget cutoff adds an intentionally destructive operation: deleting an
explicitly approved stateless HTTP Worker with `force=false`. A protected approval
binds the account, script, action, budget, currency and guard-period semantics.
The separate writer is constructed only after durable intent and repeated
read-only eligibility checks. Unknown results reconcile without automatic retries;
manual rearm never restores provider resources or erases accounting.

Sampling, missing history, CPU planning reserves and delayed rated charge lines
cannot guarantee an invoice cap or bounded overshoot. Deletion has no conditional
version check: a concurrent deployment can race the final eligibility read. Keep
the enrolled identity stateless and coordinate deployments. Provider token scopes
may cover other scripts in the same account even though application writes are
restricted to the enrolled script. An independent restore source is required;
there is no automatic backup. Endpoint flag disabling covers only workers.dev and
preview. See [automatic cutoff](automatic-cutoff.md) for the full supported subset
and [current evidence](automatic-cutoff-evidence.md) for what was tested.

Notification destinations are separate approved disclosure boundaries. Per-event
recipient/configuration digests prevent pending messages being redirected by
configuration changes; new targets do not receive history. Numeric Telegram IDs
avoid mutable username destinations. Removed or changed routes preserve cancelled
delivery evidence. Email uses verified TLS, with no plaintext fallback; native
HTTPS clients refuse redirects and environment proxies. Alert text uses sanitized
fields and suppresses mentions. Provider acceptance does not prove human receipt,
and ambiguous timeouts can cause duplicate messages. A compromised service identity
can read its notification credentials; these controls do not contain host compromise.

Optional [independent monitoring](monitoring.md) adds two boundaries. The sampler
can read guard schema-6 SQLite and approved read tokens, so it belongs inside the
guard host's trusted service boundary. It opens guard state read-only and exports
only hashed references, bounded evidence and timestamps into its own private
directory. Hashing reduces disclosure; references remain correlatable and should
not be treated as anonymous public data. A compromised sampler can falsify its
observations; the watcher cannot attest to the guard host's integrity.

The watcher needs only a local sanitized file or a narrow SSH read identity, plus
independent SMTP credentials. SSH uses BatchMode, strict known-host verification
and a fixed bounded read command; no arbitrary remote command hook or public health
endpoint is provided. Provision forced-command keys without forwarding and protect
configuration, key/known-host files and their ancestors against replacement. The
watcher has no need for Cloudflare credentials or guard SQLite access. Its own
SQLite stores incidents/delivery and never authorizes provider actions. SMTP
destination changes cancel historical pending deliveries rather than redirecting
them; acceptance still does not prove human receipt. A shared host or shared failed
mail dependency defeats independence. The watcher itself requires an existing
external uptime check or an explicitly accepted blind spot. New resources can incur
charges between polls; monitoring adds no financial cap or all-product coverage.
