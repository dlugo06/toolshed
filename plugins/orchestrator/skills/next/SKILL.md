---
name: next
description: Use when the user asks "what's next", "pick a task", "what should we work on", or wants the orchestrator to select one unit of work across all projects and run its next transition
---

# Orchestrator: next

1. Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md`.
2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" --git`.
3. Select one unit using §Selecting work. State `Selected: <project>/<id>` and the reason in one line before doing anything.
4. If the selected unit is at `idea`, choose its tier per §Pipeline tiers, record `tier` on the item, and run the spec transition in this session. Do not delegate it. Brainstorm only when the cause is unknown.
5. Otherwise run exactly one transition from §Stage machine for the item's tier, invoking only the skill or agent the table names, on the model §Models names. Nothing else is invoked during the transition.
6. Count every `Agent` dispatch the transition made and add it to the item's `agents`. If the count reaches the tier's cap, stop and report; never raise the cap yourself.
7. Record the result on the item (`stage`, `tier`, `agents`, `branch`, `pr`, `updated`, `blocked_reason` or its removal) and append one line to the phase progress file, including any ruling you made.
8. Print the report in §Report shape and stop. One transition per invocation.

If nothing is selectable, say why (all deferred, all blocked, no dispositions yet) and point to `/orchestrator:triage`.
