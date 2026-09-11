# orchestrator

A cross-project work router for Claude Code. It reads every project's PRD items, assigns each one a pipeline stage, runs the single next transition by invoking the `dev-kit` skills, records the new stage on the item, and stops at the two human gates (merge, and `passes`).

It routes. It does not implement.

## Setup

Two environment variables, both required. Without them the plugin is inert.

```sh
export TOOLSHED_PROJECTS_ROOT="$HOME/projects"        # immediate subdirectories are the projects
export TOOLSHED_PHASES_ROOT="docs/prd/phase*.json"    # glob, relative to each project
```

A project is any git repository directly under the root with at least one matching phase file. Nothing outside the root is read.

Optional: install the [`gh` CLI](https://cli.github.com) and authenticate it. When present, `status.py --gh` (and the SessionStart brief) reads each recorded PR's reviews/comments and `.dev` review reports to derive its real stage from evidence, instead of trusting the `stage` field as asserted — see §Stage is derived, not asserted in `reference/orchestrator.md`. Without `gh`, the orchestrator falls back to the asserted `stage` field alone.

## Skills

| skill | does |
|---|---|
| `/orchestrator:status` | read-only report: per project, what is open, what is in flight, what `next` would pick |
| `/orchestrator:triage` | propose keep / fold / defer / drop for every open item in one project; the owner confirms before anything is written to the phase files |
| `/orchestrator:next` | select one unit across all projects and run its next transition |
| `/orchestrator:advance <project>/<id>` | run the next transition for one named item; `advance "<intent>"` files a new item and specs it |

The SessionStart hook prints what is in flight so a fresh session starts with the next action on screen.

## State

State lives on the PRD items: `stage`, `tier`, `agents`, `branch`, `pr`, `disposition`, `blocked_reason`, `updated`. `passes` belongs to the owner. The stage machine, pipeline tiers (`fix`, `standard`, `full`, each with a subagent cap and a model table), selection rules, ship tiers and guardrails are in `reference/orchestrator.md`.

The orchestrator decides which plugin executes each stage. Inside a run it invokes only what the stage table names: `superpowers` for brainstorming and plan writing, `dev-kit` for the checks and the ship pipeline, and its own implementer and reviewer dispatches for the rest. Skill handoff prompts that say otherwise (an execution-mode choice, "invoke this sub-skill first", "stop for approval") are not followed inside a run. Per-task review loops, separate spec checkers, evaluators and multi-agent simplify passes are reserved for the `full` tier.

| tier | when | cap | token guideline | Opus dispatches |
|---|---|---|---|---|
| `fix` | a bug with a reproduction, one subsystem | 8 | ≈ 1.0M | one: the combined PR reviewer launched by `ship --fix` |
| `standard` | a feature inside existing architecture, or a fix across subsystems | 12 | ≈ 2.0M | the whole-branch reviewer plus three PR reviewers |
| `full` | foundational work, new subsystem, dependency, migration, egress, required config or secret | 20 | ≈ 4.0M | same as standard |

A clean `fix` item runs seven or eight dispatches: impact checker, test planner, one implementer, one whole-branch reviewer (Sonnet), one fix wave, one Opus PR reviewer, one process-review fixer. The `agents` field is incremented after every dispatch; reaching the cap stops the run.

Rules the reference enforces on every run (see `reference/orchestrator.md` §Guardrails): every dispatch brief is under 150 words and names one plan, one report path and one prior report; a stage is recorded only after the agent's report file exists on disk; a spec gives every classification predicate a positive and a negative fixture from the existing tests and names the language of every user-facing string; implementers report, never patch, a pre-existing test the plan did not name; reviewers treat the plan's Rulings as decided; a ruling of at most one file and twenty lines that is test-only or a string/log change is applied inline instead of dispatched; staging is by named path; PR bodies go through `--body-file`; no attribution trailers unless the owner asked. When the owner asks for a session retro, it is kept as `.dev/SESSION_NOTES_<date>.md` in the project with a per-agent token ledger.

## Item shape

The orchestrator reads phase files of this shape (flat `items`, or `sub_phases` each with `items`):

```json
{
  "phase": "Phase 5",
  "items": [
    {"id": "P5-003", "title": "Migration tests", "depends_on": [], "passes": false,
     "stage": "implementing", "branch": "feat/p5003-migration-tests", "updated": "2026-09-06"}
  ]
}
```

## Tests

```sh
python3 -m pytest plugins/orchestrator/tests
```
