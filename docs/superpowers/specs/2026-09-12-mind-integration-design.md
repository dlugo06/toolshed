# Mind integration: the orchestrator and dev-kit consult the mind and propose their rulings

Date: 2026-09-12
Status: approved design
Plugins: `orchestrator` 1.4.0, `dev-kit` 1.4.0. Depends on mind 0.2.0
(`propose`, `proposals`).

## 1. Problem

The orchestrator reference mentions the mind once, as a guardrail with no
command and no record. The dev-kit commands never mention it. Rulings the
orchestrator makes on the owner's behalf (tier, test-plan flags, review
decision tables, plan defects, ship tier) are made from memory files and
`CLAUDE.md` and are logged only in a progress line. The owner cannot see
which rulings rest on a stated preference and which were guesses.

## 2. The rule: decide, cite, or propose

The orchestrator keeps deciding at every step (owner ruling 2026-09-12,
mind `PRIN-PLAN-002`). Each ruling it makes on the owner's behalf must do one
of two things:

- **cite** a mind note ID that settles it, or
- be marked **provisional**, and at the end of the transition every
  provisional ruling is written as a note and delivered as one pull request on
  the data repo through `mind.py propose --topic <project>-<item>-<stage>`.

A provisional ruling is still applied; the proposal is how the owner sees it
and how the mind learns it. This is the pull-back on autonomy: nothing is
decided twice from a guess, because the guess becomes a note the owner can
merge, edit, or close.

Human gates are unchanged: merge and `passes` stay with the owner.

## 3. Orchestrator changes (`plugins/orchestrator/reference/orchestrator.md`)

1. **New section "Consult the mind"** after "Read the world":
   - `mind.py` is at `$(dirname "$CLAUDE_PLUGIN_ROOT")/mind/scripts/mind.py`
     when the marketplace installs plugins side by side. When the sibling
     path is absent, use `$MIND_SCRIPT` if the owner exported it; when
     neither exists, the mind is not installed: skip every consult and
     report `Mind: not installed`. The orchestrator is inert on mind
     consults, not blocked, in either not-installed case.
   - The stage consult table: for each transition, the `ask` terms to run
     before deciding, and what the answer governs.

   | transition | ask terms | governs |
   |---|---|---|
   | idea -> specced | `tier <subsystem words>`, `decision <subsystem words>` | tier choice, prior decisions the spec must honour |
   | specced -> impact_checked | `behaviour register impact <surface words>` | rulings on impact-check conflicts |
   | impact_checked -> tests_planned | `scenario defensive critical` | test-plan flag rulings |
   | tests_planned -> implementing | `implementer brief tests` | brief wording, test bound |
   | implementing -> evaluated | `review ruling <finding words>` | rulings on the whole-branch and review-tests reports |
   | evaluated -> shipped | `ship tier reviewers` | ship tier |
   | shipped -> review_processed | `process-review etiquette`, `<finding words>` | decision table rulings |

2. **Rulings line format** in the progress file and the report: each ruling
   ends with `[per <ID>]` or `[provisional]`.
3. **End of transition**: when any ruling is provisional, draft the notes
   (schema rules, scope by the "true in another repo" test, `source: orchestrator ruling <project>/<item> <date>`)
   and run `propose --topic <project>-<item>-<stage>`; record the PR URL in
   the progress line.
4. **Owner statements** made during the run ("from now on", "never",
   "always", a direct answer to a question) go through `add` (they are
   stated, not inferred) and are cited immediately.
5. **Report shape** gains two lines:
   `Mind: consulted <IDs or none>` and `Proposals: <PR url or none>`.
6. The guardrail line "consult the mind plugin if installed" is replaced by a
   pointer to the new section, and the SessionStart brief is unchanged (the
   mind has its own hook).
7. **Autonomy boundary**: a ruling that would change a `must` note's effect
   is never made provisionally; the orchestrator applies the note and, if it
   believes the note is wrong, records `blocked_reason` and stops. Only
   `should`, `default`, and unstated matters may be ruled provisionally.

## 4. dev-kit changes

- `commands/process-review.md` (`--autonomous`): the decision table gets a
  "Basis" column: a mind ID or `provisional`; the posted table carries it; the
  command ends by listing the provisional rows for the caller to propose
  (the orchestrator does the proposing; an interactive run tells the owner).
- `commands/ship.md`: the PR body's Rulings section cites the mind ID per
  line where one exists; reviewer briefs add: "A mind note that settles a
  style or process point makes it not a finding; cite the ID instead."
- `commands/plan-tests.md` and `commands/check-impact.md`: the rulings the
  caller makes on the report carry the same `[per <ID>]` / `[provisional]`
  suffix.
- `agents/pr-reviewer.md`, `agents/test-quality-reviewer.md`,
  `agents/behavioral-impact-checker.md`, `agents/test-scenario-planner.md`:
  one paragraph each: when a mind is installed, run `ask` for the finding's
  key terms before filing a preference-shaped finding (style, process, test
  volume, model choice); a settling note is cited, not filed.
- `README.md` of dev-kit and the root README: a "Mind" paragraph.

## 5. What does not change

The stage machine, tiers, caps, models, and human gates. The mind is a
source of rulings and a sink for provisional ones; it never advances a stage.

## 6. Testing

The orchestrator and dev-kit changes are reference text and command text.
`plugins/orchestrator/tests` stays green. One new test in the orchestrator
suite asserts that `status.py --brief` output is unchanged (the mind's
injection is separate). The integration is verified by running one real
transition in the reference project and checking the report carries the
`Mind:` and `Proposals:` lines and that a proposal PR appears on the data
repo.

## 7. Release

orchestrator 1.4.0, dev-kit 1.4.0, marketplace entries, changelog, READMEs.
Ship tier `--light` (no behaviour change in code paths that have tests).
