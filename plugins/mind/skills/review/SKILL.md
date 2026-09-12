---
name: review
description: Use when the owner wants to re-affirm, weaken, revise, or retire aging mind notes; walks stale notes one at a time
---

# Mind: review

Requires `MIND_REPO`. Script: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/mind.py"`.

1. `mind.py stale --days 90` (add `--all` for every project). Nothing stale: say so and stop.
2. For each row, oldest first, show the note's title, first paragraph, Why, and age. Ask which verb, one note per message; do not lead the witness and never suggest retiring a `must` note on age alone.
   - reinforce: `mind.py affirm <ID>`
   - weaken: `mind.py affirm <ID> --strength <one step lower>`
   - revise: draft the replacement with `supersedes: <ID>` and run `mind.py propose <draft> --topic revise-<ID>`
   - retire: `mind.py retire <ID>`
3. Report the verbs applied and any proposal PR URL.
