# Independent automatic-cutoff security review — 2026-10-27

Final source-review verdict: **no remaining findings in the reviewed scope**.
This is independent agent review evidence, not human merge approval or live
deployment/cutoff authorization.

Scope: accounting, configuration, provider adapter, durable intents/recovery,
runner integration, template CLI, installer arming and current user documentation.
The reviewer inspected source independently and ran targeted/adversarial fixtures.

## Findings and corrections

| Finding | Correction and regression |
| --- | --- |
| Distinct rated row hashes did not prove non-overlapping charges; summing could delete too early | Use the largest validated individual line as an explicitly partial gross charge floor; overlapping $0.60/$0.80 windows remain $0.80 |
| Valid official empty bindings/default Worker exports were rejected | Accept only documented harmless empty/default shapes; unknown and stateful shapes still block |
| Approval omitted guard-period/currency semantics | Digest binds account, currency, billing day and versioned UTC period definition |
| Run-start time could remain valid after real approval expiry | Recheck a monotonic-derived current clock after collection and immediately before mutation |
| Empty/malformed namespace owner could be treated as unrelated | Validate every owner, including later pages; unknown ownership prevents writer construction |

Final recovery recheck covered persisted exact HTTP 401/403 rejection. Authenticated
successful read-back takes precedence; unavailable read-back stays uncertain. A
known rejection with known unchanged provider state is terminal `not_applied` and
requires explicit local rearm. HTTP 503 and transport ambiguity cannot retry writes.

The final reviewer ran 21 action tests and 11 real-client runner integration tests,
all passing. Its earlier independent whole-suite run passed 165 tests with 3 Windows
skips, before the last five regression additions; the lead's Windows and independent
Linux 170-test runs are recorded in [delivery evidence](../automatic-cutoff-evidence.md).

All 33 frozen runtime/test/deploy/example files are listed in the
[LF-normalized manifest](automatic-cutoff-source.sha256). The original Linux-tested
local review manifest SHA-256 is
`f540c9c86584a4ce6c4e8be5bb1f9e5bfe8b3466e62047bb91a34f3bf0b70c87`.
Final staging removed only trailing EOF blank lines from two tests; the reviewer
compared every file against both that manifest and the Linux source archive.
All runtime/deploy/config files are unchanged. The final delivery review manifest
SHA-256 is `25ac07fa90611e0e2d043f15cb8021da0ff0aa3b44bd4f99210086e4c14ad7ed`.
These JSON-manifest hashes identify the local review receipts; the linked public
file lists the corresponding per-file delivery hashes.

Residual limits remain explicit: broad account-level token privilege, no atomic
conditional deletion, concurrent deployment race, delayed/sampled/missing usage,
CPU reserve rather than measured aggregate CPU, no full invoice balance, and no
automatic restore. Only supported stateless Workers are eligible. No live provider
canary or consumer credential was used during review.
