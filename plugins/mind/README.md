# mind

`mind` is the owner's engineering memory: principles, preferences, decisions, procedures, gotchas, and references, both universal and per project. Agents consult it before asking the owner, apply what it says, and cite the note ID. It works on every machine and in cloud agent sessions, so the content cannot live in this public repo or in a per-machine file.

Split: **code** lives here, in `plugins/mind`, owner-agnostic, configured by environment variables, public. **Content** lives in a private git repo the owner controls (the "data repo"). The plugin clones it, reads it at session start, and writes to it through `/mind:remember`. Git is the sync channel, the history, and the review surface. Every session injects that repo's content as unlabelled, high-trust instructions: treat write access to `MIND_REPO` as write access to your agent's instructions, the same as you would a CLAUDE.md.

## Setup

```sh
claude plugin install mind@toolshed
export MIND_REPO=git@github.com:<owner>/<data-repo>.git
```

`MIND_REPO` must be one of the documented forms: `ssh://...`, `git@host:...`, `https://...`, `file://...`, or an absolute path. Anything else (e.g. a `ext::` transport) is rejected before any git call is made.

Optional environment variables: `MIND_HOME` (checkout path; defaults to `${CLAUDE_PLUGIN_DATA}/repo`, falling back to `~/.mind/repo`), `MIND_TOKEN` (a token for https remotes, used for cloud sessions where SSH isn't available), `MIND_PROJECT` (force the project slug for this session), `MIND_PENDING` (captured-prompt file path; defaults to `<MIND_HOME>/../pending.jsonl`), `MIND_SETTINGS` (per-machine settings file path; defaults to `<MIND_HOME>/../settings.json`).

First run, once the data repo is empty and `MIND_REPO` is set:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/mind.py" init
```

This writes `schema.md`, creates the `global/` and `projects/` layout, and pushes.

## Data repo layout

```
<data repo>/
  schema.md                     frontmatter contract and note-writing rules
  global/
    index.md                    generated from global/notes, never hand-edited
    notes/<ID>-<kebab-title>.md
  projects/
    index.md                    generated: one line per project
    <slug>/
      project.md                purpose, repo URL, stack, aliases, related projects
      index.md                  generated from projects/<slug>/notes
      notes/<ID>-<kebab-title>.md
```

Only note files and `project.md` are authored and committed. Every `index.md` is a generated local artifact: `init` writes a `.gitignore` covering `**/index.md` into the data repo, and the script regenerates the indexes after every successful pull, add, and accept — so concurrent sessions on different machines never conflict on a shared file. The only cross-machine collision is two machines assigning the same ID to different notes, which `add` detects after pulling and resolves by taking the next free ID (see Sync and failure behaviour). Git history is the change log; there is no `log.md`.

## Note schema

```yaml
---
id: PREF-REV-003
title: Never auto-approve during process-review
type: preference      # principle | preference | decision | procedure | gotcha | reference | precedence
stage: review         # identity | product | planning | development | testing | review | release | deployment | monitoring | security
scope: global         # global | project:<slug>
strength: must        # must | should | default | optional
status: accepted      # draft | accepted | superseded | deprecated
affirmed: 2026-09-11  # last date the owner confirmed it
supersedes: null      # ID of the note this replaces, if any
source: CLAUDE.md, acme-api, 2026-09-11   # where the claim came from
refers: [PREF-REV-001, PREF-REV-002]      # precedence only: the two IDs it rules between
---
One or two sentences stating the claim.

**Why:** the reason, with the incident or evidence if there is one.
**How to apply:** what an agent does differently because of this note.
```

Required fields on `add`: `title`, `type`, `stage`, `strength`. Defaults: `status: accepted`, `affirmed: today`, `scope` from the `--scope` flag, `source: session <date>, <slug>`. Unknown enum values are rejected. Only `accepted` notes appear in injected indexes; `draft` notes are counted in the injection and listed by `--drafts`; `superseded` and `deprecated` notes stay on disk for history and never inject. The full contract, including the writing rules, lives in `schema.md` inside the data repo (written by `init` from `templates/schema.md`).

`init` writes `schema.md` once; upgrading the plugin never rewrites an existing data repo's copy. After upgrading to 0.2.0, re-copy `templates/schema.md` into the data repo by hand to pick up the `precedence` type and `refers` field — `inject` prints `mind: schema.md predates 0.2.0, re-copy templates/schema.md` as a reminder whenever the data repo's `schema.md` is still missing the word `precedence`.

## Session start

`hooks/hooks.json` registers a SessionStart command hook on `startup|resume|clear|compact` running `scripts/session-start.sh`, which exits 0 doing nothing when `MIND_REPO`, `python3`, or `git` is missing, and otherwise runs `mind.py inject --event <source>`. On `startup` and `resume` it syncs first: pull (10 s timeout), then push any local commit that is still unpushed (e.g. from a `/mind:remember` whose own push earlier failed) — a failure at either step prints one line and continues with the cached copy; `clear` and `compact` never touch the network.

It prints, in order: the protocol line, the mode line (`Mode: apply notes silently and cite | confirm before applying a note. Conflicts: use precedence notes | always ask.`, from `settings.json`), the global index, the current project's index (or "no notes for `<candidate>` yet"), the projects index, and the draft count when non-zero ("1 draft awaits acceptance" or "N drafts await acceptance: run /mind:ask --drafts"). The three indexes together are capped at 4,000 characters (`INDEX_BUDGET`): the global index is truncated first, then the project index, and the projects index is never truncated. Within a truncated section, every `must`-strength row is kept first, then one row per stage in round-robin order, so a large mind never hides a whole stage or a hard rule under a tight budget. On `startup`/`resume` it also prints the open-proposal count and URL (from `proposals`, cached for `clear`/`compact`), capped at 5 rows total (the count line's own proposal counts as one) with a `+N more, run mind.py proposals` line beyond that, and, once 20 or more prompts are pending, a reminder to run `/mind:digest`.

## Skills

- **`remember`** (`/mind:remember`): for a fact the owner stated directly. Drafts a note following `schema.md`, chooses the scope by the test "would this be true in a different repo", runs `ask` first to avoid a duplicate or find the note it supersedes, then runs `add`. Anything inferred rather than stated goes through `propose` (or `/mind:digest`) instead.
- **`ask`** (`/mind:ask <topic>`): runs `ask`, reads the full note files for any hit that matters, and answers with the IDs cited. With no hit, says so and retries with `--all` when useful. `--limit N` widens the list, `--stage <stage>` narrows it, and a `[precedence]` row says which of two conflicting notes wins.
- **`digest`** (`/mind:digest`): turns captured prompts into proposed notes. Classifies each pending prompt as correction, directive, answer, or noise; drafts one note per kept prompt, checks for a duplicate with `ask`, and opens a proposal PR with `propose`; marks the watermark either way.
- **`review`** (`/mind:review`): walks stale notes (`stale --days 90`) one at a time, oldest first, offering reinforce (`affirm`), weaken (`affirm --strength`), revise (`propose` with `supersedes`), or retire (`retire`) — never suggests retiring a `must` note on age alone.
- **`lint`** (`/mind:lint`): runs `lint --days 180` and reports the rows verbatim, naming the one command that fixes each; never fixes anything without being asked.

## Proposals (pull requests)

Anything an agent infers rather than the owner stating directly — a `/mind:digest` batch, a seeding pass — is proposed, not added: `mind.py propose <draft.md>... --topic <t> [--scope global|project] [--project slug] [--body <file>]` writes each draft as an accepted note (merging the PR is the acceptance) inside a **temporary git worktree**, never the shared checkout — a concurrent `inject`/`ask`/`add`/`lint` on `MIND_HOME` can never see an unmerged proposal as an accepted note. The branch is `propose/<YYYY-MM-DD>-<topic>`, started from `origin/<branch>` when it already exists (so a second `propose` call to the same topic adds to the same PR) or from `origin/main`; one commit per note (`mind: propose <ID> <title>`), then a push and, with `gh` on PATH and authenticated, `gh pr create --base main --head <branch>` (title `mind: <topic> (<N> notes)`, body one line per note plus its first paragraph, or `--body <file>`). Without `gh`, it prints the branch name and "open the PR by hand". A draft naming an existing note in `supersedes` flips that note to `status: superseded` inside the same branch. The worktree is always removed, success or failure; a failed push leaves the branch committed locally ("`mind: proposal branch <name> is committed locally; push failed`") for a later retry.

`mind.py proposals` lists every `propose/*` branch not yet merged into `origin/main` (`--no-merged origin/main` on both the remote and local listings), with its PR URL, plus any local branch that never reached the remote, tagged `(unpushed)`. A merged proposal drops off the list permanently once merged — whether or not GitHub or the owner ever deletes the remote branch — and a local `propose/*` branch proven merged into `origin/main` is deleted automatically, so a stuck-looking `(unpushed)` branch never nags forever after its PR lands.

## Passive capture and digest

`hooks/hooks.json` also registers a `UserPromptSubmit` hook, `scripts/capture.sh`, which is inert without `MIND_REPO` and appends one JSON line per prompt to the pending file (`<MIND_HOME>/../pending.jsonl`, override `MIND_PENDING`): `{"ts", "session", "project", "cwd", "prompt"}`. Prompts under 12 characters or starting with `/` are skipped; the file is capped at 2 MB (oldest half dropped before appending); the hook always exits 0. The pending file is created (and every append re-asserts) mode `0o600`, never the default umask, since every prompt the owner ever types lands there in clear text. **Prompts are stored verbatim, in clear text, at that path** — a pasted token, `.env` block, or private key is written as-is except for a range of common credential shapes (every current GitHub token prefix — `ghp_`/`gho_`/`ghu_`/`ghr_`/`ghs_` and the newer `github_pat_` — an Anthropic `sk-ant-...` key or any other bare `sk-...` secret, a Slack `xox[baprs]-...` token, a Google `AIza...` API key, an AWS `AKIA...` access key id or `ASIA...` STS id (plus the 40-character secret key pasted next to either), a JWT, a userinfo-embedded URL credential, and a PEM private key block), which are masked to `***` before the line is appended; nothing else scrubs the file. The same shape masking also runs inside `_redact`, applied to git/gh stderr wherever it's echoed (`doctor`'s `remote:` line, `propose`'s worktree/push errors), not only to captured prompts. `mind.py pending [--since <ts>] [--limit N]` prints unprocessed lines as JSON, oldest first; `mind.py pending --mark <ts>` records the watermark in `<pending file>.processed` but **does not delete the underlying lines**; `mind.py pending --clear` deletes only the rows at or before that watermark (keeping the watermark itself, and any row a concurrent session appended after it — never a truncation of the whole file). `--mark <ts> --clear` runs both in one call, in order; a bare `--clear` with no watermark at all deletes nothing and prints `mind: nothing marked, nothing cleared`. The `/mind:digest` skill mines these into proposed notes, then marks and clears.

## Precedence notes and settings

A `precedence` note (code `PREC`) states which of two conflicting notes wins, with an optional `refers: [ID, ID]` list field; body convention: "When `<ID-A>` conflicts with `<ID-B>`, `<ID-A>` wins when `<condition>`." `ask` promotes a matching precedence note to the front, tagged `[precedence]`, whenever a query's other hits share a stage.

Per-machine toggles live in `<MIND_HOME>/../settings.json` (override `MIND_SETTINGS`): `{"auto_answer": true, "escalate": false}`, defaults applied when the file is missing. `mind.py settings --set key=value` (repeatable) reads or writes it; `inject`'s mode line reflects the current values. A value outside `true/false/1/0/yes/no/on/off` is rejected rather than silently coerced to `false`. A settings file that exists but fails to parse also falls back to the defaults, but never silently: `inject` and `doctor` both print `mind: settings file unreadable, using defaults` in that case, rather than presenting the defaults as the owner's configured values.

## Doctor

`mind.py doctor` is read-only — it never clones or mutates `MIND_HOME` — and prints one line per check: the redacted config, checkout state (`ok`/`missing`/`broken (<reason>)`), whether `main` tracks `origin/main`, remote reachability (`git ls-remote`, with timing or a redacted error), the configured git identity, `gh` version and auth status, pending-file counts and watermark, a capture health line (`capture: last write <ts> (<N> lines)` from the pending file's newest row, or `capture: never`), the current settings (plus `mind: settings file unreadable, using defaults` when `settings.json` exists but fails to parse), and note counts (accepted/draft/malformed/projects). Useful for diagnosing a second machine or a cloud session where the mind "isn't working." With `MIND_REPO` unset, `doctor` still exits 0 and prints `config: MIND_REPO=unset ...` and `remote: unreachable (MIND_REPO not set)`, then every other line that needs no repo — it never exits 1 on the one command whose whole point is diagnosing a broken setup.

## Subcommands

One script, `scripts/mind.py`, stdlib only:

| Subcommand | Does |
|---|---|
| `init` | write `schema.md`, create `global/` and `projects/`, commit, push |
| `inject --event E` | sync — pull, then push if ahead (on `startup`/`resume`) — print the budgeted indexes, mode line, proposals/pending lines, draft count, and malformed-note count |
| `add <draft.md> --scope global\|project [--project slug]` | validate frontmatter, assign ID, write the note, reindex, commit `mind: add <ID> <title>`, sync, print the ID and sync outcome |
| `propose <draft.md>... --topic t [--scope global\|project] [--project slug] [--body file]` | write each draft as an accepted note on a `propose/<date>-<topic>` branch in a temporary worktree, push, open (or reuse) a PR |
| `proposals` | list `propose/*` branches not yet merged into `origin/main` with their PR URL, including unpushed local branches; a merged local branch is deleted |
| `ask <terms...> [--all] [--project slug] [--drafts] [--limit N] [--stage stage]` | whole-word, case-insensitive term match over title and body of accepted notes in global plus the current project (`--all`: every project); rank by terms hit; print up to `--limit` (default 10) rows, narrowed by `--stage`; a matching precedence note is promoted to the front |
| `pending [--since ts] [--limit N]` / `pending --mark ts [--clear]` | print unprocessed captured prompts as JSON, or record the digest watermark and/or delete the rows at or before it |
| `stale [--days 90] [--all]` | list accepted notes whose `affirmed` date is older than the threshold, oldest first |
| `affirm <ID> [--strength must\|should\|default\|optional]` | set `affirmed: today`, optionally change `strength`, commit, sync |
| `retire <ID>` | set `status: deprecated`, commit, sync |
| `lint [--days 180]` | report malformed notes, filename/ID mismatches, duplicate IDs across files, dangling references, unsuperseded pairs, duplicate titles, stub projects, stale notes, and injection-budget overflow |
| `settings [--set key=value]` | read or write `<MIND_HOME>/../settings.json` |
| `doctor` | print a diagnostic line per check; read-only, never clones |
| `reindex` | regenerate every `index.md` from notes |
| `accept <ID>` (bare, or `<slug>/<ID>`) | a bare ID resolves against global notes only; a project note needs its slug prefix, and a bare ID present in more than one project is an error (`ambiguous id, use <slug>/<ID>`). Sets `status: accepted` and `affirmed: today`, reindex, commit, sync |
| `sync [--pull-only]` | commit a dirty tree first as `mind: manual edits`, then pull with rebase when local commits exist, else fast-forward; push when ahead (`-u origin HEAD` on an empty remote's first push); one retry on push rejection |

## Sync and failure behaviour

- Authentication: SSH on the owner's machines. In cloud sessions `MIND_REPO` is an https URL and `MIND_TOKEN` is set; the token is passed to git through a credential helper on the command line (username `x-access-token`), never written to disk. An empty `credential.helper=` is emitted first to reset any helper configured earlier (global osxkeychain, `gh`, etc.), so only ours answers and none of them persists the token.
- Timeouts: clone 30 s, pull 10 s, push 20 s.
- The hook never blocks a session: every failure path prints one line and exits 0.
- `add` writes the note and commits before any network call. A failed push leaves the commit local and prints "mind: push failed, note is committed locally; it will push on the next remember or session start" — true: `inject` on `startup`/`resume` syncs, not just pulls, so that commit goes out on the next session start even if the owner never runs `/mind:remember` again.
- ID collision: after the pull that precedes writing, and again after a successful rebase, `add` scans the notes folder for another file carrying the ID it just assigned. If one exists, the local note takes the next free ID and the commit is amended before the push.
- A rebase that conflicts on any file (only hand edits can cause this, since indexes are gitignored) is aborted and reported as `mind: sync conflict in <file>, resolve by hand in <home>`, never as offline.
- Pull/rebase failures are classified, not all called "offline": no upstream branch yet (a brand-new empty data repo) prints `mind: first run, nothing to pull yet`; a timeout or a network/auth-shaped error prints `mind: offline, using cached copy from <date>`; anything else (a genuinely diverged branch, a corrupt repo) prints `mind: sync blocked: <last git error line>`, since that needs the owner's attention and is not a transient blip.
- A checkout with a `.git/` directory but no usable HEAD and no valid empty repo (e.g. a clone the timeout killed mid-transfer) is reported as `mind: checkout at <home> is broken, delete it and rerun`, rather than silently passing as an empty-but-healthy checkout.
- A malformed note (frontmatter that fails the schema, or an id that doesn't match the ID shape) never appears in any index; `inject` reports how many were skipped and where to look.
- Project slugs (from `MIND_PROJECT`, the origin URL, or a directory name) are sanitized to `[a-z0-9][a-z0-9._-]*`; a slug that sanitizes to empty (e.g. `..`) is rejected. `accept <slug>/<ID>` validates the slug the same way, so a path-traversal ID can never read or rewrite a file outside `MIND_HOME`.

## Tests

```sh
python3 -m pytest plugins/mind/tests -q
```

Git operations run against a bare repo created under `tmp_path`, with `MIND_REPO` and `MIND_HOME` pointed at temp paths — no real network access.
