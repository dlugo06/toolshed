---
name: lint
description: Use to check the mind's notes for malformed files, dangling references, duplicates, stubs, stale notes, and injection budget overflow
---

# Mind: lint

Read-only. Requires `MIND_REPO`. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/mind.py" lint --days 180` and report the rows verbatim. For each row say the one command that fixes it: `mind.py retire` for a duplicate, `mind.py affirm` for a stale note, an edit plus `mind.py sync` for a malformed or mismatched file or a stub project, `mind.py propose` with `supersedes` for an unsuperseded pair. Never fix anything without the owner asking.
