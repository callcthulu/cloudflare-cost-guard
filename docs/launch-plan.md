# Public launch plan

Prepared 2026-10-26. The repository is still **private**. Implementation PR #1 and
documentation PR #2 are integrated into `main`; their reviewed commits remain in
its ancestry. This is a launch plan, not a visibility change, release or deployment.

## Current state and launch position

- Integrated code/docs: 76 offline tests pass, with two Windows platform skips.
  The implementation and installer are unchanged from the reviewed source.
- Historical Linux/fake-provider evidence is in [evidence](evidence.md). No live
  provider, production installation or verified cutoff is inferred from integration.
- `main` is currently unprotected. A read-only ruleset listing returned GitHub's
  private-plan HTTP 403. The [public ruleset](examples/github-ruleset.public.json)
  is prepared and locally checked, **not imported or enforced**.
- Issues remain disabled. No Actions workflow exists, although the repository's
  Actions setting currently permits actions. Default workflow-token access is read,
  with workflow PR approval disabled. Settings need review before launch.

Describe the project as a self-hosted, observe-first usage/subscription monitor
with explicit unknown data. It is not a hard budget cap, a verified cutoff tool,
an audited security product or a guarantee of avoiding bills.

Cloudflare already provides [native budget alerts](https://developers.cloudflare.com/billing/manage/budget-alerts/)
for eligible Pay-as-you-go accounts. They notify rather than cap usage; the
[documented rollout](https://developers.cloudflare.com/changelog/post/2026-06-15-budget-alerts-default-on/)
describes daily prior-day processing and excludes recurring subscription fees.
Check existing native controls first; do not buy a plan for this project. This
utility offers an additional local view of approximate recent Workers requests,
subscription inventory and available rated rows, not a replacement for the bill.
Recheck provider features when launching: a new native feature can change the
project's useful scope and the accuracy of a community reply.

## Stage 1: final private review

Select the exact integrated commit. Recheck tests, README/install instructions,
MIT attribution and all publishable refs/history/archives. Review GitHub issues,
PRs, comments, attachments and any private security reports before making them
visible. Original private handoffs, site configuration and outreach working notes
stay outside Git. A clean default branch is not a complete disclosure check.

Use [the publication checklist](publication.md) and [maintainer process](maintaining.md).
No stable version/tag exists yet; keep the launch labelled pre-release unless a
separate release is approved. Personal deployment evidence remains private and
cannot certify every user's account. Preserve the initial handoff as a snapshot.

## Stage 2: owner-approved visibility and protection

After explicit owner approval, perform visibility and protection setup in one
controlled session; do not announce the repository before these checks:

1. Change only this repository's visibility to public at the selected revision.
2. Import [the solo-maintainer ruleset](examples/github-ruleset.public.json), read
   it back and inspect its application to `main`. Require PRs/resolved threads,
   block force pushes/deletion, allow merge commits, and keep bypass empty.
   See [governance](governance.md) for exact settings and the zero-approval tradeoff.
   Do not claim tested rejection from local JSON validation; observe the next
   ordinary PR path without force-pushing/deleting the default branch as a test.
3. Enable and verify GitHub private vulnerability reporting, its public form and
   maintainer notifications. Enable Issues/templates and reported-content moderation
   if accepting public contributions. Verify actual links on the default branch.
4. Review GitHub's automatically available public [secret scanning](https://docs.github.com/en/code-security/concepts/secret-security/secret-scanning)
   and any eligible push-protection setting. Check actual availability/read-back;
   do not buy a security product or treat scanning as proof no secret was exposed.
5. Keep Actions disabled until a workflow/runner policy is separately approved;
   no workflows or required CI checks are introduced by this plan. Future CI must
   use read-only permissions, no provider secrets/deployment and reviewed fork
   execution. Never require a check that has not been implemented and observed.
6. Verify public cloning, license, install instructions, support/security links,
   saved rules and the next benign reviewed PR. Record remaining verification
   separately from configured settings. No live Cloudflare canary is included.

GitHub Free public branch rulesets are supported according to
[current GitHub documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets).
The initial solo profile does not provide independent human approval enforcement.
Upgrade to one approval only when a real eligible second reviewer is available;
agent review cannot approve the owner's GitHub PR on another person's behalf.

## Stage 3: small, contextual launch

Publish a truthful pre-release description: why the utility exists, exact coverage,
setup cost/host requirements, existing native alerts and what remains unavailable.
Offer a focused contribution path and feedback on data quality/installation, without
requesting credentials, stars, upvotes or access to another person's infrastructure.

Recheck community rules and the actual thread on posting day. Choose one relevant
active conversation first, disclose authorship, answer its question and link only
if it adds value. Repeated old-thread link drops are not a launch strategy. Do not
claim the tool prevents someone else's reported bill or solves their requested
hard limiter. External draft replies and the outreach shortlist remain private.

Hacker News [guidelines](https://news.ycombinator.com/newsguidelines.html) disallow
generated/AI-edited comments and automated posting. Treat HN research as context;
do not post an agent's draft there. Other communities need their own rules checked.

No post, message, scheduled automation, public release or setting mutation is made
by this document. Publication may happen at the owner's chosen time; no tomorrow
reminder or automatic launch is scheduled.
