# Launch procedure

This is the source-publication procedure. [Publication status](publication-status.md)
records what actually happened; this document grants no deployment, release or
messaging permission.

## Before visibility changes

Review the selected commit, tests, installation instructions and MIT attribution.
Complete the [publication checklist](publication.md), including all publishable
history and GitHub conversations/attachments. Resolve independent review findings.
Private deployment files, original handoffs and outreach working notes stay outside Git.

## Publication session

Apply and read back [governance](governance.md), enable ordinary Issues and private
vulnerability reporting, inspect read-only CI and fork approval settings, and
verify anonymous cloning and public links. Record exact settings and unresolved
behavior checks in [publication status](publication-status.md). A versioned release
or external announcement is a separate decision.

## Describe the project accurately

Use the same opening in README and repository About:

> Self-hosted Cloudflare usage and subscription monitoring, alerts, and optional
> cutoff for approved stateless Workers. Observe by default. Not a spending cap.

Approximate recent Workers requests, subscription inventory and available rated
charges are separate signals. Missing evidence stays unknown. Optional cutoff is
source-tested for its narrow scope; a live provider cutoff remains an unverified
gate. Do not describe it as a security-audited product. Check Cloudflare's
[native budget alerts](https://developers.cloudflare.com/billing/manage/budget-alerts/)
alongside this utility; no new paid plan is required by the project.

If outreach is later authorized, check the community's current rules, disclose
authorship and link only where the tool answers the actual question. Do not claim
it would have prevented someone's bill or request credentials, stars or upvotes.
Research and draft text do not authorize posting or scheduling.

## Sharing candidate

The [synthetic demo](../examples/monitoring_demo.py) is credential-free and exercises
the real watcher with temporary state and simulated delivery. It is not a live
provider or notification demonstration. [Prerelease notes](releases/v0.1.0-alpha.1.md)
are prepared for a draft GitHub prerelease; preparing a draft does not authorize
publishing it or announcing it externally. Keep personalized post drafts and
editorial source documents outside the repository.
