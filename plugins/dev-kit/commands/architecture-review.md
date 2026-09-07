---
name: architecture-review
description: Run a holistic architecture review of the codebase.
---

Run a holistic architecture review of the codebase.

Launch the **code-architect** agent to analyze the system design, trace data flow, identify scaling bottlenecks, and generate an architecture assessment aligned with the business roadmap.

## Steps

1. Launch the `code-architect` agent (subagent_type: "dev-kit:code-architect") in the background
2. The agent will read project specs, explore all source modules, and write its findings to `.dev/ARCHITECTURE_REVIEW.md`
3. Report completion to the user with a brief summary of key findings
