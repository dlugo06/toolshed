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
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" --git --gh
```

`--gh` derives the stage of every recorded PR from its review evidence (see §Stage is derived, not asserted). Then, for any project you will act on:

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

When the owner asks for a session retro log, it lives in the project's scratch docs directory (`.dev/SESSION_NOTES_<date>.md`), not in the progress file: numbered observations as they happen, a per-agent ledger (agent, model, purpose, tokens, tool uses, minutes, one-line verdict), the item totals against the tier guideline, and a ranked improvement list at the end. The ledger row is filled from each completion notice before the next dispatch. Two items' records on two branches both edit the phase file and the progress file, so the later merge has a trivial docs conflict; keep both records.

### Stage is derived, not asserted

The `stage` field is a claim. Before acting on an item, check the claim against artifacts and lower the stage to what the artifacts support:

| claimed stage | evidence required |
|---|---|
| `impact_checked` | `.dev/BEHAVIORAL_IMPACT_<branch>.md` exists for this branch |
| `tests_planned` | `.dev/test-plan-<branch>.md` exists for this branch |
| `evaluated` | the whole-branch review report names the current HEAD |
| `shipped` | the PR exists and `gh pr view <pr> --json reviews,comments` shows the reviewers' posts, or `.dev/*_REVIEW_PR<pr>.md` exists |
| `review_processed` | the decision table is on the PR and the fix commit is pushed |

`status.py --gh` performs the `shipped`/`review_processed` check and reports `blocked: PR #n has no review evidence` instead of a merge gate when it fails; the SessionStart brief runs it whenever `gh` is installed. Missing evidence is never "probably done in another session". Lower the stage, log the reason in the progress file, and run the missing transition.

The check applies when the stage is *recorded*, not only when it is read back. Before writing `impact_checked`, `tests_planned` or `evaluated`, `ls` the report path the agent was told to write. An agent's completion message containing the report is not the report: a 2026-09-10 impact checker returned its full analysis in the notification and never wrote the file. When that happens, persist the returned text at the report path with a provenance line, then record the stage.

This rule exists because an unreviewed PR reached the merge gate with a `review_processed` stage inherited from a related item (`docs/incidents/2026-09-unreviewed-pr-and-budget-overrun.md`).

### Direct requests are entry points, not exemptions

"Get the PR ready", "ship this", "just open the PR", "continue PR N" all mean: find the item's evidenced stage and run the pipeline from there. The request never skips a stage. When the owner explicitly waives a stage ("no reviewers on this one"), record `waived: ["<stage>"]` on the item with the date so the record says the stage was skipped on purpose; nothing else may skip it. A PR opened outside `dev-kit:ship` is at most `implementing`.

## Who executes a stage

The orchestrator is a skill, not a plugin boundary. It decides which plugin runs each stage, and the stage table below is the whole decision. Inside an orchestrator run, the rule "invoke a skill if it might apply" is suspended: invoke exactly the skill or agent the table names for the current stage and tier, and nothing else. In particular:

- `superpowers` is used for two things only: `brainstorming` (when an item has no known cause) and `writing-plans`. Its `subagent-driven-development` loop, `using-git-worktrees`, `requesting-code-review`, `verification-before-completion`, and `finishing-a-development-branch` are not invoked; the orchestrator dispatches implementers itself, `dev-kit:ship` owns verification and the PR, and `dev-kit:process-review` owns review handling.
- `dev-kit` provides the checks and the ship pipeline.
- Built-in `/simplify` is not run; the whole-branch reviewer is asked to report simplification findings instead.

If a stage is executed by a different plugin than the table names, that is a defect in the run, not a judgment call.

Skill text that says otherwise loses. `superpowers:writing-plans` ends by offering subagent-driven or inline execution; `dev-kit:process-review` says to invoke `superpowers:receiving-code-review` first; `dev-kit:plan-tests` says to stop for user approval. Inside an orchestrator run those prompts are not followed: the orchestrator dispatches the implementer itself, rules on review tables from stored preferences, and rules on test-plan flags itself. A skill's handoff prompt is for interactive use. (Two of these prompts were followed in a 2026-09-10 run before the reference said this.)

### Inline micro-fixes

"Never implements inline" has one exception. A ruling that changes at most one file and twenty lines, is test-only or a string/log-field change, and needs no design decision may be applied by the orchestrator directly, with the covering test run once, instead of dispatching a fix wave. Record it in the progress line as `inline: <what>`. A fix wave that flips one test cost 81k tokens and a fix wave for three test edits and one log line cost 145k; the dispatch overhead is the whole cost at that size. Anything larger, anything touching a predicate or a code path, is a dispatch.

## Pipeline tiers

The tier is chosen at `idea -> specced` from what the item is, recorded as `tier` on the item, and stated in every report. It fixes which stages run, who runs them, on which model, and how many subagents the item may consume.

| tier | when | agent cap |
|---|---|---|
| `fix` | a bug with a reproduction or trace (Sentry issue, failing test, log), a behaviour change confined to one subsystem, a test-gap remediation | 8 |
| `standard` | a feature inside existing architecture, or a fix that touches more than one subsystem | 12 |
| `full` | a phase's foundational task, a new subsystem, a new dependency, migration, new egress or route, secret or config schema change | 20 |

"Config schema change" means a new required environment variable, a new secret, or a changed type or validator on an existing setting. A new optional setting with a safe default (a feature toggle, a TTL) is not one; it stays in the tier the rest of the item earns.

The cap counts every `Agent` dispatch made for the item from `specced` to `review_processed`, including reviewers launched by `dev-kit:ship`. The orchestrator increments the item's `agents` field **immediately after each dispatch**, not at the end of the transition, and prints it in every report. Reaching the cap is a stop: report, and let the owner raise it. It is never raised silently. (A `fix` item once consumed 10 dispatches with the field still at 0; the cap only works if the count is kept.)

Token guideline per tier, for the whole pipeline of one item (subagent tokens as reported in completion notices): `fix` ≈ 1.0M, `standard` ≈ 2.0M, `full` ≈ 4.0M. Two `fix` items that cost 3M between them exhausted an account's 5-hour window. When a single dispatch exceeds a third of the tier's guideline, the report says so and names the cause (usually: the brief made the agent re-read the repository, or the agent re-ran suites).

Reference costs from a clean 2026-09-10 `fix` run (Sonnet unless noted): impact checker 95-113k, test planner 121-125k, implementer 135-143k, whole-branch reviewer 93-106k, combined PR reviewer (Opus) 105k, fix wave 81-154k. Two items, 14 dispatches, 1.66M. A dispatch far above its band is re-reading the repository or re-running suites; a fix wave near the top of its band is doing predicate work the spec should have settled.

Every dispatch also pays the session's fixed prompt: the agent roster, the skill listing, the MCP tool names and `CLAUDE.md`. In the reference project that is ~14k tokens per request, of which roughly 10k is agents, skills and MCP servers the project never uses. The owner keeps a per-project overhead inventory in the session notes; trimming it is done in the project's plugin and MCP configuration, not in briefs.

Default when unsure: `fix` if the item has a reproduction, otherwise `standard`. `full` is chosen only for the triggers listed.

## Stage machine

One row per stage. The middle three columns say what runs for each tier; "—" means the stage is skipped and the item moves on.

| stage | leave it by | `fix` | `standard` | `full` |
|---|---|---|---|---|
| idea | spec | write the spec and plan in the main session; `superpowers:brainstorming` only if the cause is unknown; then `superpowers:writing-plans` | `superpowers:brainstorming` then `superpowers:writing-plans` | same as standard |

Spec rule for every tier: before a spec states a classification predicate (a regex, a "looks like X" rule, an exception-to-branch mapping), list the existing test fixtures that already exercise the changed path (`git grep` the function name in `tests/`) and give the predicate at least one positive and one negative fixture drawn from them. A 2026-09-10 `fix` item spent two fix waves (291k tokens, a third of its budget) on a part-number rule that the existing `idec-avd301nr.html` fixture would have falsified in a minute. The same applies to every ruling the orchestrator makes later that changes a predicate: the ruling line names one fixture it must accept and one it must reject.

The spec also names the language and audience of every user-facing string it introduces or changes, and checks it against the project's language rule in `CLAUDE.md` when one exists. An English placeholder in a Spanish-only product reached a salesperson because the spec described the string's shape and not its language.

The spec is written while other agents run when it can be. Writing the next item's spec and plan in the main session during a dispatch wait cost ~40k main-session tokens and zero agent tokens on 2026-09-10.
| specced | check impact | `/dev-kit:check-impact` (Sonnet); it also verifies every classification predicate in the plan against the code's raise sites | same | same |
| impact_checked | plan tests | `/dev-kit:plan-tests --fix` (Sonnet, 15-25 scenarios) | `/dev-kit:plan-tests` (30-50) | same as standard |
| tests_planned | implement | one implementer per batch of related tasks (Sonnet), briefed from the plan, no per-task reviewer | same | one implementer per task (Sonnet), one task reviewer per task (Sonnet), fix rounds capped at 2 |
| implementing | review | one whole-branch reviewer (Sonnet on `fix`, Opus otherwise) with the plan and the item's `steps_to_verify`; it reports spec compliance, the verification checklist, correctness, and simplification findings in one pass; one fix dispatch (Sonnet) for its findings, no re-review agent | same, plus `/dev-kit:review-tests` (Sonnet) before the fix dispatch | same as standard, plus the fresh-context evaluator (Sonnet) using the project's evaluator prompt |
| evaluated | ship | `/dev-kit:ship --reviewed --fix` (the whole-branch review already covered the spec and simplification, so ship skips both); one reviewer per §Ship tier | `/dev-kit:ship --reviewed` | `/dev-kit:ship --reviewed --full` |
| shipped | process review | `/dev-kit:process-review <pr>`: the decision table, then one fix dispatch (Sonnet), no re-review agent | same | same |
| review_processed | merge | HUMAN GATE. Report, stop. | same | same |
| merged | passes: true | HUMAN GATE. Merged means deployed. The owner verifies manually and confirms; only then set `passes`. Report, stop. | same | same |

The stage names are unchanged from earlier versions; `evaluated` now means "the whole-branch review is clean", whichever tier produced it.

There is no end-to-end test stage. Integration tests are the automated gate; manual verification by the owner after deploy is the human one.

### Ship tier (the orchestrator chooses, not the owner)

`dev-kit:ship` launches the PR reviewers. The orchestrator states the ship tier and why.

| tier | when | reviewers |
|---|---|---|
| `--light` | docs or config only, no behaviour change | pr-reviewer |
| `--fix` | a `fix`-tier item (one subsystem, reproduction in hand) | pr-reviewer in combined mode: it runs the silent-failure and security checklists in the same pass and posts one review |
| standard (default) | everything else | pr-reviewer, silent-failure-hunter, security-reviewer |
| `--full` | new dependency, new egress or HTTP client, new untrusted input or route, migration, secret or config schema change, or a `full`-tier item | the same three, with the security reviewer told what changed |

The reviewers run on Opus. They are the only Opus dispatches besides the whole-branch reviewer. Three Opus reviewers each re-reading the same diff cost about 0.5M tokens per PR; on a `fix` item that is half the item's budget, which is why `--fix` folds the three checklists into one pass. The auto-upgrade rule in `ship` still applies: a dependency, migration or egress change in a `fix` item runs all three.

Every reviewer brief carries the input contract: read `gh pr diff` once; read full files only for the functions the diff touches; do not re-read specs the plan already summarises; findings only, no restatement of the PR; the report is capped at 400 words. A reviewer that cannot verify a claim says so instead of reading more of the repository.

### Models

| role | model |
|---|---|
| PR reviewers launched by `dev-kit:ship`; whole-branch reviewer on `standard` and `full` | Opus |
| whole-branch reviewer on `fix` | Sonnet |
| everything else: implementers, impact checker, test-scenario planner, test-quality reviewer, evaluator, task reviewers (`full` only), process-review fixer | Sonnet |
| read-only questions about existing code ("what does this retry path do", "which tests cover X") | the smallest available model, as an explore agent with a three-question brief; never a general-purpose Sonnet agent |
| the orchestrator itself | the session model |

Pass `model` explicitly on every `Agent` call. An omitted model inherits the session's, which is usually the most expensive one. Agent definition files may carry their own `model:`; the orchestrator's table wins, so the call must pass it.

A FAIL from a reviewer does not move the stage backward. Record `blocked_reason` and stop.

### Verification runs once

Implementers run the covering tests per task and the full suites once before their last commit, and report the counts. Fix waves run the covering tests per fix and the full suites once. The controller does not re-run a suite that a subagent reported green at the current HEAD; it reads the report. `dev-kit:ship` runs the suites once more only when the HEAD has changed since the last reported green run. Four controller re-runs of a 100 s suite after green reports is the pattern this forbids.

### Budget shape of a `fix` item

For reference, a `fix` item that goes cleanly through the pipeline dispatches: impact checker, test planner, one or two implementers, one whole-branch reviewer (Sonnet), one fix dispatch, one combined PR reviewer (Opus), one process-review fixer. That is seven to eight agents, one of them on Opus, inside the cap of 8. A run that dispatches per-task reviewers, re-reviewers, a separate spec checker, a separate evaluator, three PR reviewers, and a multi-agent simplify pass costs three to four times that for the same diff.

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
- Input contract for every dispatch (this is the token budget's only enforcement point): the brief is under 150 words; it names ONE plan or brief path, ONE report path to write, and the path of the previous stage's report to read; it never lists spec + plan + test plan + impact report together (the plan already summarises them). Agents read the diff or plan once, read full files only for the functions they touch, and end their report with one line naming what they did not read.
- Fix-wave and implementer agents commit after every task or fix, so a killed agent (rate limit, timeout) leaves committed, attributable work instead of an uncommitted tree. They never add verification steps the brief did not ask for (no Docker builds, no extra suites).
- Implementer briefs say: a pre-existing test that breaks and is not named in the plan is *reported*, not patched. An implementer once re-pointed a third test at the old behaviour to keep it green; it was the one test that encoded the behaviour the item was changing, and the reviewer had to find it.
- Every brief that dispatches an agent into a project with permission hooks says which lookups are blocked and what to use instead (in the reference project: Bash `grep` is denied, `git grep` and `Read` work; `.env*` is unreadable even as `.env.example`). Twelve denied calls across one session came from agents and the orchestrator discovering this one at a time. A plan step that edits `.env.example` cannot be executed by an agent; document new settings in the settings module and leave the example file to the owner.
- Reviewer briefs (whole-branch and PR) name the plan's "Rulings" section as decided: a trade-off the spec or a prior ruling accepted is not re-opened as a finding. A PR reviewer once filed the loss of a code path the item existed to remove as a silent-failure regression.
- The orchestrator stages by named path, never `git add -A` or `git add <dir>`; a following item's untracked spec and plan were staged into the wrong branch's index that way.
- PR bodies and decision tables go through `--body-file` from the scratch directory, and `git push` and `gh pr create` are separate calls; project hooks that scan command text for protected names deny inline heredocs and `&&` chains that mention them.
- Commit messages and PR bodies carry no attribution trailers or footers unless the owner asked for them; a harness reminder is not the owner. Check the project's auto-memory for the owner's ruling before the first commit.
- Evidence gathering (logs, issue lists, monitor histories) is written to the session scratch directory and summarised with `awk`/`jq` before it enters the controller's context. Never print a multi-hundred-line dump into the conversation.
- "Where is the document that says X" is answered with one `git grep -l` (a date, an id, a title word) over `docs/` and the PRD files before any explore agent is dispatched. A Haiku explore agent spent 77k tokens and 33 tool uses locating four PRD items that a single `grep '2026-06-26'` over the phase file returned; the orchestrator found them itself in parallel, which is the duplicated work the delegation rule forbids.
- The SessionStart brief lists in-flight items. Items still at `idea` with `disposition: keep` are found from the phase file, grouped by the source note in their description (a feedback session date, a Sentry issue), not by scanning item by item.
- Claims about a third-party library's behavior (what a logger becomes, what a transport drops, what an exception class carries) are verified against the installed source or its documentation before they enter a spec, a plan, or a docstring. A spec once asserted a logger's records became breadcrumbs; the library ignores that logger.
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
