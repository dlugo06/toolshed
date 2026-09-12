# toolshed

A Claude Code plugin marketplace for the owner's own development workflow: a TDD toolkit, a cross-project work router, and a preference store.

## Plugins

### [`dev-kit`](plugins/dev-kit/) — 1.3.0

A TDD workflow toolkit for Claude Code. Ships 10 specialist review agents (PR reviewer, security reviewer, DBA, QA bug hunter, code architect, spec checker, test quality reviewer, test scenario planner, behavioral impact checker, Ralph initializer), 13 slash commands (`/dev-kit:ship`, `/dev-kit:process-review`, `/dev-kit:check-impact`, `/dev-kit:plan-tests`, `/dev-kit:review-tests`, `/dev-kit:spec-check`, and more), the Ralph autonomous development loop for unattended batch work, JSON-based PRD task tracking, and hookify safety guardrails.

`/dev-kit:ship` runs one of four reviewer tiers: **standard** (three Opus reviewers), **`--full`** (the same three, the security reviewer told what changed; auto-selected when the diff touches a dependency manifest, `.env.example`, migrations, or new egress), **`--fix`** (one Opus `pr-reviewer` in combined mode carrying the silent-failure and security checklists, for small single-subsystem bugs), or **`--light`** (docs/config only). `--reviewed` skips simplify and spec-check when a whole-branch review already ran. `/dev-kit:process-review` has `--autonomous` (rulings from stored preferences, decision table posted on the PR) and `--no-replies`. `/dev-kit:plan-tests` takes `--fix|--standard|--full` to bound the scenario count, and the bound is on tests written (plan-named plus Critical rows). `/dev-kit:check-impact` diffs a plan against the project's **behaviour register** (`docs/behaviour-register.md`, one row per user-observable rule; template in `templates/`) when one exists, reading only the specs the touched rows cite instead of the whole spec corpus; `--seed-register` creates it from the existing specs, and `ship` appends the rows each PR adds. Suites run once per change; agents read the diff once and write their report file before they finish.

### [`orchestrator`](plugins/orchestrator/) — 1.3.0

A cross-project work router. Reads every project's PRD items, assigns each one a pipeline stage and a tier (`fix` / `standard` / `full`, with subagent caps of 8 / 14 / 20 and a token guideline per tier), runs the single next transition by invoking only the skill or agent its stage table names, records the result on the item, and stops at the two human gates (merge, and `passes`). With the `gh` CLI installed, an item's stage is derived from evidence (the PR's reviews and the `.dev` review reports), never trusted as asserted; the SessionStart brief also says when the local default branch is behind origin. The reference (`plugins/orchestrator/reference/orchestrator.md`) holds the stage machine, the model table, the input contract for every dispatch, reference dispatch costs, and the guardrails (named-path staging, `--body-file`, hook-aware lookups, inline micro-fixes for one-file test-or-string changes, no attribution trailers unless the owner asks).

### [`mind`](plugins/mind/) — 0.0.1

An owner preference and decision store injected at session start, so the owner never has to re-explain the same context twice. Placeholder — not yet built.

## Install

### From GitHub (once published)

```
/plugin marketplace add dlugo06/toolshed
/plugin install dev-kit@toolshed
/plugin install orchestrator@toolshed
```

The same commands work from a terminal with `claude plugin marketplace add ...` and `claude plugin install ...`.

### From a local clone or folder

```
claude plugin marketplace add /path/to/toolshed
claude plugin install dev-kit@toolshed
```

### Update

```
claude plugin marketplace update toolshed
claude plugin update dev-kit@toolshed
```

A plugin only updates when its `version` changes.

## Adopting dev-kit in a project

`dev-kit`'s agents, commands, and hooks come with the plugin — installing it is enough to use `/dev-kit:ship`, the review agents, and the hookify guardrails in any project.

Its `templates/` directory holds the pieces that are meant to be **copied into your project**, not run from the plugin install:

```
plugins/dev-kit/templates/
  CLAUDE.md              # skeleton — copy to your project root and fill in the TODOs
  guides/                # architecture.md, gotchas.md, quick-start.md — copy to .claude/guides/
  hookify/                # the two hookify.*.local.md guardrails — copy to .claude/
  ralph/                 # ralph-once.sh, ralph-afk.sh, docs/ralph-prompt.md, docs/ralph-evaluator-prompt.md
  prd/                   # phase0-example.json, discussions.json — copy to docs/prd/
  behaviour-register.md  # one row per user-observable rule — copy to docs/behaviour-register.md
```

Copy what you need, search for `TODO:` across the copied files, and fill in your project's specifics. See [`plugins/dev-kit/README.md`](plugins/dev-kit/README.md) for the full workflow.

## Layout

```
.claude-plugin/marketplace.json   # marketplace catalog (plugin versions live here too)
CHANGELOG.md                      # one entry per version; every plugin change bumps the version
docs/incidents/                   # post-mortems that changed the rules
plugins/<plugin-name>/            # one folder per plugin
  .claude-plugin/plugin.json      # plugin manifest (name, version, ...)
  agents/, commands/, hooks/      # auto-discovered by Claude Code
  skills/                         # orchestrator: status, triage, next, advance
  reference/, scripts/, tests/    # orchestrator: the reference document, status.py, its tests
  templates/                      # files meant to be copied into an adopting project (dev-kit only)
  README.md
```

## Changing a plugin

Two things happen in the same PR as any plugin change, without exception:

1. **Bump the version** in `plugins/<name>/.claude-plugin/plugin.json` and in the matching `.claude-plugin/marketplace.json` entry, with a `CHANGELOG.md` entry. Installed copies only update when the version changes.
2. **Update the READMEs**: this file (versions and the capability summaries above) and `plugins/<name>/README.md` (commands, flags, stages, environment). A plugin PR without a README diff is incomplete.

## License

[MIT](LICENSE)
