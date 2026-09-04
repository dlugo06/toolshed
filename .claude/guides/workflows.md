# Development Workflows

Two modes depending on whether you're working interactively or running autonomous loops.

## Interactive (Superpowers — you're in a session)

1. **Brainstorm**: `superpowers:brainstorming` — explore intent, requirements, design
2. **Plan**: `superpowers:writing-plans` — produce a step-by-step plan with TDD steps
3. **Check Impact**: `/check-impact` — verify the plan doesn't silently regress behavior from prior specs (run before `/plan-tests`)
4. **Plan Tests**: `/plan-tests` — generate and approve test scenario map for all tasks
5. **Execute**: `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`
   - Each task: implementer subagent → spec reviewer → code quality reviewer
6. **Review Tests**: `/review-tests` — audit test quality against scenario map (must pass before ship)
7. **Ship**: `superpowers:finishing-a-development-branch` → `/ship`

## Autonomous (Ralph — unattended batch work)

1. **Plan**: `/initialize-phase` → PRD JSON with `steps_to_verify`
2. **Execute**: `./ralph-once.sh [phase]` — picks one task, TDD, commits
3. **Evaluate**: Automatic — evaluator verifies code against acceptance criteria
4. **Ship**: Human reviews `.dev/ralph-evaluation.md`, then runs `/ship`

## When to Use Which

- **Interactive**: New features, complex integrations, anything needing design decisions
- **Ralph**: Well-defined PRD tasks, batch processing, overnight runs

## Workflow Skills

- **New features**: Always invoke `superpowers:brainstorming` before implementation
- **Debugging**: Always invoke `superpowers:systematic-debugging` before proposing fixes

## Session Management

### Start of session

1. Read `CLAUDE.md`, `docs/prd/` (phase PRDs), and `docs/prd/*.progress.md` files
2. Check branch state (`git branch`, `git status`, `git log -5`)

### End of session

1. Update relevant `docs/prd/*.json` status fields and `docs/prd/*.progress.md`
2. Clean stale branches (`commit-commands:clean_gone` skill)
