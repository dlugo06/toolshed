---
name: test-review-gate
enabled: true
event: bash
pattern: gh pr create
---

**Shipping without test review.** Check if a test quality review exists for this branch:

1. Get the current branch name: `git branch --show-current`
2. Check if `.dev/test-review-<branch>.md` exists
3. If it does NOT exist, warn the user:

> "No test quality review found for this branch. Consider running `/dev-kit:review-tests` before shipping to catch weak assertions and missing edge cases. Type 'skip' to proceed anyway."

If the file exists, proceed silently — do not interrupt the ship flow.
