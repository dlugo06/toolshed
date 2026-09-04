Audit test quality for the current branch before shipping.

Launch the **test-quality-reviewer** agent to cross-reference tests against the approved scenario plan, flag weak assertions, check edge case coverage, audit cross-layer data flow, and report a PASS/NEEDS WORK verdict.

## Steps

1. Launch the `test-quality-reviewer` agent (subagent_type: "test-quality-reviewer") in the foreground
2. The agent will read all changed test and source files, compare against `.dev/test-plan-<branch>.md`, and write findings to `.dev/test-review-<branch>.md`
3. The agent now includes **Step 5b: Cross-Layer Data Flow audit** which checks for:
   - Tests that enshrine filtering/dropping behavior without verifying the drop is intentional
   - Tests that mock past the exact layer they claim to validate
   - Formatter conditionals that depend on fields upstream code never sets
   - Missing end-to-end tests for distinct input categories
4. Present the verdict to the user:
   - **PASS** → "Test quality review passed. Ready to `/ship`."
   - **NEEDS WORK** → Show the blocker list and ask: "Fix these issues before shipping, or override with `/ship` to skip."
