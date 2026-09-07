---
name: next
description: Use when the user asks "what's next", "pick a task", "what should we work on", or wants the orchestrator to select one unit of work across all projects and run its next transition
---

# Orchestrator: next

1. Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md`.
2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" --git`.
3. Select one unit using §Selecting work. State `Selected: <project>/<id>` and the reason in one line before doing anything.
4. If the selected unit is at `idea`, the transition is interactive (brainstorm, then writing-plans). Run it in this session. Do not delegate it.
5. Otherwise run exactly one transition from §Stage machine by invoking the named skill or agent. For `evaluated`, choose the ship tier per §Ship tier and say why.
6. Record the result on the item (`stage`, `branch`, `pr`, `updated`, `blocked_reason` or its removal) and append one line to the phase progress file.
7. Print the report in §Report shape and stop. One transition per invocation.

If nothing is selectable, say why (all deferred, all blocked, no dispositions yet) and point to `/orchestrator:triage`.
