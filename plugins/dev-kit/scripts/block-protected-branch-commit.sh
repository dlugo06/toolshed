#!/bin/sh
# PreToolUse guard: block `git commit` / `git push` while on master or main.
# Reads the PreToolUse hook JSON payload from stdin and inspects .tool_input.command.
# Exit 2 with a one-line reason on stderr to block the tool call.

set -eu

INPUT="$(cat)"

if command -v jq >/dev/null 2>&1; then
    CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')"
else
    # Portable fallback: pull out the value of "command" from the JSON blob.
    CMD="$(printf '%s' "$INPUT" | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\(\([^"\\]\|\\.\)*\)".*/\1/p' | head -n 1)"
fi

[ -z "$CMD" ] && exit 0

# Only look at git commit / git push invocations.
case "$CMD" in
    *git\ commit*|*git\ push*) ;;
    *) exit 0 ;;
esac

# Resolve the repository the command targets, not the session's cwd: a leading
# `cd <dir> &&` or a `git -C <dir>` names it. A commit in a second checkout on a
# feature branch was once blocked because the session cwd sat on master.
DIR="."
case "$CMD" in
    cd\ *)
        DIR="$(printf '%s' "$CMD" | sed -n 's/^cd[[:space:]]\{1,\}\([^[:space:];&|]*\).*/\1/p')"
        ;;
esac
case "$CMD" in
    *git\ -C\ *)
        D2="$(printf '%s' "$CMD" | sed -n 's/.*git[[:space:]]\{1,\}-C[[:space:]]\{1,\}\([^[:space:];&|]*\).*/\1/p')"
        [ -n "$D2" ] && DIR="$D2"
        ;;
esac
[ -z "$DIR" ] && DIR="."

BRANCH="$(git -C "$DIR" branch --show-current 2>/dev/null || true)"

case "$BRANCH" in
    master|main)
        echo "Blocked: refusing to run git commit/push directly on branch '$BRANCH'. Use a feature branch." >&2
        exit 2
        ;;
esac

exit 0
