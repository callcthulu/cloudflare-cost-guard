# Implementation ledger

Authority: locally retained source requirements and implementation plan (2026-10-26).
User explicitly requested implementation of that plan, bounded agents and independent review.

Ruling: keep original owner-specific handoff and source provenance outside Git; publish only generic requirements. This follows the owner's stronger privacy requirement for eventual public reuse.
Ruling: a new isolated repository and dedicated branch provide isolation; no checkout of the requirements-source repository.
Ruling: the delivered design and implementation plan are the execution brief; no new design approval loop.

| Tasks | Interface review |
| --- | --- |
| 1 and 2 | Freeze dataclasses/config before collection implementation. |
| 1 and 3 | Freeze policy inputs and state contract before orchestration. |
| 2 and 4 | Narrow client action functions; no generic mutation dispatch. |
| 3 and 4 | Persist pending intent before write and reconcile before retry. |
| 1 | Decimal arithmetic and unknown evidence must agree with tests. |
| 2 | Endpoint-specific completeness required; denied is not zero. |
| 3 | Unit verification alone is not Linux lifecycle evidence. |
| 4 | Fake exact data proves executor, not live metric eligibility. |
| 5 | Offline release and live deployment gates remain separate. |

Tasks: foundation complete; collection complete; runtime complete; fake executor complete;
security review complete; public-reuse review complete; final fresh Linux lifecycle
complete; evidence packaged in a private draft PR. All live gates remain pending
authorization and evidence. No main-branch integration or publication performed.

Delegation: one bounded foundation/policy specialist, one collector specialist,
one disposable-Linux/deployment specialist; foundation specialist continued with
the narrow executor. Lead integrated state/runner/notifications and regression fixes.
Separate reviewers examined security/correctness and public reuse/privacy/docs.
