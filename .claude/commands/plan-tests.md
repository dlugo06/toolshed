Generate test scenario plans for the current branch's implementation plan.

Launch the **test-scenario-planner** agent to analyze the implementation plan, read source code, and produce a structured Given/When/Then scenario map per task. Run this after `writing-plans` and `/check-impact`, and before `executing-plans` or `subagent-driven-development`.

## Pre-check

Before launching the test scenario planner, verify that `/check-impact` has been run:
- Check for `.dev/BEHAVIORAL_IMPACT_*.md` for this branch
- If not found, warn: "No behavioral impact analysis found. Run `/check-impact` first to verify the plan doesn't regress prior specs. Proceed anyway? (not recommended)"
- If found and verdict was CONFLICTS FOUND, warn: "Behavioral impact analysis found unresolved conflicts. Resolve them before generating test scenarios."

## Steps

1. Launch the `test-scenario-planner` agent (subagent_type: "test-scenario-planner") in the foreground
2. The agent will read the plan, source code, and `.ai/test-scenarios-guide.md`, then write scenarios to `.dev/test-plan-<branch>.md`
3. The agent now includes **Step 6: Cross-Layer Data Flow Scenarios** which:
   - Traces each input category through the full pipeline (entry → processing → output)
   - Generates end-to-end scenarios that exercise real filtering/routing logic (not mocked)
   - Generates "negative path completeness" scenarios for every filter/drop behavior
   - Flags tests that may enshrine bugs by asserting drops without justification
4. Present the scenario plan to the user for review and approval
5. If the user requests changes, relay them to the agent and regenerate
6. Once approved, confirm: "Test scenario plan approved. Ready for implementation with `/execute` or `subagent-driven-development`."
