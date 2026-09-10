# {Project Name} — Quick Reference

**Project**: TODO: One-line project description
**Status**: TODO: Current phase/milestone
**Tech Stack**: TODO: Python 3.10+, PostgreSQL, etc.

## Quick Start

See [Quick Start Guide](.claude/guides/quick-start.md)

## Critical Rules

- Be concise. Do not explain code you've written unless asked.
- Do not add implementation summaries at the end of tasks.
- Prefer code over explanation.
- **TDD mandatory**: RED → GREEN → REFACTOR → commit. Never commit without tests.
- **Never commit to master**. Always use feature branches: `feat/`, `fix/`, `refactor/`, `test/`, `docs/`.
- **Never commit `.env`** (contains API keys and secrets).
- Internal docs (summaries, plans, research) go in `.dev/` (gitignored). Public docs in `docs/`.

## Architecture

See [Architecture Guide](.claude/guides/architecture.md)

## Development Workflows

Requires the `dev-kit` plugin (`claude plugin install dev-kit@toolshed`).

**Interactive**: `superpowers:brainstorming` → `superpowers:writing-plans` → `/dev-kit:check-impact` → `/dev-kit:plan-tests` → implement (Sonnet implementers) → whole-branch review → `/dev-kit:ship` → `/dev-kit:process-review` → merge (human gate) → manual verification in production.

**Autonomous (Ralph)**: `/dev-kit:initialize-phase` → `./ralph-once.sh [phase]` → evaluator verifies → human reviews `.dev/ralph-evaluation.md` → `/dev-kit:ship`.

**Every step runs for every PR, in every session.** "Get the PR ready" or "ship this" is `/dev-kit:ship`, not a manual push; a PR opened in an earlier session inherits whatever steps that session skipped and they run before merge. At session start, check in-flight PRs for evidence (`gh pr view <n> --json reviews,comments`, `.dev/*_REVIEW_PR<n>.md`) instead of trusting a recorded stage. A stage the owner waives is written down as waived.

**Cost rules**: implementers, fixers and planners on Sonnet; reviewers on Opus, one combined reviewer for fix-tier PRs; every subagent brief under 150 words naming one plan path and one report path; full test suites run once per change, in the subagent, never again in the controller after a green report; fix waves commit per fix; log and issue dumps go to the scratch directory and are summarised before they enter the conversation. Provide a log-capture test fixture (structured logging output, ANSI stripped) so implementers do not rediscover it per task.

## PR Workflow & Specialist Agents

`/dev-kit:ship [--fix|--full|--light] [--reviewed]` — test once → commit → push → PR → launch reviewers (tier chosen by the orchestrator or passed explicitly; see the dev-kit plugin README). An existing PR without review evidence still gets its reviewers.

`/dev-kit:process-review <PR#> [--autonomous] [--no-replies]` — decision table (posted on the PR in autonomous runs), one Sonnet fixer committing per fix, replies unless waived; threads are never resolved.

| Command | Output |
|---------|--------|
| `/dev-kit:architecture-review` | `.dev/ARCHITECTURE_REVIEW.md` |
| `/dev-kit:db-review` | `.dev/DBA_REVIEW.md` |
| `/dev-kit:security-review [PR#]` | `.dev/SECURITY_REVIEW.md` or PR comment |
| `/dev-kit:qa-hunt` | `.dev/QA_REPORT.md` |
| `/dev-kit:check-impact` | `.dev/BEHAVIORAL_IMPACT_<branch>.md` |
| `/dev-kit:plan-tests` | `.dev/test-plan-<branch>.md` |
| `/dev-kit:review-tests` (optional) | `.dev/test-review-<branch>.md` |
| `/dev-kit:spec-check [path]` | `.dev/SPEC_CHECK_REPORT_<date>.md` |

## Gotchas

See [Gotchas Guide](.claude/guides/gotchas.md)

## Documentation

- **PRDs**: `docs/prd/phase*.json` (tasks), `docs/prd/discussions.json` (deferred decisions)
- **Tech docs**: `docs/`
- **Agent reports** (gitignored): `.dev/`
