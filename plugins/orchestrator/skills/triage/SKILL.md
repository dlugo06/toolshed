---
name: triage
description: Use when a project's open PRD items need a keep/fold/defer/drop decision against its current priority, when the user says "triage", "clean up the backlog", or when `next` finds items without a disposition
---

# Orchestrator: triage

Argument: a project directory name. Without one, triage the project the session was started in (the current working directory must be under `TOOLSHED_PROJECTS_ROOT`).

1. Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` §Triage and §Selecting work.
2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" --project <name>`. If it reports `DUPLICATE IDS`, propose a renumbering first and stop; nothing else is reliable until the owner confirms it.
3. Find the project's priority axis: its `CLAUDE.md`, its discussions or roadmap file, the most recent design doc. Quote it in one line at the top of the proposal.
4. For every open item propose `keep`, `fold: <target>`, `defer`, or `drop` with a one-line rationale. Also propose stage corrections for items whose real state differs from the recorded one (a merged PR, an existing branch).
5. Write `<project>/.dev/orchestrator-triage.md` (create `.dev/` if missing; it should be gitignored). Do not touch the phase files.
6. Report the counts per disposition and the open questions the owner must answer. Stop.

When the owner confirms, apply the dispositions and stage corrections in one edit per phase file, set `updated`, and append one line to each phase progress file. Never set `passes`.
