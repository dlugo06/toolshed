#!/bin/sh
# SessionStart hook: print what is on the hook across all projects.
# Silent when the environment is not configured, so the plugin is inert
# on machines that have not opted in.
[ -n "$TOOLSHED_PROJECTS_ROOT" ] || exit 0
[ -n "$TOOLSHED_PHASES_ROOT" ] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
# --gh: derive the stage of in-flight PRs from review evidence instead of
# trusting the recorded field (an unreviewed PR once reached the merge gate).
# Fails closed: without gh, or offline, reviewed stages show as blocked.
if command -v gh >/dev/null 2>&1; then
    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" --brief --gh 2>/dev/null || exit 0
else
    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" --brief 2>/dev/null || exit 0
fi
