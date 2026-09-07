#!/usr/bin/env bash
# ralph-afk.sh — Run Ralph in a loop
#
# Usage:
#   ./ralph-afk.sh <iterations>                          # quiet mode, auto-detect phase
#   ./ralph-afk.sh <iterations> phase1-mvp-hardening     # quiet mode, fixed phase
#   ./ralph-afk.sh -v <iterations>                       # verbose: stream output to terminal
#   ./ralph-afk.sh -v <iterations> phase1-mvp-hardening  # verbose, fixed phase
#
# Both modes use print mode (-p) for clean session lifecycle.
# Quiet (default): captures output, shows summary after each iteration.
# Verbose (-v): streams output to terminal in real-time.
# Both auto-exit on <promise>COMPLETE</promise>.
#
# NOTE: For truly unattended operation, this script uses --permission-mode
# acceptEdits, which still prompts for some operations (Bash commands, etc.).
# For fully autonomous runs, you may need --dangerouslySkipPermissions
# (use at your own risk).
#
# Based on: https://www.aihero.dev/getting-started-with-ralph

set -euo pipefail

# Parse flags
VERBOSE=false
if [ "${1:-}" = "-v" ]; then
    VERBOSE=true
    shift
fi

if [ -z "${1:-}" ]; then
    echo "Usage: $0 [-v] <iterations> [phase]"
    echo "  -v          Verbose mode (stream output to terminal)"
    echo "  iterations  Max number of Ralph cycles to run"
    echo "  phase       Optional phase slug (e.g., phase1-mvp-hardening)"
    exit 1
fi

MAX_ITERATIONS="$1"
FIXED_PHASE="${2:-}"
PRD_DIR="docs/prd"
PROMPT="docs/ralph-prompt.md"

# Validate prompt exists
if [ ! -f "$PROMPT" ]; then
    echo "Error: $PROMPT not found. Run from project root."
    exit 1
fi

# Validate PRD directory exists
if [ ! -d "$PRD_DIR" ]; then
    echo "Error: $PRD_DIR directory not found. Run from project root."
    exit 1
fi

# If a fixed phase was given, validate it once up front
if [ -n "$FIXED_PHASE" ]; then
    if [[ ! "$FIXED_PHASE" =~ ^phase[0-9]+-[a-z-]+$ ]]; then
        echo "Error: Invalid phase name format: '$FIXED_PHASE'"
        echo "Expected format: phase{N}-{slug} (e.g., phase1-mvp-hardening)"
        exit 1
    fi
    if [ ! -f "$PRD_DIR/$FIXED_PHASE.json" ]; then
        echo "Error: $PRD_DIR/$FIXED_PHASE.json not found."
        echo "Available phases:"
        ls "$PRD_DIR"/phase*.json 2>/dev/null | sed 's|.*/||; s|\.json||'
        exit 1
    fi
fi

# --- Helper: find earliest phase with remaining work ---
detect_phase() {
    python3 -c "
import json, os, sys
try:
    found = False
    for f in sorted(os.listdir(sys.argv[1])):
        if not f.startswith('phase') or not f.endswith('.json'):
            continue
        found = True
        d = json.load(open(os.path.join(sys.argv[1], f)))
        items = d.get('items', [])
        if not items and 'sub_phases' in d:
            for sp in d['sub_phases'].values():
                items.extend(sp.get('items', []))
        remaining = sum(1 for i in items if not i.get('passes', False))
        if remaining > 0:
            print(f.replace('.json', ''))
            sys.exit(0)
    if not found:
        print('ERROR: No phase PRD files found', file=sys.stderr)
        sys.exit(2)
    sys.exit(0)
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
" "$PRD_DIR"
}

# --- Helper: count remaining tasks in a phase ---
count_remaining() {
    python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    items = d.get('items', [])
    if not items and 'sub_phases' in d:
        for sp in d['sub_phases'].values():
            items.extend(sp.get('items', []))
    remaining = [i for i in items if not i.get('passes', False)]
    print(len(remaining))
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
" "$1"
}

echo "=== Ralph AFK ==="
echo "Max iterations: $MAX_ITERATIONS"
echo "Mode:           $([ "$VERBOSE" = true ] && echo "verbose" || echo "quiet")"
echo ""

for ((i=1; i<=MAX_ITERATIONS; i++)); do
    # Resolve phase (re-detect each iteration so we advance across phases)
    if [ -n "$FIXED_PHASE" ]; then
        PHASE="$FIXED_PHASE"
    else
        PHASE=$(detect_phase) || {
            echo "Error: Failed to read PRD files. Check $PRD_DIR/ for corruption."
            exit 1
        }
        if [ -z "$PHASE" ]; then
            echo "All phases complete! Nothing to do."
            exit 0
        fi
    fi

    PRD_FILE="$PRD_DIR/$PHASE.json"
    PROGRESS_FILE="$PRD_DIR/$PHASE.progress.md"
    REMAINING=$(count_remaining "$PRD_FILE") || {
        echo "Error: Failed to parse $PRD_FILE"
        exit 1
    }

    if [ "$REMAINING" -eq 0 ]; then
        echo "Phase $PHASE complete! No remaining tasks."
        if [ -n "$FIXED_PHASE" ]; then
            exit 0
        fi
        continue  # auto-detect will find next phase on next iteration
    fi

    echo "--- Iteration $i/$MAX_ITERATIONS ---"
    echo "Phase:     $PHASE"
    echo "Remaining: $REMAINING tasks"
    echo ""

    CLAUDE_ARGS=(
        -p
        --permission-mode acceptEdits
        "@$PROMPT @$PRD_FILE @$PROGRESS_FILE \
Active phase: $PHASE. PRD file: $PRD_FILE. Progress file: $PROGRESS_FILE. \
Execute the Ralph prompt. Begin from step 1 now."
    )

    if [ "$VERBOSE" = true ]; then
        # Verbose: stream output to terminal in real-time, capture for COMPLETE check
        result=$(claude "${CLAUDE_ARGS[@]}" | tee /dev/stderr)
    else
        # Quiet: capture output silently
        result=$(claude "${CLAUDE_ARGS[@]}")
        echo "$result"
    fi

    if [[ "$result" == *"<promise>COMPLETE</promise>"* ]]; then
        echo ""
        echo "=== Phase $PHASE complete after $i iterations. ==="
        if [ -n "$FIXED_PHASE" ]; then
            exit 0
        fi
        # Continue loop — auto-detect will find the next phase
    fi

    echo ""
done

echo "=== Ralph AFK finished: $MAX_ITERATIONS iterations completed. ==="
