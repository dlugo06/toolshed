---
name: spec-check
description: Verify that code on the current branch fully implements a design spec.
---

Verify that code on the current branch fully implements a design spec.

Optional argument: path to spec file (e.g., `/dev-kit:spec-check docs/superpowers/specs/2026-04-01-phase2e-pdf-parsing-design.md`). If omitted, the agent auto-detects from the branch name.

## Steps

1. Launch the `spec-checker` agent (subagent_type: "dev-kit:spec-checker") in the foreground
   - If a spec path argument was provided, pass it to the agent
   - Otherwise, let the agent auto-detect the spec from the branch name
2. The agent reads the spec line-by-line, extracts every concrete requirement, and cross-checks against changed files
3. Present the verdict to the user:
   - **PASS** → All requirements implemented. Ready to `/dev-kit:ship`.
   - **FAIL** → Show the MISSING/PARTIAL list. Ask the user whether to fix, skip, or mark the spec as outdated.
