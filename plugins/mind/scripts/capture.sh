#!/bin/sh
# UserPromptSubmit hook: append the prompt to the local pending file for a
# later /mind:digest. Never a prompt-type hook, never blocks, always exit 0.
[ -n "$MIND_REPO" ] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
[ -t 0 ] && exit 0
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/mind.py" capture >/dev/null 2>&1
exit 0
