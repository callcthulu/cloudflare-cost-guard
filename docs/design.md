# Design and safety boundaries

Python 3.11+ standard library, JSON administration, SQLite persistence, Linux systemd.
Default mode is observe. No SaaS, LLM, paid CI, hosted Worker or paid add-on is required.

The utility collects account and zone subscription inventory, approximate Workers
analytics and, where actually available, V1 rated usage. Each source has separate
coverage, timestamps and quality. Missing or denied data is unknown, never zero.
Estimates, rated charges and subscription commitments are separate ledgers.
Decimal strings, explicit units/currency and verified UTC billing periods are required.
Account aggregates are never added to their resource or zone breakdowns. Shared
allowances apply once per account/product/period. Enrollment is explicit.

Policy evaluation is pure. State latches trips and persists observations, last-good
evidence, incidents, an idempotent notification outbox and action intents. Unknown
evidence cannot clear a trip. Only an explicit operator rearm clears a latch.
Scheduler health and collection health are reported separately.

The only implemented mutation may disable both workers.dev and preview endpoint
flags on one explicitly enrolled standalone Worker. Enforcement needs an exact,
administrator-owned approval manifest, an approved baseline, fresh exact per-resource
evidence and a final inventory read. Routes, custom domains, internal triggers,
protected resources or uncertain inventory block it. Intent precedes mutation;
timeouts reconcile state before retry. A successful write alone is not verification.
Unknown public probes remain partial. Nothing automatically re-enables endpoints.

This cannot enforce a maximum bill or stop all internal invocations/storage charges.
Sampled analytics cannot authorize cutoff. If no suitable production metric and
inventory can be proven, live enforcement stays unavailable. Fake exact data tests
the executor without pretending to establish production eligibility.

Separate read and execution tokens live outside the repository. TLS verification
remains enabled; redirects never forward authorization. Query, response, retry and
run budgets are bounded. No arbitrary commands or mutation plugins exist.

Out of scope: DNS/CDN, Access, subscription/billing changes, unrelated resources,
existing services and backup jobs. Initial production use must be observe-only.
Live install, alert destination and disposable cutoff canary require explicit approval.
Offline tests, Linux scheduler evidence, independent reviews and live checks are
different gates; reports must never substitute one for another.

Original owner-specific requirements are retained outside version control. This
repository contains synthetic examples and generic documentation for reuse.
