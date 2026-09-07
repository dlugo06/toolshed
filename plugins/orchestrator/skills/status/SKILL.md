---
name: status
description: Use when the user asks "what's the status", "what's in flight", "where are we" across projects, or wants the orchestrator's read of the world without changing anything
---

# Orchestrator: status

Read-only. Never edits a file.

1. Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md`.
2. Run:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" --git
   ```
   If it exits non-zero, show its message: the two environment variables are required.
3. For each project with in-flight items, list open PRs with `gh pr list` from inside that project directory.
4. Report per project: duplicate IDs (if any), open and in-flight counts, the in-flight table, and the one item `/orchestrator:next` would pick with its reason. Keep the whole report under 40 lines; the full table is available with `--json`.
