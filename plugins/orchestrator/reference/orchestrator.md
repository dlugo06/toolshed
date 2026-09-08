# Orchestrator reference

The orchestrator routes. It reads the world, assigns each unit of work a stage and a tier, runs the single next transition, records the new stage on the PRD item, and stops. It never implements inline and never passes a human gate.

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
| `tier` | orchestrator | `fix`, `standard`, or `full`; chosen once, at `idea -> specced` |
| `branch`, `pr` | orchestrator | where the work lives |
| `disposition` | owner, via triage | `keep`, `defer`, `drop`, or `fold: <target>` |
| `blocked_reason` | orchestrator | why it cannot advance; removed when it can |
| `agents` | orchestrator | running count of subagent dispatches for this item |
| `updated` | orchestrator | ISO date of the last change |
| `passes` | owner only | complete: merged, deployed, verified |

The phase progress file (`*.progress.md` next to the phase file, if the project keeps one) is the human log. Append one line per transition. Rulings the orchestrator makes on the owner's behalf (a plan defect resolved, a review finding rejected) go on that line with the reason; there is no second ledger.

## Who executes a stage

The orchestrator is a skill, not a plugin boundary. It decides which plugin runs each stage, and the stage table below is the whole decision. Inside an orchestrator run, the rule "invoke a skill if it might apply" is suspended: invoke exactly the skill or agent the table names for the current stage and tier, and nothing else. In particular:

- `superpowers` is used for two things only: `brainstorming` (when an item has no known cause) and `writing-plans`. Its `subagent-driven-development` loop, `using-git-worktrees`, `requesting-code-review`, `verification-before-completion`, and `finishing-a-development-branch` are not invoked; the orchestrator dispatches implementers itself, `dev-kit:ship` owns verification and the PR, and `dev-kit:process-review` owns review handling.
- `dev-kit` provides the checks and the ship pipeline.
- Built-in `/simplify` is not run; the whole-branch reviewer is asked to report simplification findings instead.

If a stage is executed by a different plugin than the table names, that is a defect in the run, not a judgment call.

## Pipeline tiers

The tier is chosen at `idea -> specced` from what the item is, recorded as `tier` on the item, and stated in every report. It fixes which stages run, who runs them, on which model, and how many subagents the item may consume.

| tier | when | agent cap |
|---|---|---|
| `fix` | a bug with a reproduction or trace (Sentry issue, failing test, log), a behaviour change confined to one subsystem, a test-gap remediation | 8 |
| `standard` | a feature inside existing architecture, or a fix that touches more than one subsystem | 12 |
| `full` | a phase's foundational task, a new subsystem, a new dependency, migration, new egress or route, secret or config schema change | 20 |

The cap counts every `Agent` dispatch made for the item from `specced` to `review_processed`, including reviewers launched by `dev-kit:ship`. The orchestrator keeps the count in the item's `agents` field and prints it in every report. Reaching the cap is a stop: report, and let the owner raise it. It is never raised silently.

Default when unsure: `fix` if the item has a reproduction, otherwise `standard`. `full` is chosen only for the triggers listed.

## Stage machine

One row per stage. The middle three columns say what runs for each tier; "—" means the stage is skipped and the item moves on.

| stage | leave it by | `fix` | `standard` | `full` |
|---|---|---|---|---|
| idea | spec | write the spec and plan in the main session; `superpowers:brainstorming` only if the cause is unknown; then `superpowers:writing-plans` | `superpowers:brainstorming` then `superpowers:writing-plans` | same as standard |
| specced | check impact | `/dev-kit:check-impact` (Sonnet) | same | same |
| impact_checked | plan tests | `/dev-kit:plan-tests` (Sonnet) | same | same |
| tests_planned | implement | one implementer per batch of related tasks (Sonnet), briefed from the plan, no per-task reviewer | same | one implementer per task (Sonnet), one task reviewer per task (Sonnet), fix rounds capped at 2 |
| implementing | review | one whole-branch reviewer (Opus) with the spec, the plan, and the item's `steps_to_verify`; it reports spec compliance, the verification checklist, correctness, and simplification findings in one pass; one fix dispatch (Sonnet) for its findings, no re-review agent | same, plus `/dev-kit:review-tests` (Sonnet) before the fix dispatch | same as standard, plus the fresh-context evaluator (Sonnet) using the project's evaluator prompt |
| evaluated | ship | `/dev-kit:ship --reviewed` (the whole-branch review already covered the spec and simplification, so ship skips both); reviewers per §Ship tier | `/dev-kit:ship --reviewed` | `/dev-kit:ship --reviewed --full` |
| shipped | process review | `/dev-kit:process-review <pr>`: the decision table, then one fix dispatch (Sonnet), no re-review agent | same | same |
| review_processed | merge | HUMAN GATE. Report, stop. | same | same |
| merged | passes: true | HUMAN GATE. Merged means deployed. The owner verifies manually and confirms; only then set `passes`. Report, stop. | same | same |

The stage names are unchanged from earlier versions; `evaluated` now means "the whole-branch review is clean", whichever tier produced it.

There is no end-to-end test stage. Integration tests are the automated gate; manual verification by the owner after deploy is the human one.

### Ship tier (the orchestrator chooses, not the owner)

`dev-kit:ship` launches the PR reviewers. Every project that serves real users runs all three on every PR; the orchestrator states the ship tier and why.

| tier | when | reviewers |
|---|---|---|
| `--light` | docs or config only, no behaviour change | pr-reviewer |
| standard (default) | everything else | pr-reviewer, silent-failure-hunter, security-reviewer |
| `--full` | new dependency, new egress or HTTP client, new untrusted input or route, migration, secret or config schema change, or a `full`-tier item | the same three, with the security reviewer told what changed |

The reviewers run on Opus. They are the only Opus dispatches besides the whole-branch reviewer.

### Models

| role | model |
|---|---|
| whole-branch reviewer; PR reviewers launched by `dev-kit:ship` | Opus |
| everything else: implementers, impact checker, test-scenario planner, test-quality reviewer, evaluator, task reviewers (`full` only), process-review fixer | Sonnet |
| the orchestrator itself | the session model |

Pass `model` explicitly on every `Agent` call. An omitted model inherits the session's, which is usually the most expensive one.

A FAIL from a reviewer does not move the stage backward. Record `blocked_reason` and stop.

### Budget shape of a `fix` item

For reference, a `fix` item that goes cleanly through the pipeline dispatches: impact checker, test planner, one or two implementers, one whole-branch reviewer, one fix dispatch, three PR reviewers, one process-review fixer. That is eight to nine agents, one to two of them on Opus besides the three PR reviewers. A run that dispatches per-task reviewers, re-reviewers, a separate spec checker, a separate evaluator, and a multi-agent simplify pass costs three to four times that for the same diff.

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
- Subagent prompts are short: a brief file path, one line on where the task fits, the report path, and the report contract. Plans are checklists, not fixtures. Never paste prior-task history into a dispatch.
- Implementers never dispatch subagents of their own; reviewers never dispatch reviewers.
- One transition per unit per invocation. Report, then stop.
- Work only inside `TOOLSHED_PROJECTS_ROOT`.

## Report shape

```
## Orchestrator
Selected: <project>/<id> — <title>. Reason: <one line>.
Tier: <fix|standard|full> — <why>. Agents: <used>/<cap>.
Transition: <from> -> <to> (<skill or agent>, <model>)
Recorded: <phase file> <id> stage=<to>
Rulings: <one line each, or none>
Blocked / needs owner: <ids and why, or none>
Next invocation would: <one line>
```
