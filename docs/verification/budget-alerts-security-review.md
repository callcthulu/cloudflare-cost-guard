# Independent budget-alert security review — 2026-10-28

Final verdict: **no unresolved actionable findings in the reviewed delta** from
`0689dbb720f3219a87e00411fc685bb6cc585fd9`. This is source review evidence, not
human merge approval, deployment permission or a live cutoff/notification claim.

The independent reviewer inspected accounting/configuration, optional-cutoff
isolation, digest compatibility, contextual events, delivery ordering/migration,
offline policy inspection, installer boundaries, docs and synthetic regressions.
No private consumer file, real credential or provider access was used.

## Findings corrected and rechecked

| Finding | Correction and regression |
| --- | --- |
| Positive percentage could underflow to a zero effective threshold | Exact threshold arithmetic traps inexact/underflow/overflow and rejects nonfinite/nonpositive results; configuration reports a sanitized error |
| Warning crossing was queued but absent from report/exit status | `budget_warnings` reports crossings and exit 4 indicates a warning; collection remains independently unknown and pending/failed delivery has exit-5 precedence |
| Migrated pending cutoff alerts retained routine priority | Schema-5 migration recognizes legacy `cutoff:`/`blocked:` identities while preserving payload, attempts, due time and delivered state |

An implementer also found percentage-display overflow. Unrepresentable display
percentages now become null while the source amount/limit remain available.
Invalid, missing or conflicted context has `value: null` and `quality: unknown`.

Final independent Windows run: **200 tests, 197 passed, 3 platform skips**,
9.704 seconds. Whitespace checks passed. Additional synthetic real-adapter
integration crossed 150 warnings using an unchanged existing cutoff approval:
150 warnings and one confirmed `worker_deleted` result were produced in 0.725
seconds; reopening state and reordering warnings retained exactly 150 warning
events. This is a fixture result, not a production performance guarantee.

Warning-only resources cannot enter budget or legacy action paths. Warning fields
are excluded from the otherwise compatible approval digest; cutoff semantics
remain bound. Notifications happen after action execution, and priority respects
due-time backoff. `show-policy` uses no state/provider/token content. Managed
installation integrity checks remain in place.

The final review manifest covers 38 runtime/test/deploy/example files with
LF-normalized hashes, unchanged after independent testing. Original JSON manifest
SHA-256: `d60890b74781ca03e758448c0823130f1995986ca713efa258937b9a6cb901c7`.
See the [per-file source hashes](budget-alerts-source.sha256) and
[delivery evidence](../budget-alerts-evidence.md).
