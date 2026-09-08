---
name: advance
description: Use when the user names a specific PRD item to move ("advance P5-003", "push <project>/P2-010 forward") or gives a new intent in quotes to turn into a PRD item and spec
---

# Orchestrator: advance

Argument forms:

- `<project>/<id>`: advance that item one transition.
- `<id>`: same, in the project the session was started in.
- `"<intent>"`: create a new item at `idea` in the current project's newest phase file (next free id in that phase's numbering), then run the `idea -> specced` transition interactively.

1. Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md`.
2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" --project <name>` and locate the item. If its project reports `DUPLICATE IDS`, stop and report.
3. If the item is skipped by disposition or blocked by an open dependency, say so and stop. Do not override a disposition.
4. If the item is at `idea`, choose its tier per §Pipeline tiers and record `tier` on the item before specifying it. If it already has a tier, keep it.
5. Run exactly one transition from §Stage machine for the item's tier, invoking only the skill or agent the table names, on the model §Models names. Human gates are reported, never crossed.
6. Count every `Agent` dispatch the transition made and add it to the item's `agents`. At the tier's cap, stop and report.
7. Record the result on the item and in the phase progress file, including any ruling you made.
8. Print the report in §Report shape and stop.
