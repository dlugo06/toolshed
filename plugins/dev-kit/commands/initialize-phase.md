---
name: initialize-phase
description: Create a new phase PRD for the Ralph autonomous loop. Enters plan mode for thorough codebase exploration before writing tasks.
allowed-tools: EnterPlanMode, ExitPlanMode, Read, Glob, Grep, Bash, Edit, Write, Agent, AskUserQuestion
---

# Initialize a New Ralph Phase PRD

You are creating a structured phase PRD for the Ralph autonomous development loop.

**This MUST use plan mode.** Enter plan mode immediately to explore the codebase thoroughly before writing any tasks. The quality of Ralph's autonomous execution depends entirely on the specificity and accuracy of the PRD you produce.

## Step 1: Enter Plan Mode

Call `EnterPlanMode` now. In plan mode, you will:

1. **Gather source documents** — ask the user which specs, plans, or design docs to consolidate. Read ALL sources.
2. **Explore the codebase deeply** — for every potential task, search for existing implementations (Grep/Glob), read actual code at the files/functions the task would modify, note exact file paths and line numbers.
3. **Draft the PRD** — write it to `docs/prd/phase{N}-{slug}.json` following the schema below.
4. **Exit plan mode** — present the PRD for user approval before finalizing.

## PRD Schema

Read the ralph-initializer agent for the full schema and quality checks:

```
@${CLAUDE_PLUGIN_ROOT}/agents/ralph-initializer.md
```

Follow its process (Steps 1-8) exactly, but do so **within plan mode** so you can explore thoroughly and get user approval before writing files.

## Key Quality Gates

Before exiting plan mode, verify each task passes these tests:

- **Verifiable**: Every `steps_to_verify` item is either covered by an integration test (`@pytest.mark.integration`, externals mocked) or, when it describes behavior observable only through the running application, flagged for the owner's manual verification after deploy. Code-level requirements go in `implementation_notes`, not `steps_to_verify`.
- **Specificity**: Could an agent implement this without asking a clarifying question?
- **Granularity**: Completable in one context window (1-3 files, one commit)?
- **Accuracy**: File paths and line numbers reference real, current code?
- **No duplicates**: Not already implemented in the codebase?
- **Non-dev filtered**: Business decisions and manual tasks go to `discussions.json`

## Arguments

$ARGUMENTS — Optional: phase name, source document paths, or description of what the phase covers.
