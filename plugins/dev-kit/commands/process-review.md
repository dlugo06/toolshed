---
name: process-review
description: Process review comments on a PR: read each comment, fix or reject with reasoning.
---

Process review comments on a PR: read each comment, fix or reject with reasoning.

Argument: PR number (e.g., `/dev-kit:process-review 48`)

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

## **STOP. Wait for user approval before proceeding. Do NOT apply any fixes until the user confirms.**

### 5. Apply Fixes

After user approval, write the approved "fix" rows to a brief file and dispatch **one** implementer subagent (`model: "sonnet"`) with that brief. It applies every fix, runs the covering tests, and commits. Do not dispatch one agent per finding and do not dispatch a re-review agent; the PR reviewers already ran, and the next review of this diff is the human's at merge.

For each comment classified as "fix", the brief states:
- Make the code change
- Keep changes minimal and scoped to what the reviewer requested
- Do not refactor surrounding code

### 6. Run Tests

Before committing, verify all tests pass (TDD enforcement):
```bash
pytest
```

If any test fails, fix it before proceeding. Do not commit with failing tests.

### 7. Commit Changes

Stage and commit all fixes in a single commit using conventional commit format:
```bash
git add <changed files>
git commit -m "fix: address PR #$ARGUMENTS review feedback

- <brief description of fix 1>
- <brief description of fix 2>
..."
git push
```

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

- **Before starting**, invoke `superpowers:receiving-code-review` -- this enforces technical rigor when evaluating feedback, preventing blind agreement or blind rejection
- **NEVER auto-approve** -- always present the decision table and STOP until the user explicitly approves
- **Never silently skip a comment** -- every unresolved thread gets a reply; do not resolve threads (replies are enough, resolving is API noise)
- **One fix subagent, no re-review subagent** -- the fix wave is a single Sonnet dispatch; verification is the test suite plus the human merge
- **Always wait for user approval** of the decision table before making changes
- **Always run `pytest` before committing** -- this project enforces TDD strictly
- **Use conventional commits** -- prefix with `fix:`, not freeform messages
