# Behaviour register

One row per user-observable rule the product currently enforces. This file is what `/dev-kit:check-impact` diffs a plan against, instead of re-reading every design spec on every run. Copy it to `docs/behaviour-register.md` in your project.

A row is a rule someone outside the code could observe: what a message line says, which inputs are dropped or routed where, what a payload field carries, when a placeholder appears. Internal structure (a helper's signature, a module layout) is not a row.

## How rows are added and changed

- `/dev-kit:check-impact` proposes rows for every rule the plan introduces or changes, in the "Register additions" section of its report, with the branch's spec as the source.
- `/dev-kit:ship` appends those rows (marked with the PR number) before the PR is opened, on the branch, as a `docs:` commit. A changed rule edits its row in place and records the superseding spec; a removed rule keeps its row with `removed by <spec>` so the history stays greppable.
- Seeding an existing project: `/dev-kit:check-impact --seed-register` reads every spec once and writes the initial file. Review it by hand; a seeded row without a pinning test is marked `test: none`.

## Columns

| column | meaning |
|---|---|
| `id` | stable, `BR-<n>`; never reused |
| `surface` | where the rule is observed: `message`, `payload`, `routing`, `filter`, `storage`, `notification`, or a project-specific surface name |
| `rule` | one sentence, present tense, with the literal strings or predicate it fixes |
| `set by` | the spec (path) and PR that established the current form |
| `pinned by` | the test that fails if the rule changes (`file::test_name`), or `none` |

## Register

| id | surface | rule | set by | pinned by |
|---|---|---|---|---|
| BR-1 | message | TODO: example — every vendor line reads `<n>. <name>` where `<name>` is the Spanish description when one exists, else the product name | `docs/superpowers/specs/<date>-<name>.md`, PR #n | `tests/.../test_x.py::test_y` |
