---
name: check-impact
description: Check whether the current branch's implementation plan silently regresses user-observable behavior recorded in the project's behaviour register or prior design specs.
---

Check whether the current branch's implementation plan silently changes user-observable behavior without saying so.

Arguments: `[plan path] [--seed-register]`.

Launch the **behavioral-impact-checker** agent (`model: "sonnet"`, passed explicitly) to cross-reference every behavioral change in the plan (filters, routing, output conditionals, payload fields) against the project's record of established behavior. Run this after `writing-plans` and before `/dev-kit:plan-tests`.

## Which record is used

- **Register mode** (preferred): the project keeps `docs/behaviour-register.md` (template: `templates/behaviour-register.md`). The agent reads the register in full, the branch's own spec, and only the specs that register rows for the touched surfaces cite. Cost is bounded by the register, not by the number of specs the project has accumulated.
- **Spec-corpus mode** (fallback, the original behavior): no register exists. The agent builds a spec index by `git grep` and reads the matching specs in full. This grows linearly with the project; when a project passes roughly fifteen specs, seed the register.
- **`--seed-register`**: one-time. The agent reads every spec once, writes `docs/behaviour-register.md` with one row per user-observable rule it finds, marks rows without a pinning test as `test: none`, and stops. Review the file by hand before the next run relies on it.

## Steps

1. Launch the `behavioral-impact-checker` agent (subagent_type: "dev-kit:behavioral-impact-checker") in the foreground. The brief names the plan path, the mode (register / spec-corpus / seed), and the report path `.dev/BEHAVIORAL_IMPACT_<branch>.md`.
2. The agent writes the report file before it finishes. The report ends with a "Register additions" section: the rows the plan introduces or changes, ready for `/dev-kit:ship` to append.
3. Present the verdict to the user:
   - **CLEAR** → "No behavioral conflicts found. Safe to proceed with `/dev-kit:plan-tests`."
   - **CONFLICTS FOUND** → Show the conflict list and options: update the plan, update the register row (and its spec), or add explicit acknowledgment to the plan.

In an orchestrator run, the orchestrator rules on each conflict itself from the plan's Rulings, the spec, and stored preferences, amends the plan, and records `impact_checked` only after `ls` confirms the report file exists.
