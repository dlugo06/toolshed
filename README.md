# toolshed

A Claude Code plugin marketplace for the owner's own development workflow: a TDD toolkit, a cross-project work router, and a preference store.

## Plugins

### [`dev-kit`](plugins/dev-kit/) — 1.0.0

A TDD workflow toolkit for Claude Code. Ships 10 specialist review agents (PR reviewer, security reviewer, DBA, QA bug hunter, code architect, spec checker, test quality reviewer, test scenario planner, behavioral impact checker, Ralph initializer), 13 slash commands (`/dev-kit:ship`, `/dev-kit:process-review`, `/dev-kit:check-impact`, `/dev-kit:plan-tests`, `/dev-kit:review-tests`, `/dev-kit:spec-check`, and more), the Ralph autonomous development loop for unattended batch work, JSON-based PRD task tracking, and hookify safety guardrails. `/dev-kit:ship` chooses its reviewer tier (standard, `--full`, or `--light`) based on what changed, or on an explicit flag.

### [`orchestrator`](plugins/orchestrator/) — 0.1.0

A cross-project work router. Reads every project's PRD items, assigns each one a pipeline stage, runs the single next transition, and stops at human gates — so work advances across multiple repos without the owner having to manually pick the next task in each one.

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
```

Copy what you need, search for `TODO:` across the copied files, and fill in your project's specifics. See [`plugins/dev-kit/README.md`](plugins/dev-kit/README.md) for the full workflow.

## Layout

```
.claude-plugin/marketplace.json   # marketplace catalog
plugins/<plugin-name>/            # one folder per plugin
  .claude-plugin/plugin.json      # plugin manifest (name, version, ...)
  agents/, commands/, hooks/      # auto-discovered by Claude Code
  templates/                      # files meant to be copied into an adopting project (dev-kit only)
  README.md
```

## License

[MIT](LICENSE)
