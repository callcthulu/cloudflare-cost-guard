# Independent compatibility security and correctness review

Date: 2026-10-27. Base: `770050f889a775012d2ae4f3f046845820c683a0`.
Reviewed the dedicated compatibility working tree before commit, including runtime, tests, documentation and sanitized delivery evidence.

**Result: no unresolved actionable findings in the reviewed change.** Two P2 findings were reproduced during review, corrected by the implementer, and independently rechecked as described below. This is an offline source review, not deployment authorization or proof of live provider behavior.

## Scope and preserved boundaries

- Singular zone subscription object endpoint and plural account list are separated correctly. Account completeness checks remain strict; malformed required fields do not become free plans.
- Owning account plus verified provider ID reconciles one commitment across endpoint appearances. Both appearances and actual zone attribution remain in private snapshots. Distinct IDs stay distinct; amount, currency, plan, canonical identity, declared scope and multi-zone conflicts invalidate totals.
- V1 info explicitly distinguishes covered, unavailable and unknown. Empty/invalid metadata does not prove a billing anchor; positive rated rows remain separate alert evidence.
- Cache restoration retains coverage metadata and invalidates period proof on stale/future fetches, old cache format, billing-day changes, billing rollover and known metadata start/end transitions.
- Account-list completeness is not all-product inventory. Rated charges, estimates and commitments stay separate. Existing unknown latches, observe zero-write behavior and executor credential boundary remain intact.
- No V2 fallback, pricing inference, permission expansion, credential changes or enforcement expansion was introduced.

## Findings and closure evidence

### Closed P2: absent billing proof was accepted by policy

The initial `cfguard/policy.py` change treated absent billing-period and account-coverage flags as success when configuration asserted verification. A synthetic complete zero rated row with no info proof produced `healthy / rated_zero / 0`.

The corrected policy requires explicit `billing_period=verified_config`, `billing_account_coverage=covered` and `billing_info=parsed`. Independent rerun of the original reproduction now yields `unknown / None / rated_unknown`. Regression coverage exercises absent and invalid proof for both rated totals and estimates.

### Closed P2: cached period proof outlived a known metadata transition

The initial cache stored summarized proof without the underlying subscription validity boundary. An active anchor ending at 12:01, fetched at 12:00, still yielded verified period coverage from cache at 12:05.

The collector now bounds `billing_period_valid_until` by billing-period end, earliest active subscription end and earliest future subscription start. Restoration validates the explicit UTC bound, fetch age, configuration and covered/parsed metadata, and removes expired proof. Independent collector-to-cache reproductions for both an active end and a future conflicting start at +1 minute now emit +1 minute validity and restore `unverified` at +5 minutes. Invalid, missing and out-of-period validity are also tested. The regression-red record was inspected and showed failures before these fixes.

## Verification

- Independent final run: `python -B -m unittest discover -s tests -q` — 107 tests run, 105 passed, 2 Windows/platform skips; no failures or errors.
- `git diff --check` — clean.
- Linux evidence inspected: 107 tests run, all passed, zero skips, Python 3.12.3 in disposable Ubuntu 24.04. The recorded execution used an unprivileged user and an isolated network namespace with loopback only. This reviewer inspected evidence rather than performing a second Linux execution.
- Independently recalculated all 23 source hashes in `compatibility-source.sha256`: no mismatch against the current runtime/deploy/test files. Its checksum matches the Linux provenance JSON.
- Inspected README, changelog, capabilities, configuration, getting-started, runbook, troubleshooting and compatibility-delivery documentation. Endpoint, coverage, proof-expiry, upgrade and operational limitations agree with the implementation. Upgrade instructions explicitly select the new pinned source directory and preserve state/latches.
- Local Markdown references were checked. The review-document link is intentionally fulfilled when this report is copied to `docs/verification/compatibility-review.md`; other checked local targets exist.
- Privacy review covered the changed tracked content and all newly added delivery/test files. No consumer configuration, private resource identifiers, personal filesystem paths, real token contents or raw consumer payloads were found. A bearer-token pattern matched only the existing clearly synthetic fixture assertion. Raw failing traceback logs remain outside the tracked delivery.
- No commits existed above the stated base at this review checkpoint. Final commit identity and delivery-package checksums must be recorded by the integrating agent after commit; this review does not invent them.

## Limits

No consumer private tree, credential contents, authenticated Cloudflare endpoint, deployment target or real notification was accessed. The installer/systemd lifecycle was unchanged and was not rerun by this review. Linux offline tests and existing historical lifecycle evidence do not establish live account coverage, notification receipt, production success or enforcement readiness. Real enforcement remains unavailable and no hard spending cap is claimed.

## Final assembly recheck

After the assembly-only trailing-blank-line cleanup in `tests/test_compatibility.py`, independently recalculated the final 23-file Linux source manifest against the current files: zero mismatches. Final manifest SHA-256 is `5948252db415ae78b1f41b2415c0344d1383e457ea779194580ff34faf88f6a4`, matching the supplied final Linux evidence identity. `git diff --cached --check` exits 0. The intended public review-document target now exists. This assembly recheck adds no new runtime or semantic findings; prior finding closures remain valid. No redundant full-suite execution was performed during this assembly-only review.
