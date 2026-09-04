Check whether the current branch's implementation plan silently regresses behavior from prior design specs.

Launch the **behavioral-impact-checker** agent to cross-reference every behavioral change in the plan (filters, routing, output conditionals) against ALL prior design specs. Run this after `writing-plans` and before `/plan-tests`.

## Steps

1. Launch the `behavioral-impact-checker` agent (subagent_type: "behavioral-impact-checker") in the foreground
2. The agent will read the plan AND all prior specs in `docs/superpowers/specs/`, then write findings to `.dev/BEHAVIORAL_IMPACT_<branch>.md`
3. Present the verdict to the user:
   - **CLEAR** → "No behavioral conflicts found. Safe to proceed with `/plan-tests`."
   - **CONFLICTS FOUND** → Show the conflict list and options: update the plan, update the prior spec, or add explicit acknowledgment.
