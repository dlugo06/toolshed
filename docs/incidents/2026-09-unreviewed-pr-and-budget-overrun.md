# Incident: an unreviewed PR reached the merge gate, and a fix-tier day exhausted the session budget

**Date observed**: 2026-09-09 to 2026-09-10
**Severity**: red. Rules the toolshed exists to enforce were bypassed by the tool itself, and the cost profile makes the pipeline unusable at normal plan limits.
**Scope**: `orchestrator` (stage machine, status reader, SessionStart brief), `dev-kit` (`ship`, `process-review`, `plan-tests`, `check-impact`, the reviewer and planner agents, the CLAUDE.md template).

Names of people, projects and paths are omitted on purpose; this repository is public.

## What happened

1. In a prior session the owner asked for a PR ("PR A", ~960 added lines across a Node bridge, a Python client, a Dockerfile and a dependency patch) to be "made ready". The session committed, pushed and opened the PR directly. None of `dev-kit:ship`'s reviewers ran; `process-review` never ran. The PRD item associated with the branch kept the stage it had inherited from a related item (`review_processed`).
2. The next session's SessionStart brief printed `P [review_processed] -> merge (HUMAN GATE)`. The orchestrator rebased the PR and reported it "ready to merge". Only when the owner asked "has it followed the workflow?" did anyone check `gh pr view --json reviews,comments`: zero reviews, zero comments, no `.dev/*_PR<n>.md` reports.
3. The three ship reviewers were then run. The security review found a MEDIUM newline-injection defect in a log forwarder and the silent-failure review found two HIGHs (a restart guard that could no longer fire; a failure class with no escalation). All would have merged.
4. In parallel the session ran the full `fix`-tier pipeline for a second PR ("PR B", three bundled Sentry items). Fifteen agents were dispatched across the two PRs. Measured subagent usage was about 2.7M tokens plus a fix wave killed by the account's 5-hour rate limit at its final verification step, leaving its work uncommitted. The owner's window hit 70% halfway through the session.
5. PR B's own review found a CRITICAL in the change the pipeline had just produced: the plan's classification predicate ("no status code means a network error, retry it") was wrong, because the vendor clients wrap parser bugs in the same exception type without a status code. Neither `check-impact` nor `plan-tests` caught it; both agents had reviewed the plan text, not the raise sites.

## Rules that were breached

| rule | source | breach |
|---|---|---|
| Every PR goes through `ship` (reviewers) and `process-review` | project CLAUDE.md, orchestrator stage machine | PR A skipped both because the request was phrased as a direct ask |
| Stage is the orchestrator's record of position | orchestrator reference §Units of work | Stage was asserted by inheritance and trusted at a human gate with no evidence check |
| Agent cap per tier (`fix` = 8) | orchestrator reference §Pipeline tiers | PR B used 10 dispatches; the `agents` field was not updated per dispatch, so the cap never fired |
| Full suites run once per change, in the subagent | project memory | The controller re-ran full suites four times after green implementer reports |
| Subagent prompts are short | orchestrator reference §Guardrails | Briefs of 300-600 words listing spec + plan + test plan + impact report; the same 17-file diff was read by four agents |
| Verify third-party behavior before asserting it | project memory | The spec claimed a logger's records become Sentry breadcrumbs; the library ignores that logger. Shipped into docs; caught by review |
| Never route around hooks | project memory | Not breached, but ~10 read-only shell commands were denied by project hook rules and retried in other forms |

## Root cause analysis (5 whys)

### Why did an unreviewed PR reach the merge gate?

1. Why was it reported as ready? The SessionStart brief and `status.py` print the `stage` field and its next transition; `review_processed` maps to "merge (HUMAN GATE)".
2. Why was the stage `review_processed`? It was set when the related umbrella item went through the pipeline, then the field was reused for the follow-up branch without anyone running the stages for that branch.
3. Why could the stages be skipped? `ship` and `process-review` are invoked by the orchestrator's transitions; a direct request ("get the PR ready") was executed as ad-hoc git work. Nothing in the tooling refused to open or push a PR outside `ship`, and nothing reconciled the PRD record afterwards.
4. Why did nothing catch it at the next session start? `status.py` never looked at the PR. It has no notion of evidence; it trusts the JSON field.
5. Why is a self-asserted field trusted at a human gate? The design assumed one writer (the orchestrator). Direct requests, prior sessions, and hand edits are also writers, and the gate had no independent check.

**Root cause**: stage is asserted, not derived. There is no artifact check between `shipped` and `merge`, and a direct request is treated as an exemption from the pipeline instead of an entry point into it.

### Why did a fix-tier day exhaust the budget?

1. Why did the window fill halfway through? About 3M subagent tokens for two fix-tier PRs.
2. Why that many? Six Opus reviewers (three per PR, mandated for every PR), two fix waves at ~360k each, two implementers at 360k and 210k, a 125k read-only analysis agent whose conclusion was wrong, and planning agents at 140k and 200k.
3. Why are individual agents that large? Briefs pass every artifact and each agent re-reads the repository: `check-impact` reads every spec ever written, the planner reads all referenced source, reviewers read full files, fix waves read three review sources plus the code, then re-run every suite (one attempted a Docker build). Nothing bounds input, and nothing tells an agent what the previous agent already established.
4. Why did the fix wave's loss cost so much? It committed nothing until the end; the rate-limit kill discarded ~300k tokens of work into an uncommitted tree that the controller had to verify and commit by hand.
5. Why did no budget stop it? The tier cap counts agents, not tokens, is updated by the orchestrator "at the end of the transition", and has no tooling behind it. The count was not maintained and the cap was exceeded silently.

**Root cause**: no input contract for agents and no enforced budget. Cost is decided by each agent's appetite, not by the tier.

### Why did the pipeline produce a CRITICAL of its own?

1. Why was the classification wrong? The plan said "vendor error with no status code = network failure".
2. Why did the plan say that? The spec author read the one client that raises with a status code and generalised; the scraper wrappers that re-raise parser errors as the same vendor type were not read.
3. Why did `check-impact` pass it? Its job is cross-referencing against prior specs; a predicate that contradicts the code but no spec is invisible to it.
4. Why did `plan-tests` not flag it? It flagged an adjacent gap (an invariant test never used a vendor-typed error) but generated scenarios from the plan's predicate, so the tests encoded the mistake.
5. Why did the implementer not notice? Its brief was the plan; the plan was internally consistent.

**Root cause**: planning-stage agents verify plans against documents, not against the code's actual raise sites and the installed libraries' actual behavior.

## Corrective actions (all in this PR)

| # | action | where |
|---|---|---|
| 1 | Stage evidence: `status.py --gh` reads each in-flight PR's review and comment counts and the `.dev` review reports; a stage at or past `shipped` with no evidence is reported as `blocked: unreviewed` instead of a merge gate. SessionStart passes `--gh` when `gh` is available. | `orchestrator/scripts/status.py`, `scripts/session-start.sh`, `tests/test_status.py` |
| 2 | Stage reconciliation rule: before any transition, the recorded stage is lowered to the evidenced stage; the reason is logged. Direct requests enter the pipeline at the evidenced stage; a stage the owner waives is recorded as `waived` on the item, never silently skipped. | `orchestrator/reference/orchestrator.md`, `skills/advance/SKILL.md`, `skills/status/SKILL.md` |
| 3 | Fix-tier review is one Opus `pr-reviewer` running the silent-failure and security checklists in a single pass; `standard` and `full` keep three. Reviewers read the diff once and full files only for changed functions; findings-only output with a word cap. | `orchestrator.md` §Ship tier, `dev-kit/commands/ship.md`, `dev-kit/agents/pr-reviewer.md` |
| 4 | Ship never bypasses reviewers: an existing PR with no review evidence gets them launched; a direct "open the PR" request is `ship`. Tests run once per change: the controller does not re-run suites an implementer or fixer already ran green at the same commit. | `ship.md` |
| 5 | Process-review: autonomous mode (rulings from stored preferences, the table is posted on the PR as the record), fixer commits per fix, runs covering tests per fix and the full suites once, never adds verification steps beyond the brief, `--no-replies` option. | `process-review.md` |
| 6 | Planning agents verify against code, not documents: `check-impact` and `plan-tests` enumerate the raise sites behind every classification predicate and check claims about third-party behavior against the installed source. Both default to Sonnet. Test-plan size is tier-bound (fix 15-25, standard 30-50). | `agents/behavioral-impact-checker.md`, `agents/test-scenario-planner.md`, `commands/plan-tests.md` |
| 7 | Input contract for every dispatch: brief ≤ 150 words, one plan path, one report path, the previous agent's report path; never spec + plan + test plan + impact report together; agents read the diff or plan once and state what they skipped. Read-only questions go to a small-model explore agent with a three-question brief. | `orchestrator.md` §Guardrails |
| 8 | Budget: the `agents` field is updated after every dispatch, not at the end; the report prints it; a per-tier token guideline is recorded and reaching the agent cap stops the run. Controllers write evidence dumps (logs, issue lists) to the scratch directory and read summaries. | `orchestrator.md` §Pipeline tiers, §Guardrails |
| 9 | Template CLAUDE.md carries the session-start evidence check, the direct-request rule, and the one-suite-run rule so downstream projects inherit them. | `dev-kit/templates/CLAUDE.md` |

## What this does not fix

- Project-level hook rules that deny read-only shell commands; that is per-project configuration.
- A token meter for agents. The CLI does not expose per-dispatch usage to the controller; the agent cap and the input contract are the proxies until it does.
