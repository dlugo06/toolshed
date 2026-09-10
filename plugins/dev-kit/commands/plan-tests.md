---
name: plan-tests
description: Generate test scenario plans for the current branch's implementation plan.
---

Generate test scenario plans for the current branch's implementation plan.

Arguments: `[plan path] [--fix|--standard|--full]`. The tier bounds the plan: `--fix` targets 15-25 scenarios, `--standard` 30-50, `--full` as many as the tasks need. Default `--standard`. A 53-scenario plan for a fix-tier bundle once produced 1,400 lines of tests for 300 lines of code; the bound exists for that reason.

Launch the **test-scenario-planner** agent (`model: "sonnet"`, passed explicitly) to analyze the implementation plan, read the source it touches, and produce a structured Given/When/Then scenario map per task. Run this after `writing-plans` and `/dev-kit:check-impact`, and before implementation. The brief is under 150 words: the plan path, the tier, the impact report path, the output path.

## Pre-check

Before launching the test scenario planner, verify that `/dev-kit:check-impact` has been run:
- Check for `.dev/BEHAVIORAL_IMPACT_*.md` for this branch
- If not found, warn: "No behavioral impact analysis found. Run `/dev-kit:check-impact` first to verify the plan doesn't regress prior specs. Proceed anyway? (not recommended)"
- If found and verdict was CONFLICTS FOUND, warn: "Behavioral impact analysis found unresolved conflicts. Resolve them before generating test scenarios."

## Steps

1. Launch the `test-scenario-planner` agent (subagent_type: "dev-kit:test-scenario-planner") in the foreground
2. The agent will read the plan, source code, and `.ai/test-scenarios-guide.md`, then write scenarios to `.dev/test-plan-<branch>.md`
3. The agent now includes **Step 6: Cross-Layer Data Flow Scenarios** which:
   - Traces each input category through the full pipeline (entry → processing → output)
   - Generates end-to-end scenarios that exercise real filtering/routing logic (not mocked)
   - Generates "negative path completeness" scenarios for every filter/drop behavior
   - Flags tests that may enshrine bugs by asserting drops without justification
4. The agent's **Step 7: Predicate Verification** lists every classification predicate in the plan (which exceptions, inputs or states take which branch) next to the real raise sites and callers it found in the code, and flags mismatches. A plan once said "no status code means a network error"; the code wrapped parser bugs in the same exception type. Read this section first.
5. Present the scenario plan and the red flags to the user for review and approval. In an orchestrator run, the orchestrator rules on the red flags from the plan and the code and records the rulings; it does not dismiss any.
6. If changes are requested, relay them to the same agent (SendMessage) rather than launching a new one.
7. Once approved, confirm: "Test scenario plan approved. Ready for implementation."
