#!/bin/sh
# PreToolUse guard: block `git push --force`/`-f` targeting master or main.
# Reads the PreToolUse hook JSON payload from stdin and inspects .tool_input.command.
# Exit 2 with a one-line reason on stderr to block the tool call.

set -eu

INPUT="$(cat)"

if command -v jq >/dev/null 2>&1; then
    CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')"
else
    CMD="$(printf '%s' "$INPUT" | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\(\([^"\\]\|\\.\)*\)".*/\1/p' | head -n 1)"
fi

[ -z "$CMD" ] && exit 0

case "$CMD" in
    *git\ push*) ;;
    *) exit 0 ;;
esac

case "$CMD" in
    *--force*|*\ -f\ *|*\ -f) ;;
    *) exit 0 ;;
esac

# Match the pushed refspec, not any substring of the command: a feature-branch
# force-push whose command line also mentions `origin/master..branch` (a log or
# filter-branch range in the same chain) must not be blocked. A word is a
# protected destination when it is exactly master/main (optionally +-prefixed),
# ends in `:master`/`:main`, or is the full ref name.
for WORD in $CMD; do
    case "$WORD" in
        master|main|+master|+main|*:master|*:main|refs/heads/master|refs/heads/main)
            echo "Blocked: refusing to force-push over master/main." >&2
            exit 2
            ;;
    esac
done

# No explicit branch named — check if we're currently on master/main and about
# to push there (e.g. `git push --force` with no refspec, or `origin HEAD`).
BRANCH="$(git branch --show-current 2>/dev/null || true)"
case "$BRANCH" in
    master|main)
        echo "Blocked: refusing to force-push while on branch '$BRANCH'." >&2
        exit 2
        ;;
esac

exit 0
