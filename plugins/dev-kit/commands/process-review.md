---
name: process-review
description: Process review comments on a PR: read each comment, fix or reject with reasoning.
---

Process review comments on a PR: read each comment, fix or reject with reasoning.

Arguments: PR number, then optional flags (e.g., `/dev-kit:process-review 48`, `/dev-kit:process-review 48 --autonomous --no-replies`).

- `--autonomous`: the caller is the orchestrator or the owner has said the run is unattended. The decision table is still produced, but instead of stopping for approval it is ruled on from the project's stored preferences (auto-memory, `CLAUDE.md`, prior decision tables) and **posted as a PR comment** titled `process-review decision table (<date>)`; that comment is the audit record the owner reads later. Without the flag, step 4's STOP applies.
- `--no-replies`: skip the per-thread replies in step 7 (the owner reads the table instead). The table is never skipped.

## Steps

### 1. Identify Repository

Detect the current repo from the working directory:
```bash
gh repo view --json nameWithOwner --jq '.nameWithOwner'
```
Store as `$REPO` for all subsequent commands. Parse into `$OWNER` and `$REPO_NAME`.

### 2. Gather Context

Before evaluating comments, understand what the PR does:

```bash
gh pr view $ARGUMENTS --json title,body,headRefName,baseRefName,files
gh pr diff $ARGUMENTS
```

Checkout the PR branch so you can read and edit files directly:
```bash
gh pr checkout $ARGUMENTS
```

### 3. Fetch All Review Feedback

Fetch **all** forms of review feedback — inline threads, review body text, and regular PR comments:

```bash
gh api graphql -f query='
query($repo: String!, $owner: String!, $pr: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100) {
        nodes {
          id
          isResolved
          isOutdated
          comments(first: 10) {
            nodes {
              id
              databaseId
              body
              path
              line
              author { login }
              createdAt
            }
          }
        }
      }
      reviews(first: 50) {
        nodes {
          id
          databaseId
          state
          body
          author { login }
          createdAt
        }
      }
      comments(first: 50) {
        nodes {
          id
          databaseId
          body
          author { login }
          createdAt
        }
      }
    }
  }
}' -F owner="$OWNER" -F repo="$REPO_NAME" -F pr=$ARGUMENTS
```

Process all three response sections:
- **reviewThreads**: Inline comments on specific lines. Filter to **unresolved** only.
- **reviews**: Review body text submitted alongside inline comments (e.g., "Overall this looks good but..."). Filter to non-empty `body`.
- **comments**: Regular PR comments not attached to a review.

**IMPORTANT**: Do NOT filter by author. The pr-reviewer agent and other AI reviewers post under the PR author's GitHub account. Treat ALL unresolved threads as actionable. PRAISE-only threads can be acknowledged and resolved without code changes.

### 4. Evaluate Each Comment

For each piece of feedback:

1. **Read the commented file and surrounding code** to understand the full context
2. **Classify the comment**:
   - **Fix** -- the reviewer identified a real issue or improvement worth making
   - **Reject** -- the comment is based on a misunderstanding, is out of scope, or the current approach is intentionally correct
   - **Already addressed** -- the issue was fixed in a subsequent commit
   - **Praise** -- positive feedback, no action needed (resolve without reply)
3. **Document your reasoning** before making any changes

Present a summary table to the user BEFORE taking action:

```
| # | Source | File:Line | Reviewer | Comment (truncated) | Decision | Reasoning |
|---|--------|-----------|----------|---------------------|----------|-----------|
| 1 | thread | src/foo.py:87 | @copilot | Missing validation... | Fix | Valid -- no input check |
| 2 | thread | src/bar.py:15 | @copilot | Should use async... | Reject | Current pattern is intentional |
| 3 | review body | — | @reviewer | Overall approach... | Fix | Valid architectural concern |
```

## **STOP. Wait for user approval before proceeding. Do NOT apply any fixes until the user confirms.** (With `--autonomous`: rule on every row from stored preferences, post the table on the PR, and continue. A row you cannot rule on from the record is `Reject (needs owner)` with the question in the reasoning column, never a silent fix.)

### 5. Apply Fixes

After approval, write the approved "fix" rows to a brief file (under 150 words plus the rows; name the report paths, never paste the reviews) and dispatch **one** implementer subagent (`model: "sonnet"`) whose prompt is a single line pointing at that brief file. Post the decision table with `gh pr comment <n> --body-file <scratch>/decision-table.md`, never an inline heredoc (project hooks deny command text that names guarded functions). Do not dispatch one agent per finding and do not dispatch a re-review agent; the PR reviewers already ran, and the next review of this diff is the human's at merge.

The brief states, for the whole wave:
- Make each code change with a RED test first; keep it minimal and scoped to what the reviewer requested; do not refactor surrounding code
- **Commit after each fix** (`fix: <finding> (PR #N review)`), so a killed agent leaves committed work; a fix wave once lost ~300k tokens of uncommitted work to a rate-limit kill
- Run the covering tests per fix and the full suites **once**, before the last commit; report the counts
- Do no verification the brief did not ask for (no Docker builds, no extra suites, no repo-wide reads)
- Read `gh pr diff` once and the `.dev` review reports; read full files only for the functions being fixed

### 6. Verify

Read the fixer's report: it must name the full-suite counts at the final commit. If it does, do not re-run the suites here. If the report is missing the counts (the agent was killed or skipped them), run them once:
```bash
pytest
```

If any test fails, fix it before proceeding. Do not push with failing tests.

### 7. Push and Reply

The fixer already committed per fix. Push:
```bash
git push
```

Then reply in each unresolved thread with the fix or the technical reason for rejecting (skipped with `--no-replies`).

### 8. Summary

Output a final summary:
```
PR #XX review comments processed:
- Fixed: N
- Rejected: N
- Praise resolved: N
- Already resolved: N (skipped)
- Tests: all passing
```

## Rules

- **Before starting** in an interactive run, invoke `superpowers:receiving-code-review` -- this enforces technical rigor when evaluating feedback, preventing blind agreement or blind rejection. In an orchestrator run (`--autonomous`) it is not invoked; the orchestrator reference names the only skills that run inside a transition
- **A fix-tier PR usually has one review body and no inline threads.** When the thread query returns none, the decision table comment is the whole record; step 7's per-thread replies have nothing to do and are skipped without `--no-replies`
- **Tiny waves stay in the caller.** When every "Fix" row is test-only or a string/log-field change, one file, under twenty lines in total, the caller applies them directly with the covering test run once (the orchestrator reference's inline micro-fix rule) instead of dispatching the fixer; a fixer dispatch for one flipped test cost 81k tokens
- **Rulings already made are not re-opened.** A finding that re-litigates a trade-off recorded in the plan's Rulings section or the spec is `Reject (decided)` citing that section; a follow-up note goes on the PRD item when the reviewer's concern deserves later work
- **NEVER auto-approve** -- present the decision table and STOP until the user explicitly approves, unless `--autonomous` was passed, in which case the table is posted on the PR as the record and rulings come from stored preferences only
- **Never silently skip a comment** -- every finding appears in the table with a decision; threads get replies unless `--no-replies`; do not resolve threads (replies are enough, resolving is API noise)
- **One fix subagent, no re-review subagent** -- the fix wave is a single Sonnet dispatch that commits per fix; verification is the test suite once plus the human merge
- **Suites run once** -- in the fixer, at its final commit; the caller re-runs only when the report lacks the counts
- **Reviewer accuracy is checked, not assumed** -- a finding that contradicts the code (a predicate the reviewer misread, an exception class that cannot reach the site) is a Reject with the file:line that shows why; a finding that is right about a pre-existing defect outside the PR's scope is a Reject (scope) that is written to the project's follow-up notes, never dropped
- **Use conventional commits** -- prefix with `fix:`, not freeform messages
