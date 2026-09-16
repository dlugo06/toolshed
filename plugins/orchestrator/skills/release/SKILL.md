---
name: release
description: Use when the owner wants the open pull requests from autonomous runs reviewed and organised for merging ("review the PRs", "what can I merge", "batch the PRs", "rollout plan", "act as release coordinator"), or asks how the mind's proposal PRs fared after they merged them
---

# Orchestrator: release

The merge is the owner's; everything before it is this skill's. It audits every open PR a run produced, verifies the suites fresh, orders the merges, writes the owner's manual checks, and reads what the owner kept of the mind's last proposals. It never merges, never sets `passes`, never resolves a thread.

Read `${CLAUDE_PLUGIN_ROOT}/reference/release.md` first; it holds the audit checklist, the batching rules, the report template and the proposal-audit classes. Script: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/release.py"`.

1. **Inventory.** From the project's default branch, clean and fast-forwarded (`git status --short` empty, `git fetch origin`). Run `release.py prs --project-dir <dir>` and read the whole output: item, tier, surfaces, evidence flags, owner steps, rejected findings, overlaps, first-cut batches. Then read each PR body once with `gh pr view <n>` and the progress-file lines for its item.
2. **Stage audit.** For each PR, fill the stage table in §Stage audit of the reference from the evidence flags, the progress lines and the PR reviews. A stage with no artifact is *skipped*, not *ran*; a stage the owner waived is *waived*. List every deviation from the tier table with the rule it deviates from. Never call a PR mergeable while a stage it needs shows *skipped*.
3. **Verify fresh.** One scratch worktree per PR at its head commit, the suites the surfaces require, counts recorded at the commit hash. Then build the integration branch for each batch in the main checkout (`test/batch-<letter>-<date>` from `origin/<default>`, merging the PRs in the batch order, conflicts resolved as §Conflicts says) and run the full suites once on each. The zip-key tests that need `.env` run from the main checkout only.
4. **Batch.** Apply §Batching to the first cut: docs-only first, one deploy surface per batch, a PR with owner pre-merge steps alone and last, dependencies before dependents, the register renumbered once per batch.
5. **Manual checks.** Per batch, one checklist from the items' `steps_to_verify`, the PR bodies' unchecked boxes, and the Sentry issues the items name, written as the owner would run them on the phone and in Sentry. Owner pre-merge steps (secrets, `.env.example`, dashboard registrations) are a separate list at the top.
6. **Mind.** Run `release.py proposals --repo "$MIND_HOME" --since <last release date>`. Read every dropped note with `git show`. Classify each drop under §Proposal audit and say which class it is; a class the reference does not name is a new one. Update the drafting rule in `reference/orchestrator.md` §Consult the mind when the audit shows a class it does not exclude yet (that is a plugin change: version bump, CHANGELOG, READMEs, PR). List the open proposals for the owner.
7. **Write and open.** Write `.dev/PR_ROLLOUT_<date>.md` in the project with the sections of §Report. Push each integration branch and open its rollup PR (`gh pr create --body-file`, title `Batch <letter> rollup: <items>`, body = that batch's checklist and conflict notes, "merge with a merge commit, never squash"). Return the checkout to the default branch. Report per §Report shape and stop.

Rejected reviewer findings are listed for the owner to eyeball, never re-litigated here. A PR whose stage audit fails goes to `/orchestrator:advance` after the report, not into a batch.
