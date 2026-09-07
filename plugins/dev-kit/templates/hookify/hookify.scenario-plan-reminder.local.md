---
name: scenario-plan-reminder
enabled: true
event: skill
pattern: subagent-driven-development|executing-plans
---

**Starting implementation without test scenarios.** Check if a scenario plan exists:

1. Get the current branch name: `git branch --show-current`
2. Check if `.dev/test-plan-<branch>.md` exists
3. If it does NOT exist, warn:

> "No test scenario plan found for this branch. Run `/dev-kit:plan-tests` first for better test coverage, or confirm you want to proceed without one."

If the file exists, proceed silently.
