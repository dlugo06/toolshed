# PR Workflow

## Ship a Branch

`/ship` — simplify → test → commit → push → PR → launch reviewers

## Process Review Feedback

`/process-review <PR#>` — read comments, fix/reject with reasoning, reply, resolve

### Review Sources

- GitHub threads + review bodies
- Local agent reports: `.dev/SILENT_FAILURE_REVIEW_PR*.md`, `.dev/SECURITY_REVIEW_PR*.md`

## Reviewers (auto-launched by /ship)

1. `pr-reviewer` — adversarial 5-dimension review
2. `silent-failure-hunter` — error handling analysis (from pr-review-toolkit plugin)
3. `security-reviewer` — OWASP security assessment

## Specialist Agents

| Command | Agent | Output |
|---------|-------|--------|
| `/architecture-review` | code-architect | `.dev/ARCHITECTURE_REVIEW.md` |
| `/db-review` | dba | `.dev/DBA_REVIEW.md` |
| `/security-review [PR#]` | security-reviewer | `.dev/SECURITY_REVIEW.md` or PR comment |
| `/qa-hunt` | qa-bug-hunter | `.dev/QA_REPORT.md` |
| `/e2e-test <phase\|task_id>` | e2e-tester | `.dev/E2E_REPORT_<id>.md` |
| `/check-impact` | behavioral-impact-checker | `.dev/BEHAVIORAL_IMPACT_<branch>.md` |
| `/plan-tests` | test-scenario-planner | `.dev/test-plan-<branch>.md` |
| `/review-tests` | test-quality-reviewer | `.dev/test-review-<branch>.md` |
| `/spec-check [path]` | spec-checker | `.dev/SPEC_CHECK_REPORT_<date>.md` |
