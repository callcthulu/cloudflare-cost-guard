# Notifications

Send budget warnings and cutoff outcomes directly to email, Telegram, Slack or
Discord, in any combination. Generic HTTPS JSON receivers remain supported.
Configure destinations before enabling the timer. This guide describes the native
channel extension; older pinned installations need a reviewed upgrade first.
Source tests do not establish live delivery or owner approval.
See [verification evidence](native-notifications-evidence.md) for tested scope.
Reviewed implementation: `63ae782e95e3b8360541b0b539a4dc29e0c9384d`.
Use [getting started](getting-started.md) or the [agent guide](agent-deployment.md)
with this full source pin.

## Choose destinations

| Type | Owner preparation | Protected files |
| --- | --- | --- |
| `email` | Use an existing permitted SMTP account with TLS; no mail server to install. | `settings_file`: SMTP JSON described below. |
| `telegram` | Create a bot with BotFather, start a private conversation with it once, and obtain the intended chat ID privately. | `token_file` and `chat_id_file`. |
| `slack` | Install/approve a Slack app with incoming webhooks and authorize its destination channel. | `url_file`: incoming webhook URL. |
| `discord` | Create an incoming webhook for the intended channel using owner permissions. | `url_file`: incoming webhook URL. |
| `webhook` | Approve an existing HTTPS receiver accepting the original incident JSON. | `url_file`: receiver URL. |

Telegram uses outbound `sendMessage`; the guard needs no bot listener, hosted bot
service or inbound webhook. Supply a nonzero signed-64-bit **numeric chat ID**;
mutable `@username` aliases are rejected so queued alerts stay bound to a stable
recipient. Discord incoming webhooks need no message-reading bot.
Slack installation/channel approval remains an owner action. Follow the official
[Slack incoming webhook guide](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/),
[Discord webhook API](https://docs.discord.com/developers/resources/webhook),
[Telegram bot setup](https://core.telegram.org/bots/tutorial#obtain-your-bot-token)
and [Telegram sendMessage API](https://core.telegram.org/bots/api#sendmessage).
Do not paste credential-bearing API URLs into prompts, shell history or support reports.
Email requires a relay/account permitting username/password SMTP authentication,
possibly with a provider-issued app password. OAuth-only SMTP is unsupported.
TLS is required; the adapter never falls back to plaintext.

## Editable configuration

Merge this member into your protected source configuration. The
[complete synthetic example](../config.notifications.example.json) also includes
observe-mode monitoring and synthetic budget policy; replace its example data
before use. No writer credentials or cutoff approval are included.

```json
{
  "notification": {
    "max_attempts": 3,
    "targets": [
      {"id": "ops-slack", "type": "slack", "url_file": "/etc/cloudflare-cost-guard/secrets/slack.url"},
      {"id": "ops-discord", "type": "discord", "url_file": "/etc/cloudflare-cost-guard/secrets/discord.url"},
      {"id": "ops-telegram", "type": "telegram", "token_file": "/etc/cloudflare-cost-guard/secrets/telegram.token", "chat_id_file": "/etc/cloudflare-cost-guard/secrets/telegram-chat.id"},
      {"id": "ops-email", "type": "email", "settings_file": "/etc/cloudflare-cost-guard/secrets/smtp.json"}
    ]
  }
}
```

Keep only the destinations you need: 1–16 targets, unique stable IDs matching
`[a-z][a-z0-9_-]{0,63}`. `max_attempts` is 1–10 (default 3), shared across all due
destination deliveries in one run. It is not the lifetime retry count. Existing
`notification: {"url_file": "...", "max_attempts": 3}` generic receivers continue
to work. That legacy member and `targets` are mutually exclusive.

URLs, bot tokens, chat IDs, SMTP details and real recipient addresses belong only
in external protected files. Paths are absolute. On Linux, use root ownership,
service group `cloudflare-cost-guard`, mode `0640` and protected parent directories.
Never weaken permissions to let an ordinary login user inspect secrets.
Provision files through your existing secure process; for a privately staged file:

```sh
sudo install -o root -g cloudflare-cost-guard -m 0640 \
  /root/secure-import/slack.url /etc/cloudflare-cost-guard/secrets/slack.url
```

The URL/token/chat files contain their one value. `smtp.json` contains exactly the
following fields (all example credentials and addresses below are synthetic):

```json
{
  "host": "smtp.example.invalid",
  "port": 465,
  "tls": "ssl",
  "username": "synthetic-user",
  "password": "SYNTHETIC-REPLACE-OUTSIDE-GIT",
  "from": "guard@example.invalid",
  "to": "owner@example.invalid"
}
```

TLS is mandatory: `ssl` for implicit TLS, or `starttls` using your provider's
submission settings (commonly port 587). Use existing permitted SMTP credentials;
consult your mail provider for host, port and authorized sender. `to` is exactly
one email recipient per target. Add another email target and protected settings
file for another recipient so delivery/retries remain independent.

## Preview and explicit synthetic send

The installed [cfguard helper](getting-started.md#5-install-validate-and-probe)
runs as the service user:

```sh
cfguard show-policy --config /etc/cloudflare-cost-guard/config.json
cfguard test-notification --config /etc/cloudflare-cost-guard/config.json --target ops-slack
```

`show-policy` includes sanitized target references/types. Default test mode reads
configuration only: no secret files, state, provider calls or notification send.
It previews a synthetic message for the selected target. After explicit owner
approval to message that destination, send exactly that one synthetic message:

```sh
cfguard test-notification --config /etc/cloudflare-cost-guard/config.json --target ops-slack --send
```

Repeat for each selected target and obtain owner-confirmed receipt. Even `--send`
never calls Cloudflare, changes cutoff state or flushes the incident queue.
Provider/SMTP acceptance is not proof that a human saw the message.

For root-only source JSON, use a trusted root-controlled checkout as in the
[managed update procedure](runbook.md#configuration-updates-upgrades-and-token-rotation).
These configuration-only commands do not require giving the service user access
to `/root`:

```sh
CFGUARD_SOURCE=/root/cfguard-source
sudo sh -c 'cd "$1" && exec /usr/bin/python3 -B -m cfguard validate --config /root/cfguard-config.json' cfguard-config "$CFGUARD_SOURCE"
sudo sh -c 'cd "$1" && exec /usr/bin/python3 -B -m cfguard show-policy --config /root/cfguard-config.json' cfguard-config "$CFGUARD_SOURCE"
sudo sh -c 'cd "$1" && exec /usr/bin/python3 -B -m cfguard test-notification --config /root/cfguard-config.json --target ops-slack' cfguard-config "$CFGUARD_SOURCE"
```

Appending `--send` inside the last quoted command is an explicit real send and
requires authorization for that destination. Do not run `run` as root to test alerts.

## Delivery behavior

Native messages present readable warnings and confirmed, blocked or uncertain
cutoff outcomes with sanitized resource references, amounts/thresholds, source
quality and UTC period where available. Provider-controlled strings are sanitized
and channel mentions are suppressed; inventory and secrets are not alert content.
Generic receivers retain incident JSON and should deduplicate by `incident_id`.

Each incident snapshots its configured target set and configuration/recipient
digests before delivery. Destinations have independent pending, success, retry and
cancellation state. New targets never receive historical backlog. Due cutoff
outcomes precede warnings and routine events without bypassing retry backoff.
Missing credentials fail the affected delivery for retry; success at another
destination remains recorded. An unresolved destination may bind when its first
valid credential file becomes available, without replacing a prior recipient.

Network timeouts can leave acceptance uncertain and a later retry may duplicate a
message. There is no exactly-once or human-receipt guarantee. Channels depend on
independent external providers, and none replaces independent host-outage monitoring.
Use `status` and run delivery results to inspect pending/cancelled outcomes locally.

## Changing destinations and rotating secrets

Stop scheduling and wait for any active run before changes. Inspect pending
state, take a protected [state backup](runbook.md#state-backup-and-restore), and
record the current source configuration privately. Edit the protected source JSON,
then validate, inspect policy and preview each changed target. After approved
installation, explicitly send the selected synthetic tests and confirm receipt
before restarting scheduling.

Removing/replacing a target cancels its old pending deliveries while preserving
evidence. Reusing its ID with changed configuration does not reroute backlog.
Changing a Slack, Discord or generic webhook URL also cancels old pending delivery:
the guard cannot prove a new URL has the same recipient. SMTP password rotation and
Telegram token rotation for the same bot can retain recipient binding; changing
recipient, SMTP destination identity or bot identity cannot silently reroute it.
When switching legacy `url_file` to `targets`, unbound legacy pending deliveries
are explicitly cancelled rather than sent to new recipients. Inspect that status
and retain the old evidence; do not delete SQLite to clear it.

The installed `/etc/cloudflare-cost-guard/config.json` is hash-owned: never edit it
directly. Use the [stopped managed installer update](runbook.md#configuration-updates-upgrades-and-token-rotation)
from protected source JSON and explicitly restart the timer after checks. Same-path
credential rotation needs no config edit, but still requires stopped scheduling,
protected files and review of pending recipient binding. Native-channel source
verification and a synthetic send are separate from live monitoring, scheduled-run
and cutoff-canary evidence.
