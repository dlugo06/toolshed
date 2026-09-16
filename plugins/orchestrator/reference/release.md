# Release reference

The `release` skill runs the merge gate's preparation for a batch of pull requests that autonomous runs produced. This document holds the checklists it applies and the shape of what it writes. The stage machine, tiers and models it audits against are in `orchestrator.md`.

## Inputs

- `release.py prs --project-dir <dir>`: the inventory. Each row joins the PR (number, branch, files, reviews, decision-table comment, owner steps parsed from a "Human steps" / "owner" heading and unchecked `- [ ]` boxes) with its PRD item (tier, stage, `depends_on`, `steps_to_verify`) and the artifacts on disk (`spec`, `plan`, `impact`, `test_plan`, `branch_review`, `pr_review`, `silent_failure`, `security`). `--json` gives the same as data; `--pr N` limits the set.
- The pipeline's `.dev` reports are gitignored and live in whichever checkout the run used: the project's `.dev`, or a harness worktree under `.claude/worktrees/<name>/.dev` when the run was started inside one. `release.py` looks in all of them; the spec and plan are read from the PR branch, since they are tracked but not on the default branch yet. The item's own fields (`tier`, `stage`, `agents`, `pr`) also ride the branch: read them with `git show origin/<branch>:docs/prd/<phase>.json`, not from the default branch, where the item may still read `idea`.
- The phase progress file, on the PR branch: one dated line per transition, with agents, tokens, test counts at a commit, and the rulings. This is the record the stage audit reads when a flag is `no` (an artifact may live under another name; the progress line names it).
- `gh pr view <n> --json reviews,comments`: reviewer count and the process-review decision table.
- `release.py proposals --repo "$MIND_HOME" --since <date>`: the mind proposal audit (below).

## Stage audit

One table per PR, columns `stage | ran | evidence | model | deviation`. Fill it from the artifacts, never from the item's `stage` field [per PRIN-REV-001].

| stage | evidence that it ran |
|---|---|
| spec + plan | `docs/superpowers/specs/*<item>*` and `plans/*<item>*` exist; the progress line names brainstorming when the tier requires it |
| impact_checked | `.dev/BEHAVIORAL_IMPACT_<branch>.md`, verdict line quoted on the progress line |
| tests_planned | `.dev/test-plan-<branch>.md`, scenario count within the tier bound |
| implementing | implementer report(s) and commits; the suites' counts at a commit |
| evaluated | `.dev/REVIEW_<branch>.md` (whole-branch reviewer), plus `.dev/test-review-*` on `standard`/`full`; the fix wave's commits when findings were accepted |
| shipped | the PR exists; reviewer count matches the ship tier (`--fix` one combined, standard three); `.dev/PR_REVIEW_PR<n>.md`, and on standard `SILENT_FAILURE_REVIEW_PR<n>.md` + `SECURITY_REVIEW_PR<n>.md` |
| review_processed | a decision-table comment on the PR; every `Fix` row has a commit after the table's timestamp; threads replied to, none resolved |

Deviations worth naming every time: the whole-branch reviewer's model on the tier (Sonnet on `fix`, Opus otherwise); one combined reviewer on a `fix` item that touched a dependency, migration, egress, or secret (should have been `--full`); the full suite last run before the final fix wave (re-run it in step 3 and say so); `/simplify` not run (the pre-commit hook is a reminder, the whole-branch reviewer covers it on `fix`); a plan step that edits `.env.example` left to the owner; register rows numbered on the branch that collide with another PR's; a test-plan scenario ruled "not implemented" without a fixture or line cited.

Recorded human gates are checked too: no merge, no `passes: true`, no resolved thread, no `.env` write. Any of those found is a defect in the run, reported first.

## Verification

- Per PR: `git worktree add <scratch>/pr-<n> <head-sha>`; link `venv` and `node_modules` from the main checkout (never `.env`, it is hook-protected and the point is to see what fails without it). Run the suites the surfaces require: `python` → the full pytest; `bridge` → `npm test` too; `docs` only → nothing but `ruff format --check` when the PR also carries `.py` files. Record `<passed> passed, <env-failed> env` at the commit.
- Environmental failures (tests that need a key from `.env`) are counted, named once, and run from the main checkout on the integration branch, where `.env` exists.
- Integration branches are chained, one per batch, built in the main checkout so the project's protected-branch hook sees a feature branch: `test/batch-a-<date>` from `origin/<default>`, `test/batch-b-<date>` from batch A's head, and so on, each PR merged with `git merge --no-ff origin/<branch>` in batch order. Chaining resolves every cross-batch conflict once, now; after batch A merges, batch B's rollup PR diff shrinks to its own PRs. Full suites once per batch (a scratch worktree per earlier batch, the last batch in the main checkout where `.env` exists); ruff format on each merged tree; register and PRD JSON validated (no duplicate ids, no gap in BR numbers).
- A merge commit whose pre-commit hook fails (a formatter rewrote a resolved file) leaves the merge half-done: `git add` the rewritten file and commit again **before** creating the next batch branch. A `git checkout -b` in that state drops `MERGE_HEAD`, and the next commit would be a plain commit with one parent, which GitHub never links to the source PR. If that happened, go back to the batch branch, write the source branch's sha to `.git/MERGE_HEAD`, and commit; check `git log -1 --format=%p` shows two parents on every rollup merge.
- Loops over "number branch" pairs are written with `printf | while read n b`; a `for spec in "..."; do set -- $spec` loop does not split words under zsh.
- Jest's "worker process has failed to exit gracefully" is pre-existing on this project's bridge suite; say so instead of counting it.

## Conflicts

- `docs/prd/*.progress.md`: append-only, keep both sides in date order.
- `docs/behaviour-register.md`: keep both, renumber the later PR's new rows to continue the batch's sequence, and `git grep` the old number: an amended row on the same PR may cite it (`per BR-68, P5-049`), and that citation moves with the row. Amendments to existing rows stay on their row; when two PRs amend adjacent rows the conflict block holds both rows and each side's row is taken from the PR that amended it. Say which PR got which numbers in the plan.
- `docs/prd/phase*.json`: keep both items' edits; validate JSON and duplicate ids afterwards.
- Code conflicts: keep both sides when both add a block at the same spot (a validator and its test class, a handler and its tests) and run the suite; anything else is a real conflict, resolved by reading both PRs' plans, and named in the report with the resolution.

## Batching

1. Docs-only PRs (triage, progress) first; they carry the stage corrections the later merges rely on.
2. One deploy surface per batch: the Python quote path and the bridge deploy differently and are verified differently. Config-only PRs ride with the surface they configure.
3. A PR with owner pre-merge steps (a new secret, a dashboard registration, an `.env.example` edit) is its own batch, last, and its checklist opens with those steps.
4. `depends_on` order inside a batch; a dependent never precedes its dependency.
5. The platform deploys every merge to the default branch: merge one batch within a few minutes, verify, then the next. Never interleave batches.
6. Rollup PRs merge with a **merge commit**. A squash orphans the source PRs (GitHub never marks them merged, the item branches linger, the triage run sees phantom in-flight work).

## Manual checks

For each batch, one checklist. Sources, in this order: the item's `steps_to_verify` rows that name a production surface (a WhatsApp message, a Sentry issue, a Railway log line), the PR body's unchecked boxes, the Sentry issues the item's description names. Each line says what the owner does, where, and what they see when it works; a Sentry issue is named by its short id; a log line by its event name. Verification that the suites already prove is not on the list.

The owner's pre-merge steps go in their own list at the top of the batch, verbatim from the PR body, with the file or dashboard named.

## Proposal audit

`release.py proposals` lists every merged `propose/*` PR since the date (a PR whose title says `(6 notes)` but whose table shows 17 proposed was reused by several runs of the same topic on the same day; `propose` appends to an open branch and never retitles the PR) with the notes it proposed, kept, dropped and edited (from the branch's commits: `mind: propose <ID>` adds, `Delete <path>` and `Update <path>` are the owner's edits before merging). Read each dropped note (`git show <delete-commit>`) and classify the drop:

| class | what the note did | the tell |
|---|---|---|
| item ruling | decided one item's scope, YAGNI or trade-off and generalised it | the Why narrates the item; the title only makes sense with the item in view |
| run mechanics | described the agent's own environment (worktrees, missing keys, hook denials, fixtures it could not capture) | the How-to-apply is a workaround for the run, not a rule for the code |
| own correction | generalised a bug the agent introduced and then fixed in the same run | the Why says "was changed to ... which also ..." |
| code placement | prescribed where a function lives or how a module is shaped in this codebase | paths or module names in the body |
| library trap | a third-party behaviour the agent learned | a library name and version in the Why |

A kept note states a stance on how software is built that the owner could have held before the item existed [per PRIN-ID-001]. The tell is not the vocabulary (kept notes also name a bridge or a vendor in their Why) but whether the title stands without the item: "a vendor's 429 joins the transient retry set" stands; "a fixture the agent cannot capture live is built from the docs" is the run talking. When every drop lands in a class the drafting rule in `orchestrator.md` §Consult the mind already excludes, the rule stands and the audit says the acceptance rate. When a drop lands in a class it does not exclude, add the class there (a plugin change) and cite the PR that showed it. Never re-propose a dropped note.

## Report

`.dev/PR_ROLLOUT_<date>.md`, in this order:

1. **Scope**: the PRs, the runs that produced them (dates and windows from the progress lines), the sources read.
2. **What each run did**: one table row per run: items, stages seen, agents, notes.
3. **Deviations**: numbered, each with the rule it deviates from and whether the batch corrects it.
4. **Test validation**: the per-PR table (`branch | commit | pytest | jest | ruff`) and the integration-branch row per batch.
5. **Conflicts**: pairwise, with the resolution applied on the integration branch.
6. **Rollout order**: per batch, the ordered PRs with register renumbering, then "Verify after <batch>" with the manual checks.
7. **Owner steps before merge**: secrets, dashboards, `.env.example`, revocations.
8. **Rejected reviewer findings**: one line per rejected row (`#PR row n: finding. reason`), for the owner to eyeball.
9. **Mind**: the proposal audit table, the acceptance rate, the classes seen, the rule change made or "rule stands", the open proposals.
10. **Integration branches**: names, what they contain, the rollup PR URLs, and how to discard them.

## Report shape (the final message)

```
## Release
PRs: <n> open, <m> batched, <k> held (<ids and why>)
Batches: A <#..> (<surface>) | B <#..> (<surface>) | C <#..> (owner steps first)
Rollup PRs: <urls>
Deviations: <count>, worst: <one line>
Suites: per-PR green at head; integration A <counts>, B <counts>
Owner before merge: <one line per step, or none>
Verify after merge: see .dev/PR_ROLLOUT_<date>.md §6
Mind: kept <k>/<p> since <date>; classes: <list>; rule: <changed (PR url) | stands>; open proposals: <n>
Next: merge A (merge commit), verify, then B; report verification, then set passes
```
