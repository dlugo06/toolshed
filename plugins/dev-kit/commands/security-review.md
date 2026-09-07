---
name: security-review
description: Run a security review of the codebase.
---

Run a security review of the codebase.

Optional argument: PR number (e.g., `/dev-kit:security-review 15`) — posts findings to the PR instead of a standalone report.

Launch the **security-reviewer** agent to scan for vulnerabilities, check secret handling, validate inputs, and audit dependencies.

## Steps

1. If a PR number is provided, pass it to the agent prompt: "Review PR #N for security issues and post findings as a PR review comment"
2. If no PR number, pass: "Run a standalone security review and write findings to .dev/SECURITY_REVIEW.md"
3. Launch the `security-reviewer` agent (subagent_type: "dev-kit:security-reviewer") in the background
4. Report completion to the user with a brief summary of key findings
