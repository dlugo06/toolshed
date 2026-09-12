# mind

`mind` is the owner's engineering memory: principles, preferences, decisions, procedures, gotchas, and references, both universal and per project. Agents consult it before asking the owner, apply what it says, and cite the note ID. It works on every machine and in cloud agent sessions, so the content cannot live in this public repo or in a per-machine file.

Split: **code** lives here, in `plugins/mind`, owner-agnostic, configured by environment variables, public. **Content** lives in a private git repo the owner controls (the "data repo"). The plugin clones it, reads it at session start, and writes to it through `/mind:remember`. Git is the sync channel, the history, and the review surface.

## Setup

```sh
claude plugin install mind@toolshed
export MIND_REPO=git@github.com:<owner>/<data-repo>.git
```

Optional environment variables: `MIND_HOME` (checkout path; defaults to `${CLAUDE_PLUGIN_DATA}/repo`, falling back to `~/.mind/repo`), `MIND_TOKEN` (a token for https remotes, used for cloud sessions where SSH isn't available), `MIND_PROJECT` (force the project slug for this session).

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
type: preference      # principle | preference | decision | procedure | gotcha | reference
stage: review         # identity | product | planning | development | testing | review | release | deployment | monitoring | security
scope: global         # global | project:<slug>
strength: must        # must | should | default | optional
status: accepted      # draft | accepted | superseded | deprecated
affirmed: 2026-09-11  # last date the owner confirmed it
supersedes: null      # ID of the note this replaces, if any
source: CLAUDE.md, acme-api, 2026-09-11   # where the claim came from
---
One or two sentences stating the claim.

**Why:** the reason, with the incident or evidence if there is one.
**How to apply:** what an agent does differently because of this note.
```

Required fields on `add`: `title`, `type`, `stage`, `strength`. Defaults: `status: accepted`, `affirmed: today`, `scope` from the `--scope` flag, `source: session <date>, <slug>`. Unknown enum values are rejected. Only `accepted` notes appear in injected indexes; `draft` notes are counted in the injection and listed by `--drafts`; `superseded` and `deprecated` notes stay on disk for history and never inject. The full contract, including the writing rules, lives in `schema.md` inside the data repo (written by `init` from `templates/schema.md`).

## Session start

`hooks/hooks.json` registers a SessionStart command hook on `startup|resume|clear|compact` running `scripts/session-start.sh`, which exits 0 doing nothing when `MIND_REPO`, `python3`, or `git` is missing, and otherwise runs `mind.py inject --event <source>`. On `startup` and `resume` it pulls first (10 s timeout; a failure prints an offline line and continues with the cached copy); `clear` and `compact` never touch the network.

It prints, in order: the protocol line, the global index, the current project's index (or "no notes for `<candidate>` yet"), the projects index, and the draft count when non-zero ("1 draft awaits acceptance" or "N drafts await acceptance: run /mind:ask --drafts"). The three indexes together are capped at 4,000 characters (`INDEX_BUDGET`): the global index is truncated first, then the project index, and the projects index is never truncated. Within a truncated section, every `must`-strength row is kept first, then one row per stage in round-robin order, so a large mind never hides a whole stage or a hard rule under a tight budget.

## Skills

- **`remember`** (`/mind:remember`): drafts a note following `schema.md`, chooses the scope by the test "would this be true in a different repo", runs `ask` first to avoid a duplicate or find the note it supersedes, then runs `add`.
- **`ask`** (`/mind:ask <topic>`): runs `ask`, reads the full note files for any hit that matters, and answers with the IDs cited. With no hit, says so and retries with `--all` when useful.

## Subcommands

One script, `scripts/mind.py`, stdlib only:

| Subcommand | Does |
|---|---|
| `init` | write `schema.md`, create `global/` and `projects/`, commit, push |
| `inject --event E` | pull (on `startup`/`resume`), print the budgeted indexes and draft count |
| `add <draft.md> --scope global\|project [--project slug]` | validate frontmatter, assign ID, write the note, reindex, commit `mind: add <ID> <title>`, sync, print the ID and sync outcome |
| `ask <terms...> [--all] [--project slug] [--drafts]` | whole-word, case-insensitive term match over title and body of accepted notes in global plus the current project (`--all`: every project); rank by terms hit; print up to 10 rows |
| `reindex` | regenerate every `index.md` from notes |
| `accept <ID>` (bare, or `<slug>/<ID>`) | a bare ID resolves against global notes only; a project note needs its slug prefix, and a bare ID present in more than one project is an error (`ambiguous id, use <slug>/<ID>`). Sets `status: accepted` and `affirmed: today`, reindex, commit, sync |
| `sync [--pull-only]` | commit a dirty tree first as `mind: manual edits`, then pull with rebase when local commits exist, else fast-forward; push when ahead (`-u origin HEAD` on an empty remote's first push); one retry on push rejection |

## Sync and failure behaviour

- Authentication: SSH on the owner's machines. In cloud sessions `MIND_REPO` is an https URL and `MIND_TOKEN` is set; the token is passed to git through a credential helper on the command line (username `x-access-token`), never written to disk. An empty `credential.helper=` is emitted first to reset any helper configured earlier (global osxkeychain, `gh`, etc.), so only ours answers and none of them persists the token.
- Timeouts: clone 30 s, pull 10 s, push 20 s.
- The hook never blocks a session: every failure path prints one line and exits 0.
- `add` writes the note and commits before any network call. A failed push leaves the commit local and prints "mind: push failed, note is committed locally; it will push on the next remember or session start". The next `add` or `inject` retries the push.
- ID collision: after the pull that precedes writing, and again after a successful rebase, `add` scans the notes folder for another file carrying the ID it just assigned. If one exists, the local note takes the next free ID and the commit is amended before the push.
- A rebase that conflicts on any file (only hand edits can cause this, since indexes are gitignored) is aborted and reported as `mind: sync conflict in <file>, resolve by hand in <home>`, never as offline.
- Project slugs (from `MIND_PROJECT`, the origin URL, or a directory name) are sanitized to `[a-z0-9][a-z0-9._-]*`; a slug that sanitizes to empty (e.g. `..`) is rejected.

## Tests

```sh
python3 -m pytest plugins/mind/tests -q
```

Git operations run against a bare repo created under `tmp_path`, with `MIND_REPO` and `MIND_HOME` pointed at temp paths — no real network access.
