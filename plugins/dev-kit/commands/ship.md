---
name: ship
description: Ship the current branch: simplify, test, commit, push, create PR, and launch reviewers.
---

Ship the current branch: simplify, test, commit, push, create PR, and launch reviewers.

Arguments: `[--full|--fix|--light] [--reviewed] [PR title override]` — e.g. `/dev-kit:ship --full`, `/dev-kit:ship --reviewed --fix`, `/dev-kit:ship fix: handle edge case`. The tier flag is normally chosen by the caller (the `orchestrator` plugin decides it as part of the normal workflow; a human can also pass it directly). With no flag, run the **standard** tier below, unless the auto-upgrade rule in step 6 fires.

`--reviewed` means a whole-branch review that covered spec compliance and simplification has already run on this branch (the orchestrator passes it after its `implementing -> evaluated` transition). It skips step 3 (simplify) and step 7 (spec check); nothing else changes.

**Ship is the only way a PR is opened or pushed for review.** "Just open the PR", "get it ready", "push it up" are this command. A PR that exists without review evidence (`gh pr view <n> --json reviews,comments` shows none, and no `.dev/*_REVIEW_PR<n>.md`) is an unshipped PR: run steps 4, 6 and 10 against it. Skipping the reviewers on request is recorded by the caller as a waived stage; ship itself never skips them. (An unreviewed PR once reached the merge gate this way; see the orchestrator plugin's incident record.)

## Tiers

- **standard** (default): spec-check, then `dev-kit:pr-reviewer` + `pr-review-toolkit:silent-failure-hunter` + `dev-kit:security-reviewer`.
- **`--full`**: the same three reviewers; the security reviewer is told which dependency, migration, egress or config change triggered the tier.
- **`--fix`**: one reviewer, `dev-kit:pr-reviewer` in **combined mode** (its brief says `mode: fix-tier combined`): it runs its own checklist plus the silent-failure and security checklists in a single pass and posts one review. For `fix`-tier items: one subsystem, a reproduction in hand. Three Opus reviewers re-reading one small diff cost ~0.5M tokens; this tier exists for that reason.
- **`--light`**: skip spec-check entirely; only `dev-kit:pr-reviewer`. For docs-only or config-only branches with no behaviour change.

All launched reviewer agents run with `model: "opus"` passed on the Agent call, regardless of tier. They are the only Opus dispatches ship makes.

Every reviewer brief is under 150 words and carries the input contract: the PR number; "read `gh pr diff` once; read full files only for the functions the diff touches; do not re-read specs; findings only, no restatement; report under 400 words; end with one line naming what you did not read". Do not paste the spec, plan, test plan or impact report into the brief; name the plan path only.

## Steps

### 1. Validate Branch

```bash
git branch --show-current
```

If on `master` — STOP. Tell the user to create a feature branch first. Never ship from master.

### 2. Check Working State

```bash
git status
git diff --stat
gh pr list --head <branch-name> --json number,url,state
git log origin/<branch-name>..HEAD --oneline 2>/dev/null
```

Determine what work has ALREADY been done:
- PR already open? → skip PR creation in step 9, use existing PR number, and check `gh pr view <n> --json reviews,comments` plus `.dev/*_REVIEW_PR<n>.md`: no evidence means the reviewers in step 10 still run
- Already pushed with no new local commits? → skip push in step 7
- No uncommitted changes? → skip commit in step 5 (but still run simplify + tests)

If no changes (staged or unstaged), no unpushed commits, AND no existing PR — STOP. Nothing to ship.

### 3. Simplify Changed Code

Skip this step when `--reviewed` was passed. Otherwise run `/simplify` on files that were modified in this branch (compared to master) as a single pass, not one agent per angle:

```bash
git diff master --name-only
```

Apply any improvements suggested by simplify. If simplify changes code, re-run tests after.

### 4. Run Tests

Run each suite **once**, and only if no subagent has reported a green full run at the current HEAD (an implementer's or fix wave's report naming this commit's counts is that evidence; read it instead of re-running). When you do run:

```bash
pytest
```

ALL tests must pass. If any fail — STOP. Fix failures before shipping. Never run the suites twice in the same ship; never run them "to be sure" after a green report.

### 5. Commit

If there are uncommitted changes:

- Stage modified files (not untracked files unless they're clearly part of the work)
- Write a conventional commit message (`feat:`, `fix:`, `test:`, `refactor:`, `docs:`)
- Commit

If changes were already committed, skip this step.

### 6. Determine Tier

Start from the flag passed in (or `standard` if none). Then check the auto-upgrade rule:

```bash
git diff master --name-only
```

**Auto-upgrade to `--full`** — without being asked — if the diff touches any of:
- Dependency declarations in a manifest: `requirements*.txt`, the `dependencies`/`optional-dependencies` sections of `pyproject.toml`, `dependencies`/`devDependencies` in `package.json`, `package-lock.json`, `go.mod`, `Cargo.toml`. Tool configuration in the same files (pytest markers, ruff settings, scripts) does not count.
- `.env.example`
- Anything under `migrations/`
- The diff adds a new HTTP client/egress call (matches `httpx|requests|fetch\(|axios`) or a new webhook/route handler

This upgrade applies even if `--light` was passed — a dependency, migration, or egress change always needs at least `security-reviewer`. Record which tier is actually running and why, for the final report.

### 7. Spec Check

Skip this step entirely for `--light` or `--reviewed`. Otherwise, launch the spec-checker agent **in the foreground** (must complete before continuing):

- If the user provided a spec path → pass it explicitly
- Otherwise → let the agent auto-detect from branch name

**Agent** `subagent_type: "dev-kit:spec-checker"` with prompt: `"Run spec check"` (or `"Check spec at <path>"` if known).

**If verdict is PASS** → continue to step 8.

**If verdict is FAIL** → STOP. Show the user the blocking issues from the agent output, then ask:

> "Spec check failed. How would you like to proceed?
> 1. Fix the issues and re-run /dev-kit:ship
> 2. Continue anyway (skip spec compliance)
> 3. The spec is outdated — skip spec check"

Wait for the user's response before continuing. Do NOT proceed to push or PR creation until resolved.

**If no spec found for the branch** → STOP. Ask the user which spec to use:

> "No spec found matching branch `<branch-name>`. Available specs in `docs/superpowers/specs/`:"
> (list all specs)
> "Which spec should I check against, or type 'skip' to skip the spec check?"

Wait for the user's response before continuing.

### 8. Push

```bash
git push -u origin <branch-name>
```

Run this as its own command. Do not chain it with `gh pr create`: project hooks that scan command text (protected-branch guards, safety patterns) deny the whole chain when any part of it mentions a guarded name.

### 9. Create PR

Write the body to a file in the session scratch directory first, then:

```bash
gh pr create --title "<title>" --body-file <scratch>/pr-body-<branch>.md
```

Body template:

```markdown
## Summary
<1-3 bullet points summarizing ALL commits on this branch>

## Test plan
- [ ] All tests pass
- [ ] Integration tests cover the change

## TDD compliance
- [ ] Tests written before implementation
- [ ] RED → GREEN → REFACTOR cycle followed
```

An inline heredoc body is denied by the same hooks whenever the summary names a guarded function (a PR body that mentioned the Stelorder product-creation call was blocked twice). No attribution footer or trailer unless the project's owner asked for one; check the project's auto-memory.

If the user provided a title argument, use it. Otherwise, generate one from the branch name and commit messages. Keep it under 70 characters.

If a PR already exists for this branch, skip creation and use the existing PR number.

### 10. Launch Reviewers By Tier

Launch every reviewer for the resolved tier in a SINGLE message (parallel tool calls, all in background). Every Agent call passes `model: "opus"` and the PR number.

- **standard**: `subagent_type: "dev-kit:pr-reviewer"`, `subagent_type: "pr-review-toolkit:silent-failure-hunter"`, `subagent_type: "dev-kit:security-reviewer"`
- **`--full`**: the same three; the security reviewer's brief names the triggering change
- **`--fix`**: `subagent_type: "dev-kit:pr-reviewer"` only, brief line `mode: fix-tier combined`
- **`--light`**: `subagent_type: "dev-kit:pr-reviewer"` only

If the PR already existed and step 2 found no review evidence, this step runs regardless of how the PR was opened.

### 11. Report

After reviewers complete, output a summary:

```
## Ship Complete

- Branch: <branch>
- PR: <url>
- Tier: <standard|full|light> — <reason: requested | auto-upgraded because ... | light (docs/config-only)>
- Commit(s): <count> commits pushed
- Tests: <count> passed
- Reviews launched: <list of agents actually launched>
```
