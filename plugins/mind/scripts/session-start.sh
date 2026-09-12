#!/bin/sh
# SessionStart hook: pull the owner's notes repo and print its indexes.
# Inert when MIND_REPO is unset, so the plugin does nothing on machines
# that have not opted in. Never blocks a session: always exits 0.
[ -n "$MIND_REPO" ] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
command -v git >/dev/null 2>&1 || exit 0
# Claude Code passes the SessionStart source ("startup", "resume", "clear",
# "compact") as the "source" key of a JSON object on stdin; there is no env
# var for it. Fall back to "startup" if stdin is empty or unparseable, and
# skip reading stdin entirely on a tty (run by hand at a terminal), where
# json.load would otherwise block waiting for an EOF that never comes.
if [ -t 0 ]; then
    EVENT=startup
else
    EVENT=$(python3 -c 'import json, sys
try:
    print(json.load(sys.stdin).get("source", "startup"))
except Exception:
    print("startup")' 2>/dev/null)
    EVENT="${EVENT:-startup}"
fi
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/mind.py" inject --event "$EVENT" 2>/dev/null || exit 0
exit 0
