# Changelog

## 1.2.0 (retro of the 2026-09-10 salesperson-feedback run, see the project's `.dev/SESSION_NOTES_2026-09-10.md`)

- orchestrator reference: skill handoff prompts (writing-plans execution choice, process-review's receiving-code-review, plan-tests' approval stop) are explicitly overridden inside a run; new §Inline micro-fixes (≤1 file, ≤20 lines, test/string/log-only) so a fix wave is not dispatched for one flipped test; "config schema change" defined (new required env, secret, or changed validator — not a defaulted toggle); spec rule: every classification predicate ships with one positive and one negative fixture drawn from the existing tests, and every user-facing string names its language; stage records require the report file to exist (`ls` before writing `impact_checked`/`tests_planned`/`evaluated`), with the agent's returned text persisted when it forgot to write; reference dispatch costs per agent from a clean `fix` run and the fixed-prompt overhead note; guardrails for implementer briefs (unnamed breaking tests are reported, not patched), hook-aware briefs (`git grep`, no `.env*`), reviewer briefs (plan Rulings are decided), named-path staging, `--body-file` + separate push, no attribution trailers unless the owner asked; one `git grep -l` before any explore agent; session retro log shape.
- dev-kit `ship`: push and PR creation are separate commands; PR body via `--body-file`; no attribution footer unless asked.
- dev-kit `process-review`: `superpowers:receiving-code-review` only in interactive runs; fix-tier PRs with no inline threads skip replies; tiny waves applied by the caller; findings that re-open recorded rulings are `Reject (decided)`; decision table posted via `--body-file`; fixer prompt is one line pointing at the brief file.
- dev-kit `plan-tests` / `test-scenario-planner`: YAGNI ruling for guarded inputs; predicate rulings name accept/reject fixtures; plans that carry test bodies are mapped, not re-derived; the scenario map is written with the Write tool before the final message; a missing impact report is reported, not fabricated.
- dev-kit `behavioral-impact-checker`: the report file is written before the final message (a run returned its verdict only in the completion message); `git grep` for the spec index; the brief may name one spec to read in full.
- dev-kit `pr-reviewer`: reads the plan's Rulings section as decided; checks user-facing strings against the project's language rule.
- dev-kit hook `block-force-push-protected-branch.sh`: matches the pushed refspec, not any `master`/`main` substring in the command (a `--force-with-lease` of a feature branch was blocked because the same command line contained `origin/master..branch`).

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
