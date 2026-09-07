# Orchestrator reference

The orchestrator routes. It reads the world, assigns each unit of work a stage, runs the single next transition by invoking the existing skill for it, records the new stage on the PRD item, and stops. It never implements inline and never passes a human gate.

Every `/orchestrator:*` skill reads this file first.

## Configuration

Two environment variables, both required. The plugin is inert without them.

| variable | meaning | example |
|---|---|---|
| `TOOLSHED_PROJECTS_ROOT` | directory whose immediate subdirectories are the projects | `$HOME/projects` |
| `TOOLSHED_PHASES_ROOT` | glob, relative to each project, matching its PRD phase files | `docs/prd/phase*.json` |

A project is any git repository directly under the root with at least one matching phase file. Nothing outside the root is ever read.

## Read the world

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" --git
```

Then, for any project you will act on:

```bash
gh pr list -R <owner/repo> --state open --json number,headRefName,reviewDecision,statusCheckRollup
git -C <project> status --short
```

If a project section starts with `DUPLICATE IDS`, stop for that project. Report the IDs and ask the owner to renumber; stages keyed by ID cannot be trusted until then.

## Units of work

A unit is one item in a phase file. The orchestrator keeps its state on the item itself:

| field | set by | meaning |
|---|---|---|
| `stage` | orchestrator | position in the pipeline below |
| `branch`, `pr` | orchestrator | where the work lives |
| `disposition` | owner, via triage | `keep`, `defer`, `drop`, or `fold: <target>` |
| `blocked_reason` | orchestrator | why it cannot advance; removed when it can |
| `updated` | orchestrator | ISO date of the last change |
| `passes` | owner only | complete: merged, deployed, verified |

The phase progress file (`*.progress.md` next to the phase file, if the project keeps one) is the human log. Append one line per transition.

## Stage machine

| stage | leave it by | skill or agent |
|---|---|---|
| idea | spec | `superpowers:brainstorming` then `superpowers:writing-plans` (interactive, main session) |
| specced | check impact | `/dev-kit:check-impact` |
| impact_checked | plan tests | `/dev-kit:plan-tests` |
| tests_planned | implement | `superpowers:subagent-driven-development`, implementers in a worktree |
| implementing | evaluate | fresh-context evaluator agent (read-only) using the project's evaluator prompt |
| evaluated | ship | `/dev-kit:ship` with the tier chosen below |
| shipped | process review | `/dev-kit:process-review <pr>` |
| review_processed | merge | HUMAN GATE. Report, stop. |
| merged | passes: true | HUMAN GATE. Merged means deployed. The owner verifies manually and confirms; only then set `passes`. Report, stop. |

There is no end-to-end test stage. Integration tests are the automated gate; manual verification by the owner after deploy is the human one.

`/dev-kit:review-tests` is optional. Run it when an implementer's tests look thin, not as a stage.

### Ship tier (the orchestrator chooses, not the owner)

| tier | when | reviewers |
|---|---|---|
| `--light` | docs, config, or a one-file fix with no behaviour change | pr-reviewer |
| standard (default) | everything else | pr-reviewer, silent-failure-hunter |
| `--full` | new dependency, new egress or HTTP client, new untrusted input or route, migration, secret or config schema change, or the item is a phase's foundational task | pr-reviewer, silent-failure-hunter, security-reviewer |

State the tier and the reason in the report.

### Models

Use the strongest available model for the orchestrator itself, the evaluator, spec-checker, and PR reviewers. Use the cheaper tier for implementers, test-scenario planning, and exploration. Pass `model` explicitly on every `Agent` call so agent definitions do not change per project.

A FAIL from any evaluator or reviewer does not move the stage backward. Record `blocked_reason` and stop.

## Selecting work (`next`)

1. Exclude items whose `disposition` is `defer`, `drop`, or `fold`, and items with an open blocker in `depends_on`.
2. Prefer items already past `idea` (finish before starting).
3. Among `idea` items, follow the project's stated priority axis if it has one (look in its `CLAUDE.md` and in its discussions or roadmap file for a named migration path or priority order). Items with no place on that axis are not selected until triage gives them `disposition: keep`.
4. Prefer risky and foundational over polish, smaller over larger when tied.
5. Across projects, prefer the project with in-flight work, then the project the session was started in.
6. State the choice and the reason in one line before acting.

If no item in a project has a disposition yet, run triage for that project first.

## Triage

For every open item in a project propose one of `keep`, `fold: <target>`, `defer`, `drop`, with a one-line rationale. Write the proposal to the project's `.dev/orchestrator-triage.md` (or the project's scratch directory). Do not write dispositions into the phase files until the owner confirms; then apply them in one edit per phase file.

## Guardrails

- Never set `passes`, never merge, never approve a PR, never commit to the default branch, never push outside `/dev-kit:ship`.
- Before asking the owner anything, consult the `mind` plugin if installed, then the project's auto-memory and `CLAUDE.md`. If the answer is there, apply it and cite the source. If not, ask once, then record the answer.
- Brainstorming and spec writing are interactive; run them in the main session, never in a subagent.
- Subagent prompts are short: `Read <path> §<section>. <one-line instruction>. Report in <150 words.` Plans are checklists, not fixtures.
- One transition per unit per invocation. Report, then stop.
- Work only inside `TOOLSHED_PROJECTS_ROOT`.

## Report shape

```
## Orchestrator
Selected: <project>/<id> — <title>. Reason: <one line>.
Transition: <from> -> <to> (<skill>)
Recorded: <phase file> <id> stage=<to>
Blocked / needs owner: <ids and why, or none>
Next invocation would: <one line>
```
