## Problem and resulting behavior

Describe the concrete problem, scope and resulting behavior. Link an ordinary issue
if applicable. Security reports must follow the [security policy](https://github.com/callcthulu/cloudflare-cost-guard/security/policy) before a
public PR is opened.

## Validation and limits

Record commands and actual results, including meaningful regression/failure-path
checks for changed behavior. Distinguish offline, disposable Linux and live evidence.
State what remains unverified. Documentation-only changes can use link/diff checks.

## Review checklist

- [ ] Dedicated branch; change kept small enough to review.
- [ ] README and relevant linked documentation match the change.
- [ ] Diff and introduced history reviewed for secrets/private data; fixtures synthetic.
- [ ] No deployment configuration, identifiers, tokens, state, raw logs or exports added.
- [ ] Observe zero-writes, unknown evidence, separate ledgers and enforcement gates preserved.
- [ ] Workflow changes reviewed for read-only permissions, pinned actions and fork safety.
- [ ] No credentials, private-data uploads, paid runners or automatic deployment added.
- [ ] Maintainer/independent review recorded; agent review is evidence, not GitHub approval.
- [ ] I can license this contribution under the existing MIT license.
