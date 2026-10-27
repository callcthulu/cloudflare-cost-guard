# Independent compatibility documentation review — 2026-10-27

Scope: read-only review of the branch diff against `main`, README, compatibility delivery, getting-started/configuration/capabilities/runbook/troubleshooting/CHANGELOG, historical handoff context and synthetic offline evidence. No consumer directory, private consumer report, credential, installation, provider request or notification was accessed/executed.

## Actionable finding

- P2 — `docs/runbook.md:144`: the compatibility-delivery upgrade path points here, but the copyable install command still runs `/root/cfguard-source/deploy/install.py` from the original install. A code-upgrade reader is told to create a new root-controlled source directory, while the required command substitution appears after the block. Copying the block can successfully reinstall the old code and pass validation/probe. Make the upgrade source path an explicit required variable or separate exact-pin upgrade block before the installer command; make an unset/unreviewed path fail closed.

## Passed review points

- Getting-started removed the historical fixed SHA, requires a reviewed 40-character delivery SHA, fetches/checks out that exact revision, verifies HEAD and archives the same variable. It stops on missing SHA/fetch/switch mismatch rather than silently selecting a branch.
- Coverage documentation correctly distinguishes `covered:false` / unavailable from unknown metadata and from a zero balance. Missing anchors cannot verify the period; estimates, rated rows and commitments remain separate.
- Cache expiry claims agree with the inspected implementation: original fetch time is retained; old/stale/future formats, billing-day changes, rollover and known subscription transitions cannot preserve verified proof.
- No new token grants, paid plan, state reset, cache deletion or lifecycle/live verification is required or claimed. Earlier lifecycle and handoff evidence are explicitly historical.
- The changed documentation and currently present synthetic Windows/Linux evidence contain no apparent private consumer identity, host path, raw consumer report, credential or secret URL. Rootfs URLs, generic Unix paths and Git commit/manifest hashes are public/generic provenance.
- Windows log reports 107 tests, two skips; current Linux log/provenance report 107 tests, zero skips. These were inspected as evidence, not rerun by this reviewer.

## Delivery completion checks

At review time, `docs/verification/compatibility-review.md` was still being prepared and the external exact-SHA delivery package had not yet been produced. These need a final existence/link/checksum check after assembly. This review does not independently certify the runtime or Linux execution provenance.

## Final recheck

The P2 finding above is resolved in the working tree: the runbook now requires a reviewed `CFGUARD_SOURCE` placeholder, checks its installer exists, and passes the quoted path as a positional argument to the scoped installer shell. The instruction to use the new source directory appears before the command block.

No remaining blocking documentation/usability/privacy findings in the reviewed scope. The Linux log, provenance JSON and source manifest now exist. All 23 recorded source hashes match the current repository files; the manifest SHA256 matches the provenance record. `git diff --check` passed. The final independent security-review document and external exact-SHA package remain assembly checks for the lead reviewer, rather than evidence this reviewer has seen.
