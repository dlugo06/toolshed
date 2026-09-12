# Note schema

```yaml
---
id: PREF-REV-003
title: Never auto-approve during process-review
type: preference      # principle | preference | decision | procedure | gotcha | reference
stage: review         # identity | product | planning | development | testing | review | release | deployment | monitoring | security
scope: global         # global | project:<slug>
strength: must        # must | should | default | optional
status: accepted      # draft | accepted | superseded | deprecated
affirmed: 2026-09-11  # last date the owner confirmed it
supersedes: null      # ID of the note this replaces, if any
source: CLAUDE.md, acme-api, 2026-09-11   # where the claim came from
---
One or two sentences stating the claim.

**Why:** the reason, with the incident or evidence if there is one.
**How to apply:** what an agent does differently because of this note.
**Related:** [[PREF-REV-004-do-not-resolve-pr-threads]]
```

Type semantics:

- **principle**: always true, MUST or MUST NOT.
- **preference**: default choice when several are valid; applied without asking.
- **decision**: dated record with context, options, rationale, consequences; superseded, never edited.
- **procedure**: a checklist.
- **gotcha**: a trap with the evidence that proved it.
- **reference**: URLs, IDs, dashboards.

ID scheme: `<TYPE>-<STAGE>-<NNN>`, with type codes PRIN, PREF, DEC, PROC,
GOT, REF and stage codes ID, PROD, PLAN, DEV, TEST, REV, REL, DEPLOY, MON,
SEC. Numbers are assigned per scope folder, so a project note is cited with
its slug: `acme-api/GOT-DEPLOY-004`. A global note is cited bare.

Status semantics: only `accepted` notes appear in injected indexes. `draft`
notes are counted in the injection ("N drafts await acceptance") and listed
by `/mind:ask --drafts`. `superseded` and `deprecated` notes stay on disk
for history and never inject.

Required fields on `add`: `title`, `type`, `stage`, `strength`. Defaults:
`status: accepted`, `affirmed: today`, `scope` from the `--scope` flag,
`source: session <date>, <slug>`. The script rejects unknown enum values.

## Writing rules

- One claim per note. The title is the claim, stated plainly.
- Body: one or two sentences stating the claim, then a `**Why:**` line and a
  `**How to apply:**` line. Add `**Related:**` only when it links another
  note.
- Reuse an existing `stage` value instead of inventing a new one.
- Never edit an accepted note in place to change its claim: write a new
  note and set its `supersedes` to the old note's ID instead.
- No secrets: no token, password, DSN key, or credential value in any note.
  A `reference` note may say where a secret lives, never what it is.
- No employer name, third-party company name, or other private-repo name in
  any note.
