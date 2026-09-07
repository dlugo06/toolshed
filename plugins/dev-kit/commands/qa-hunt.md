---
name: qa-hunt
description: Run adversarial QA bug hunting on the codebase.
---

Run adversarial QA bug hunting on the codebase.

Launch the **qa-bug-hunter** agent to analyze test coverage gaps, probe edge cases, write targeted test cases, and report bugs with reproduction steps.

## Steps

1. Launch the `qa-bug-hunter` agent (subagent_type: "dev-kit:qa-bug-hunter") in the background
2. The agent will map coverage, write adversarial tests, run them, and write findings to `.dev/QA_REPORT.md`
3. Report completion to the user with a brief summary: bugs found, tests written, coverage change
