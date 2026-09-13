---
name: remember
description: Use when the owner states a preference, rule, decision, gotcha, or reference worth keeping, or after the owner answers a question the mind could not; saves it to the mind's private notes repo
---

# Mind: remember

Writes one note. Requires `MIND_REPO` in the environment.

0. If the fact is something you inferred rather than the owner stated, do not use this skill; draft it and run `mind.py propose` instead (or leave it for `/mind:digest`).
1. Decide the scope with one test: would this be true in a different repository? Yes: `--scope global`. No: `--scope project`.
2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/mind.py" ask <three or four key terms>` first. If a note already says this, stop and cite it. If a note says something this replaces, put its ID in `supersedes`.
3. Read `<MIND_HOME>/schema.md` (the path is printed in the session-start protocol line) and draft the note as a markdown file in the scratchpad: frontmatter `title`, `type`, `stage`, `strength`, `supersedes`, `source`; body of one or two sentences, then `**Why:**` and `**How to apply:**`. No secrets. No employer or third-party names.
4. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/mind.py" add <draft path> --scope global|project`.
5. Report the printed line verbatim: it carries the ID and whether the push succeeded. If it says the project file is a stub, open `<MIND_HOME>/projects/<slug>/project.md`, fill `name`, `repo`, `stack`, `related`, and the body paragraph, then run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/mind.py" reindex` and `... sync` — `sync` commits the edit itself, so there is nothing else to stage or commit by hand.
