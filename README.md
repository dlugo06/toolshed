# Claude Dev Kit

A project skeleton for Claude Code with TDD workflows, autonomous development (Ralph loop), specialist review agents, and structured PRD tracking.

## What's Included

- **11 specialist agents** — PR reviewer, security reviewer, DBA, QA bug hunter, code architect, spec checker, test quality reviewer, test scenario planner, behavioral impact checker, Ralph initializer, E2E tester
- **14 slash commands** — /ship, /process-review, /run-tests, /debug-workflow, /architecture-review, /db-review, /security-review, /qa-hunt, /e2e-test, /initialize-phase, /check-impact, /plan-tests, /review-tests, /spec-check
- **Ralph autonomous loop** — generator/evaluator architecture for unattended TDD-driven development
- **PRD tracking** — JSON-based phase PRDs with progress files and deferred discussions
- **Hookify guardrails** — test scenario and test review gates

## Getting Started

1. Click **"Use this template"** on GitHub (or `gh repo create my-project --template <owner>/claude-dev-kit`)
2. Search for `TODO:` across the repo and fill in your project details
3. Start with `CLAUDE.md` and `.claude/guides/quick-start.md`
4. Delete `docs/prd/phase0-example.json` once you've seen the format
5. Create your first real phase with `/initialize-phase`

## Prerequisites

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)
- Recommended plugins: `superpowers`, `hookify`, `commit-commands`, `pr-review-toolkit`

## Directory Structure

```
├── CLAUDE.md                    # Thin root — references guides
├── .claude/
│   ├── agents/                  # 11 specialist review agents
│   ├── commands/                # 14 slash commands
│   ├── guides/                  # Modular documentation
│   └── hookify.*.local.md      # Safety guardrails
├── docs/
│   ├── prd/                     # Phase PRDs and discussions
│   ├── ralph-prompt.md          # Autonomous task executor
│   └── ralph-evaluator-prompt.md
├── ralph-once.sh                # Single Ralph iteration
└── ralph-afk.sh                 # Unattended loop
```

## Workflows

### Interactive (Superpowers)

Brainstorm → Plan → Check Impact → Plan Tests → Execute (subagent-driven) → Review Tests → Ship

### Autonomous (Ralph)

Initialize Phase → `./ralph-once.sh` → Evaluator verifies → Ship

See [Workflows Guide](.claude/guides/workflows.md) for details.
