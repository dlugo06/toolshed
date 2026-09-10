# Changelog

## 1.1.0 (incident response, see `docs/incidents/2026-09-unreviewed-pr-and-budget-overrun.md`)

- orchestrator: stage is derived from evidence. `status.py --gh` reads each recorded PR's reviews/comments and `.dev` review reports; a `shipped`/`review_processed` item without evidence is reported as `blocked: PR #n has no review evidence` instead of a merge gate. The SessionStart brief runs `--gh` when `gh` is installed. Reference gains §Stage is derived, not asserted, §Direct requests are entry points, not exemptions, §Verification runs once, and an input contract for every dispatch.
- orchestrator: per-tier token guideline; `agents` is incremented after each dispatch; whole-branch reviewer runs on Sonnet for `fix`; read-only questions go to a small-model explore agent; transition labels for `tests_planned`/`implementing` match the reference.
- dev-kit `ship`: new `--fix` tier (one Opus `pr-reviewer` in combined mode carrying the silent-failure and security checklists); an existing PR with no review evidence still gets its reviewers; suites run once and never after a green subagent report; reviewer briefs carry the input contract.
- dev-kit `process-review`: `--autonomous` (rulings from stored preferences, decision table posted on the PR as the record) and `--no-replies`; the fixer commits per fix, runs suites once, adds no unrequested verification; reviewer findings are checked against the code before they are accepted.
- dev-kit `plan-tests` / `test-scenario-planner`: tier-bound scenario counts (`--fix` 15-25), input bound, mandatory Predicate Verification against raise sites and installed library source; default model Sonnet.
- dev-kit `check-impact` / `behavioral-impact-checker`: spec index before full reads, Step 3b code-conflict check for every predicate, UNVERIFIED third-party claims are conflicts; default model Sonnet.
- dev-kit `pr-reviewer`: reads the diff once and changed functions in context, not whole files; fix-tier combined mode; `Not read:` line.
- dev-kit template `CLAUDE.md`: every step runs for every PR in every session; direct requests are `ship`; cost rules; log-capture fixture recommendation.

## 1.0.0

- Marketplace created from `claude-dev-kit`. Converted the project template into the `toolshed` plugin marketplace with three plugins: `dev-kit` (the former template, now a plugin), `orchestrator` (cross-project work router), and `mind` (placeholder, not yet built).
