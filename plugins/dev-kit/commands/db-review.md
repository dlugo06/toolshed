---
name: db-review
description: Run a database design and query analysis review.
---

Run a database design and query analysis review.

Launch the **dba** agent to analyze table design, ORM usage, query patterns, indexing strategy, and migration management.

## Steps

1. Launch the `dba` agent (subagent_type: "dev-kit:dba") in the background
2. The agent will review models, queries, connection config, and migrations, writing findings to `.dev/DBA_REVIEW.md`
3. Report completion to the user with a brief summary of key findings
