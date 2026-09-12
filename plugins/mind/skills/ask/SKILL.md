---
name: ask
description: Use before asking the owner any question about how they want work done, and whenever the user asks "what does the mind say about" a topic; searches the owner's notes and cites IDs
---

# Mind: ask

Read-only. Requires `MIND_REPO`.

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/mind.py" ask <terms>`. Terms are matched case-insensitively against title and body; use two to four distinct words.
2. No hit: rerun with `--all` to search every project. Still nothing: say "the mind has no note on this" and ask the owner; afterwards run `/mind:remember`.
3. For any hit that matters, read the full note file under `<MIND_HOME>` and apply it. Cite IDs in the answer ("per PREF-REV-003"; project notes as `<slug>/GOT-DEPLOY-004`).
4. Two notes that disagree: quote both IDs and ask the owner which supersedes. `--drafts` lists notes awaiting acceptance; the owner accepts one with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/mind.py" accept <ID>`. `--limit N` widens the list; `--stage <stage>` narrows it; a `[precedence]` row says which of two conflicting notes wins.
