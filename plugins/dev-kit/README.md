# dev-kit

A TDD workflow toolkit for Claude Code: specialist review agents, slash commands for the ship pipeline, the Ralph autonomous development loop, PRD-based task tracking, and hookify safety guardrails.

## Agents

10 specialist agents, addressed as `dev-kit:<agent>`:

| Agent | Purpose |
|-------|---------|
| `pr-reviewer` | Adversarial 5-dimension PR review, posts to GitHub. `model: opus`. At most one CRITICAL finding, requires a reachability argument; verdict is `REQUEST_CHANGES` only with a confirmed CRITICAL, otherwise `COMMENT`. |
| `security-reviewer` | OWASP-style security assessment: vulnerabilities, secret handling, input validation, dependency risk. |
| `dba` | Database design review: schema, ORM usage, query patterns, indexing, migrations. |
| `qa-bug-hunter` | Adversarial QA: coverage gaps, edge cases, targeted test cases, reproduction steps. |
| `code-architect` | Holistic architecture review: system design, data flow, scaling bottlenecks. |
| `spec-checker` | Verifies a branch fully implements a design spec. FAILs only on MISSING or behavior-changing PARTIAL requirements; test-name mismatches, literal-code deviations that preserve behavior, and doc wording differences are INFO and never FAIL. |
| `test-quality-reviewer` | Audits test quality against the approved scenario plan: weak assertions, coverage gaps. |
| `test-scenario-planner` | Generates a Given/When/Then scenario map per task before implementation. |
| `behavioral-impact-checker` | Cross-references a plan's behavioral changes against every prior design spec to catch silent regressions. |
| `ralph-initializer` | Converts source documents into a structured phase PRD for the Ralph loop. |

## Commands

13 slash commands, addressed as `/dev-kit:<command>`:

`ship`, `process-review`, `run-tests`, `debug-workflow`, `architecture-review`, `db-review`, `security-review`, `qa-hunt`, `initialize-phase`, `check-impact`, `plan-tests`, `review-tests`, `spec-check`.

## Hooks

`hooks/hooks.json` registers two `PreToolUse` guards (matcher: `Bash`) backed by scripts in `scripts/`:

- `block-protected-branch-commit.sh` — blocks `git commit` / `git push` while on `master` or `main`.
- `block-force-push-protected-branch.sh` — blocks `git push --force` / `-f` targeting `master` or `main`.

Both read the tool-input JSON from stdin, parse `.tool_input.command` (via `jq` when available, a portable `sed` fallback otherwise), and exit 2 with a one-line reason to block.

Everything else — the two `hookify.*.local.md` guardrails (test scenario reminder, test review reminder) — lives in `templates/hookify/` and is copied into an adopting project, not auto-installed.

## Templates

`templates/` holds files meant to be **copied into your project**, not run from the plugin install — see the root [README](../../README.md#adopting-dev-kit-in-a-project) for the copy instructions:

- `CLAUDE.md` — project skeleton with TODOs
- `guides/` — `architecture.md`, `gotchas.md`, `quick-start.md`
- `hookify/` — the two `hookify.*.local.md` guardrails
- `ralph/` — `ralph-once.sh`, `ralph-afk.sh`, `docs/ralph-prompt.md`, `docs/ralph-evaluator-prompt.md`
- `prd/` — `phase0-example.json`, `discussions.json`

## Workflow

### Interactive (Superpowers — you're in a session)

1. **Brainstorm**: `superpowers:brainstorming` — explore intent, requirements, design
2. **Plan**: `superpowers:writing-plans` — produce a step-by-step plan with TDD steps
3. **Check Impact**: `/dev-kit:check-impact` — verify the plan doesn't silently regress behavior from prior specs (run before plan-tests)
4. **Plan Tests**: `/dev-kit:plan-tests` — generate and approve a test scenario map for all tasks
5. **Execute**: `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`
   - Each task: implementer subagent → spec reviewer → code quality reviewer
6. **Ship**: `/dev-kit:ship` — tier (standard, `--full`, `--light`) is chosen by the caller: the `orchestrator` plugin decides it as part of the normal workflow, or a human can pass the flag directly. `/dev-kit:ship` also auto-upgrades to `--full` on its own when the diff touches a dependency manifest, `.env.example`, migrations, or adds new HTTP egress/webhook code.
7. **Process Review**: `/dev-kit:process-review <PR#>` — read comments, fix or reject with reasoning, reply, resolve
8. **Merge** — human gate. No agent merges a PR.
9. **Manual verification** — the owner verifies the change in production after deploy.

`/dev-kit:review-tests` is available at any point before shipping to audit test quality against the scenario plan, but it is **optional**, not a required gate.

### Autonomous (Ralph — unattended batch work)

1. **Plan**: `/dev-kit:initialize-phase` → PRD JSON with `steps_to_verify`
2. **Execute**: `./ralph-once.sh [phase]` — picks one task, TDD, commits
3. **Evaluate**: Automatic — a fresh-context evaluator verifies the commit against `steps_to_verify` using integration tests; it prints any `MANUAL VERIFICATION` lines for behavior only checkable in the running app, non-blocking
4. **Ship**: Human reviews `.dev/ralph-evaluation.md`, then runs `/dev-kit:ship`

### Testing strategy

Automated end-to-end UI/browser testing is retired. Integration tests (`@pytest.mark.integration`, externals mocked) are the primary automated gate for both interactive and autonomous work; the owner verifies manually in production after deploy; unit tests are kept minimal and fast.

### When to use which

- **Interactive**: New features, complex integrations, anything needing design decisions
- **Ralph**: Well-defined PRD tasks, batch processing, overnight runs

## License

[MIT](../../LICENSE)
