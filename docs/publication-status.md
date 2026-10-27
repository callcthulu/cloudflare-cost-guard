# Public repository settings

Publication is being prepared on 2026-10-27. The repository is still private;
the settings below are not yet active. This record will be updated after GitHub
accepts the visibility change and the settings have been read back.

The [pre-publication security review](verification/public-launch-review.md) found
no blocking findings in the accessible history, repository content and launch changes.
It records the scope and limits of that review.

| Control | Target |
| --- | --- |
| Default branch | `main`; pull requests required, no force pushes or deletion |
| Required checks | `offline-linux-py311`, `offline-linux-py314`, `offline-windows-py314` from GitHub Actions |
| Reviews | One approving code-owner review; an owner-only PR exception is separate from the non-bypassable checks |
| Actions | Read-only token, SHA-pinned actions, approval for all outside fork contributors |
| Security reports | GitHub private vulnerability reporting |
| Secret detection | Secret scanning and push protection |
| Ongoing analysis | CodeQL default setup for Python; Dependabot for Actions |
| Community features | Issues enabled; Wiki and Pages disabled |

The [governance policy](governance.md) describes the rules and the owner exception.
[Contributing](../CONTRIBUTING.md) explains the review process;
[SECURITY](../SECURITY.md) gives the private reporting route.

The reviewed runtime pin remains
`a00bedfca4fa89fbbfb4be4a49218257a0cd3caf`. Publication changes repository access
and contribution controls. It does not deploy the application or enable a cutoff.
