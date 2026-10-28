# Independent monitoring integration

## Goal and scope

Provide generic optional monitoring inside Cloudflare Cost Guard: independent host,
collection and delivery checks; positive subscription commitment alerts; explicit
Worker/zone inventory baselines; persistent reminders and affirmative recovery.
No provider mutations, automatic enrollment, financial ceiling, new repository,
visibility change or installation-specific data are part of this change.

## Implementation

1. Move the reviewed generic sampler, policy and watcher into `cfguard.monitoring`.
   Rename test modules and fixtures so discovery runs alongside the existing suite.
   Exercise the new CLI before and after moving the implementation.
2. Include nested package code in the managed installer while preserving trust,
   relative paths, ownership hashes and foreign-file refusal. Monitoring units and
   configuration remain separately reviewed opt-in templates, never auto-activated.
3. Add synthetic examples and generic setup/schema documentation. Link the optional
   module from README, capabilities and operations without changing dated evidence.
4. Run the entire credential-free suite and privacy checks. Obtain an independent
   whole-branch safety review, resolve important findings and require the existing
   three CI checks before merging through the normal PR workflow.

## Verification boundaries

Review schema-6 compatibility against real synthetic guard state, installed module
availability, unknown/stale recovery rules, protected token/config handling and
pending-recipient binding. Unit tests and CI do not establish live provider access,
systemd lifecycle, notification receipt or a maximum invoice. Private configuration,
host profiles, account/resource identities and deployment evidence remain external.
