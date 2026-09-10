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
2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" --project <name> --gh` and locate the item. If its project reports `DUPLICATE IDS`, stop and report.
3. Reconcile the stage with the evidence table in §Stage is derived, not asserted. If the recorded stage is higher than the artifacts support (for example `review_processed` with `next` = `blocked: PR #n has no review evidence`), lower it to the evidenced stage, write the reason in the progress file, and continue from there. Never run a human-gate transition on a claimed stage.
4. If the item is skipped by disposition or blocked by an open dependency, say so and stop. Do not override a disposition.
5. If the item is at `idea`, choose its tier per §Pipeline tiers and record `tier` on the item before specifying it. If it already has a tier, keep it.
6. Run exactly one transition from §Stage machine for the item's tier, invoking only the skill or agent the table names, on the model §Models names, with the input contract from §Guardrails. Human gates are reported, never crossed. A direct request from the owner ("get the PR ready", "ship it") is this same step at the evidenced stage; it skips nothing unless the owner waives a stage, which is recorded as `waived` on the item.
7. Increment the item's `agents` field after **each** `Agent` dispatch, before the next one. At the tier's cap, stop and report.
8. Record the result on the item and in the phase progress file, including any ruling you made and the subagent token totals from the completion notices.
9. Print the report in §Report shape and stop.
