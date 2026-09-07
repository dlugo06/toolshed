#!/usr/bin/env bash
# ralph-once.sh — Run a single Ralph loop iteration
#
# Usage:
#   ./ralph-once.sh                                    # auto-detect phase
#   ./ralph-once.sh phase1-mvp-hardening               # target specific phase
#
# This runs Claude in interactive mode so you can watch and intervene.
# Once you're confident, switch to --print for non-interactive.

set -euo pipefail

PHASE="${1:-}"
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

# If no phase specified, find the earliest phase with remaining work
if [ -z "$PHASE" ]; then
    PHASE=$(python3 -c "
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
" "$PRD_DIR")
    PYTHON_EXIT=$?

    if [ "$PYTHON_EXIT" -ne 0 ]; then
        echo "Error: Failed to read PRD files. Check $PRD_DIR/ for corruption."
        exit 1
    fi

    if [ -z "$PHASE" ]; then
        echo "All phases complete! Nothing to do."
        exit 0
    fi
fi

# Validate phase name format
if [[ ! "$PHASE" =~ ^phase[0-9]+-[a-z-]+$ ]]; then
    echo "Error: Invalid phase name format: '$PHASE'"
    echo "Expected format: phase{N}-{slug} (e.g., phase1-mvp-hardening)"
    exit 1
fi

PRD_FILE="$PRD_DIR/$PHASE.json"
PROGRESS_FILE="$PRD_DIR/$PHASE.progress.md"

if [ ! -f "$PRD_FILE" ]; then
    echo "Error: $PRD_FILE not found."
    echo "Available phases:"
    ls "$PRD_DIR"/phase*.json 2>/dev/null | sed 's|.*/||; s|\.json||'
    exit 1
fi

# Count remaining tasks
REMAINING=$(python3 -c "
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
" "$PRD_FILE") || {
    echo "Error: Failed to parse $PRD_FILE"
    exit 1
}

echo "=== Ralph Once ==="
echo "Phase:     $PHASE"
echo "PRD:       $PRD_FILE"
echo "Progress:  $PROGRESS_FILE"
echo "Remaining: $REMAINING tasks"
echo ""

# Run Claude — single argument with @file refs + inline instructions (per aihero guide pattern)
echo "--- Generator ---"
claude \
    --permission-mode acceptEdits \
    "@$PROMPT @$PRD_FILE @$PROGRESS_FILE \
Active phase: $PHASE. PRD file: $PRD_FILE. Progress file: $PROGRESS_FILE. \
Execute the Ralph prompt. Begin from step 1 now."

GENERATOR_EXIT=$?
if [ "$GENERATOR_EXIT" -ne 0 ]; then
    echo "Generator exited with code $GENERATOR_EXIT. Skipping evaluator."
    exit "$GENERATOR_EXIT"
fi

# Check if Ralph actually committed anything
LATEST_COMMIT=$(git log -1 --format="%H" 2>/dev/null)
MASTER_HEAD=$(git rev-parse master 2>/dev/null)

if [ "$LATEST_COMMIT" = "$MASTER_HEAD" ]; then
    echo "No new commits from generator. Skipping evaluator."
    exit 0
fi

# Run evaluator — separate Claude invocation with fresh context (no self-evaluation bias)
EVALUATOR_PROMPT="docs/ralph-evaluator-prompt.md"

if [ ! -f "$EVALUATOR_PROMPT" ]; then
    echo "Warning: $EVALUATOR_PROMPT not found. Skipping evaluator."
    exit 0
fi

echo ""
echo "--- Evaluator ---"
echo "Verifying task against steps_to_verify with fresh context..."
echo ""

claude \
    --permission-mode acceptEdits \
    "@$EVALUATOR_PROMPT @$PRD_FILE @$PROGRESS_FILE \
Active phase: $PHASE. PRD file: $PRD_FILE. Progress file: $PROGRESS_FILE. \
You are the evaluator. Review the most recent commit and verify it against the task's steps_to_verify. Begin from step 1 now."

EVALUATOR_EXIT=$?

# Check evaluator verdict
if [ -f ".dev/ralph-evaluation.md" ]; then
    if grep -q "Verdict: FAIL" .dev/ralph-evaluation.md; then
        echo ""
        echo "=== Evaluator: FAIL ==="
        echo "Issues found. Review .dev/ralph-evaluation.md"
        echo "Run ./ralph-once.sh again to fix, or review manually."
        exit 1
    elif grep -q "Verdict: PASS" .dev/ralph-evaluation.md; then
        echo ""
        echo "=== Evaluator: PASS ==="

        # Steps requiring manual verification don't block PASS — surface them for the owner.
        if grep -q "MANUAL VERIFICATION" .dev/ralph-evaluation.md; then
            echo ""
            echo "--- Manual verification required (owner, post-deploy) ---"
            grep "MANUAL VERIFICATION" .dev/ralph-evaluation.md
            echo ""
        fi

        echo "Ready for /dev-kit:ship"
    fi
fi
