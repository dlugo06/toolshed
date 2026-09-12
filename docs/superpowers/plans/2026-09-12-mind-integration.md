# Mind Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the orchestrator and dev-kit consult the mind before every ruling and deliver uncited rulings as proposal pull requests on the data repo.

**Architecture:** Text changes to the orchestrator reference, the dev-kit commands and agents, and the READMEs. No code path with tests changes; one orchestrator test pins that the SessionStart brief is unchanged.

**Tech Stack:** Markdown; `mind.py propose`/`ask`/`proposals` from mind 0.2.0.

**Spec:** `docs/superpowers/specs/2026-09-12-mind-integration-design.md`

## Global Constraints

- Public repo: no personal names, local paths, employer or project names. Owner's hygiene grep over `git diff main --name-only` before every commit.
- Versions: orchestrator `1.4.0`, dev-kit `1.4.0` in their `plugin.json` and the marketplace; one `## 1.4.0 (2026-09-12)` changelog entry covering both; root README, `plugins/orchestrator/README.md`, `plugins/dev-kit/README.md` updated.
- Plain names, no analogies. Commit style `docs(orchestrator): ...`, `docs(dev-kit): ...`, no attribution trailers.
- The mind script path in every reference: `"$(dirname "$CLAUDE_PLUGIN_ROOT")/mind/scripts/mind.py"` (marketplace plugins install side by side); when that file is absent the consult step is skipped and the report says `Mind: not installed`.

---

### Task 1: Orchestrator reference

**Files:** Modify `plugins/orchestrator/reference/orchestrator.md`; Test `plugins/orchestrator/tests/test_status.py`

- [ ] **Step 1: Failing test** (pins that the brief has no mind text; the mind has its own hook)

```python
def test_brief_has_no_mind_section(root, monkeypatch, capsys):
    monkeypatch.setenv("TOOLSHED_PROJECTS_ROOT", str(root))
    monkeypatch.setenv("TOOLSHED_PHASES_ROOT", PHASES)
    assert main(["--brief"]) == 0
    out = capsys.readouterr().out
    assert "Mind:" not in out and "mind.py" not in out
```

- [ ] **Step 2: Run, expect pass already** (it pins current behaviour; keep it).
- [ ] **Step 3: Edit the reference.** Insert after "## Read the world" a new section:

```markdown
## Consult the mind

The `mind` plugin (installed side by side: `MIND="$(dirname "$CLAUDE_PLUGIN_ROOT")/mind/scripts/mind.py"`) holds the owner's stated preferences. When the file is absent, every consult below is skipped and the report says `Mind: not installed`; nothing else changes.

The rule for every ruling the orchestrator makes on the owner's behalf: **decide, cite, or propose**.

- Before deciding, run `python3 "$MIND" ask <terms>` with the terms in the table below. A note that settles the matter is applied and cited as `[per <ID>]` on the ruling line.
- With no settling note, decide anyway and mark the ruling `[provisional]`.
- At the end of the transition, every provisional ruling becomes a note (schema rules; scope by "true in another repository"; `source: orchestrator ruling <project>/<item> <date>`) delivered in one pull request on the data repo: `python3 "$MIND" propose <drafts...> --topic <project>-<item>-<stage>`. The PR URL goes on the progress line and in the report.
- A statement the owner makes during the run ("from now on", "never", "always", a direct answer) is not provisional: it goes through `python3 "$MIND" add` at once and is cited from then on.
- A ruling that would change the effect of a `must` note is never made provisionally. Apply the note; if it seems wrong, record `blocked_reason` and stop. Only `should`, `default`, and unstated matters may be ruled provisionally.

| transition | ask terms | what the answer governs |
|---|---|---|
| idea -> specced | `tier <subsystem words>`; `decision <subsystem words>` | the tier; prior decisions the spec must honour |
| impact_checked -> tests_planned | `scenario defensive critical` | rulings on test-plan flags |
| tests_planned -> implementing | `implementer brief tests` | brief wording and the test bound |
| implementing -> evaluated | `review ruling <finding words>` | rulings on whole-branch and review-tests findings |
| evaluated -> shipped | `ship tier reviewers` | the ship tier |
| shipped -> review_processed | `process-review etiquette`; `<finding words>` | decision-table rulings |

Open proposals are listed by `python3 "$MIND" proposals`; the orchestrator never merges one.
```

Then: in "Units of work", the sentence about rulings on the progress line gains: "Each ruling ends with `[per <ID>]` or `[provisional]`; a transition that produced provisional rulings ends its line with `proposal: <PR url>`." In "Guardrails", replace the bullet "Before asking the owner anything, consult the `mind` plugin if installed, then the project's auto-memory and `CLAUDE.md`. If the answer is there, apply it and cite the source. If not, ask once, then record the answer." with "Before asking the owner anything, follow §Consult the mind, then the project's `CLAUDE.md`. If the answer is there, apply and cite it. If not, ask once, then `add` the answer." In "Report shape", add two lines after `Rulings:`: `Mind: consulted <IDs or none | not installed>` and `Proposals: <PR url or none>`.

- [ ] **Step 4: Run the orchestrator suite** — [ ] **Step 5: Commit** `docs(orchestrator): consult the mind; decide, cite, or propose`

---

### Task 2: dev-kit commands

**Files:** Modify `plugins/dev-kit/commands/process-review.md`, `commands/ship.md`, `commands/plan-tests.md`, `commands/check-impact.md`

- [ ] **process-review.md**: in the `--autonomous` paragraph add: "Each row of the decision table carries a `Basis` column: the mind note ID that settles it (`python3 "$(dirname "$CLAUDE_PLUGIN_ROOT")/mind/scripts/mind.py" ask <finding words>`) or `provisional`. The posted table keeps the column. The command ends by listing the provisional rows; the orchestrator proposes them on the data repo, an interactive run tells the owner." Add the `Basis` column to the table template in the steps.
- [ ] **ship.md**: in the PR body template's Rulings section: "each line ends with `[per <ID>]` or `[provisional]`"; in the reviewer brief contract add: "A mind note that settles a style or process point makes it not a finding; cite the ID instead."
- [ ] **plan-tests.md** and **check-impact.md**: where the caller rules on red flags or conflicts, add: "Each ruling ends with `[per <ID>]` (a mind note) or `[provisional]`."
- [ ] Commit `docs(dev-kit): rulings cite mind notes or are provisional`

---

### Task 3: dev-kit agents

**Files:** Modify `plugins/dev-kit/agents/pr-reviewer.md`, `agents/test-quality-reviewer.md`, `agents/behavioral-impact-checker.md`, `agents/test-scenario-planner.md`

- [ ] Add to each, after the input contract, one paragraph:

```markdown
**Mind.** When `"$(dirname "$CLAUDE_PLUGIN_ROOT")/mind/scripts/mind.py"` exists, run `python3 <that path> ask <key terms>` before filing a preference-shaped finding (style, process, test volume, model choice, wording). A note that settles it is cited (`per <ID>`) and not filed as a finding. Correctness findings are never withheld on this basis.
```

- [ ] Commit `docs(dev-kit): reviewers consult the mind before preference-shaped findings`

---

### Task 4: Release

**Files:** both `plugin.json`, `.claude-plugin/marketplace.json`, `CHANGELOG.md`, root `README.md`, `plugins/orchestrator/README.md`, `plugins/dev-kit/README.md`

- [ ] Versions to `1.4.0`; changelog `## 1.4.0 (2026-09-12)` with one bullet per task; orchestrator README gains a "Consult the mind" paragraph and the two new report lines; dev-kit README gains a "Mind" paragraph (Basis column, reviewer consult, ruling suffixes); root README's "Changing a plugin" section unchanged, the plugin list shows 1.4.0 for both.
- [ ] Hygiene grep; orchestrator suite green; `claude plugin validate .`.
- [ ] Commit `docs: 1.4.0 for orchestrator and dev-kit (mind integration)`

## Self-review

Spec §3 items 1-7 map to Task 1; §4 to Tasks 2 and 3; §6 to Task 1's test; §7 to Task 4. No code with tests changes. The `MIND` path convention is identical in every file.
