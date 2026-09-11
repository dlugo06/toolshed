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

The orchestrator decides which plugin executes each stage. Inside a run it invokes only what the stage table names: `superpowers` for brainstorming and plan writing, `dev-kit` for the checks and the ship pipeline, and its own implementer and reviewer dispatches for the rest. Per-task review loops, separate spec checkers, evaluators and multi-agent simplify passes are reserved for the `full` tier; a `fix` item is capped at eight subagents, two of them on Opus besides the three PR reviewers.

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
