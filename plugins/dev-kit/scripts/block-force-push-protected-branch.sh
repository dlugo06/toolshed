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

# An explicit, non-protected refspec (`origin feature`, `origin feature:feature`)
# was checked above and is fine whatever branch the session sits on. Only a push
# with no refspec, or `HEAD`, resolves to the current branch and needs the check
# below. Words after `push`: options start with `-`; the first bare word is the
# remote; a second bare word is the refspec.
SEEN_PUSH=0; BARE=0; REFSPEC=""
for WORD in $CMD; do
    if [ "$SEEN_PUSH" -eq 0 ]; then
        [ "$WORD" = "push" ] && SEEN_PUSH=1
        continue
    fi
    case "$WORD" in
        "&&"|"||"|";"|"|") break ;;
        -*) continue ;;
        *) BARE=$((BARE + 1)); [ "$BARE" -eq 2 ] && REFSPEC="$WORD" ;;
    esac
done
case "$REFSPEC" in
    ""|HEAD|HEAD:*) ;;
    *) exit 0 ;;
esac

# No explicit branch named — check if we're currently on master/main and about
# to push there (e.g. `git push --force` with no refspec, or `origin HEAD`).
# Resolve the repository from a leading `cd <dir> &&` or `git -C <dir>` first.
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
        echo "Blocked: refusing to force-push while on branch '$BRANCH'." >&2
        exit 2
        ;;
esac

exit 0
