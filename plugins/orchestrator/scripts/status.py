#!/usr/bin/env python3
"""Orchestrator world reader: deterministic status of every PRD item in every project.

Environment (both required unless passed as flags):
    TOOLSHED_PROJECTS_ROOT   directory whose immediate subdirectories are the projects
    TOOLSHED_PHASES_ROOT     glob, relative to each project, matching its PRD phase
                             files (for example: docs/prd/phase*.json)

Usage:
    status.py                 markdown report, one section per project
    status.py --brief         in-flight items only, for the SessionStart hook
    status.py --json          machine-readable
    status.py --git           also check that recorded branches exist and report
                             whether the local default branch is behind origin
    status.py --gh            also check review evidence on recorded PRs (needs gh)
    status.py --project NAME  limit to one project

Stdlib only. Never writes anything.

Stage is derived, not asserted. With --gh, an item whose recorded stage is at
or past "shipped" but whose PR has no review evidence (no reviews, no
comments, no .dev review report) is reported as blocked instead of at a human
gate. This is the check that was missing when an unreviewed PR reached the
merge gate (docs/incidents/2026-09-unreviewed-pr-and-budget-overrun.md).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

STAGES: list[str] = [
    "idea",
    "specced",
    "impact_checked",
    "tests_planned",
    "implementing",
    "evaluated",
    "tests_reviewed",
    "shipped",
    "review_processed",
    "merged",
    "done",
]

# stage -> the single transition that leaves it. See reference/orchestrator.md.
TRANSITIONS: dict[str, str] = {
    "idea": "spec (brainstorm + writing-plans)",
    "specced": "check impact (/dev-kit:check-impact)",
    "impact_checked": "plan tests (/dev-kit:plan-tests)",
    "tests_planned": "implement (implementers per tier, Sonnet)",
    "implementing": "review (whole-branch reviewer, then one fix dispatch)",
    "evaluated": "ship (/dev-kit:ship, tier chosen by orchestrator)",
    "tests_reviewed": "ship (/dev-kit:ship, tier chosen by orchestrator)",
    "shipped": "process review (/dev-kit:process-review <pr>)",
    "review_processed": "merge (HUMAN GATE)",
    "merged": "mark passes (HUMAN GATE: deployed and verified by the owner)",
    "done": "none: done",
}

HUMAN_GATES = {"review_processed", "merged"}
SKIP_DISPOSITIONS = {"defer": "deferred", "drop": "dropped", "fold": "folded"}

# Stages that claim the PR reviewers have run. Reaching them without review
# evidence is a defect in the record, not a position in the pipeline.
REVIEWED_STAGES = {"shipped", "review_processed"}
REVIEW_REPORT_PATTERNS = (
    ".dev/SILENT_FAILURE_REVIEW_PR{pr}.md",
    ".dev/SECURITY_REVIEW_PR{pr}.md",
)
UNREVIEWED = "blocked: PR #{pr} has no review evidence; run /dev-kit:ship reviewers, then process-review"


def pr_evidence(project_dir: Path, pr: int | str, runner=subprocess.run) -> dict:
    """Review evidence for one PR: counts from gh plus local .dev review reports.

    Returns {"reviews": int, "comments": int, "reports": [paths], "state": str}.
    A gh failure (offline, not authenticated, PR gone) yields zero counts and
    state "unknown"; the caller treats that as no evidence, which fails closed.
    """
    reviews = comments = 0
    state = "unknown"
    try:
        out = runner(
            ["gh", "pr", "view", str(pr), "--json", "reviews,comments,state"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        ).stdout
        data = json.loads(out)
        reviews = len(data.get("reviews") or [])
        comments = len(data.get("comments") or [])
        state = str(data.get("state") or "unknown")
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    reports = [
        p.format(pr=pr)
        for p in REVIEW_REPORT_PATTERNS
        if (project_dir / p.format(pr=pr)).exists()
    ]
    return {"reviews": reviews, "comments": comments, "reports": reports, "state": state}


def has_review_evidence(evidence: dict) -> bool:
    """A PR counts as reviewed when any reviewer left a trace."""
    return bool(evidence["reviews"] or evidence["comments"] or evidence["reports"])


class ConfigError(RuntimeError):
    """Raised when the required environment is missing."""


def resolve_config(root: str | None, phases: str | None) -> tuple[Path, str]:
    root = root or os.environ.get("TOOLSHED_PROJECTS_ROOT")
    phases = phases or os.environ.get("TOOLSHED_PHASES_ROOT")
    if not root:
        raise ConfigError("TOOLSHED_PROJECTS_ROOT is not set (or pass --root)")
    if not phases:
        raise ConfigError("TOOLSHED_PHASES_ROOT is not set (or pass --phases)")
    root_path = Path(root).expanduser()
    if not root_path.is_dir():
        raise ConfigError(f"TOOLSHED_PROJECTS_ROOT is not a directory: {root_path}")
    return root_path, phases


def discover_projects(root: Path, phases: str) -> dict[str, list[Path]]:
    """Immediate subdirectories of root that are git repos with at least one phase file."""
    projects: dict[str, list[Path]] = {}
    for child in sorted(root.iterdir()):
        if not child.is_dir() or not (child / ".git").exists():
            continue
        files = sorted(child.glob(phases))
        if files:
            projects[child.name] = files
    return projects


def _load_phase(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    phase = data.get("phase", path.stem)
    items = list(data.get("items", []))
    for key, sub in data.get("sub_phases", {}).items():
        for raw in sub.get("items", []):
            item = dict(raw)
            item.setdefault("sub_phase", key)
            items.append(item)
    for item in items:
        item["phase"] = phase
        item.setdefault("passes", False)
        item.setdefault("depends_on", [])
        if item["passes"]:
            item["stage"] = "done"
        else:
            item.setdefault("stage", "idea")
    return items


def collect_items(phase_files: list[Path]) -> list[dict]:
    """Every item from the given phase files, flattened and stage-defaulted."""
    items: list[dict] = []
    for path in phase_files:
        items.extend(_load_phase(path))
    return items


def find_duplicate_ids(items: list[dict]) -> list[str]:
    """IDs that appear more than once, each listed once, in first-seen order."""
    counts = Counter(i["id"] for i in items)
    seen: list[str] = []
    for item in items:
        if counts[item["id"]] > 1 and item["id"] not in seen:
            seen.append(item["id"])
    return seen


def next_action(item: dict, open_ids: set[str]) -> str:
    """The one thing the orchestrator would do next for this item."""
    if item["passes"] or item["stage"] == "done":
        return "none: done"
    disposition = str(item.get("disposition", "")).split(":")[0].strip()
    if disposition in SKIP_DISPOSITIONS:
        return f"skip: {SKIP_DISPOSITIONS[disposition]}"
    blockers = [d for d in item.get("depends_on", []) if d in open_ids]
    if blockers and item["stage"] == "idea":
        return "blocked: " + ", ".join(blockers)
    if item.get("blocked_reason") and item["stage"] not in HUMAN_GATES:
        return f"blocked: {item['blocked_reason']}"
    return TRANSITIONS.get(item["stage"], f"unknown stage: {item['stage']}")


def is_in_flight(row: dict) -> bool:
    """Past idea, not done, not skipped, not waiting on a dependency."""
    unreviewed = row["next"].startswith("blocked: PR #")
    dependency_blocked = row["next"].startswith("blocked: P") and not unreviewed
    return (
        row["stage"] not in ("idea", "done")
        and not row["next"].startswith("skip:")
        and not dependency_blocked
    )


def _local_branches(project_dir: Path) -> set[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(project_dir), "branch", "--format=%(refname:short)"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def default_branch_sync(project_dir: Path, runner=subprocess.run) -> dict | None:
    """Ahead/behind of the local default branch against its remote-tracking ref.

    Returns {"branch": name, "ahead": int, "behind": int} or None when the
    repository has no origin/<default> ref (or git fails). Never fetches:
    the numbers describe what the checkout already knows, which is what the
    orchestrator reads before cutting a branch. A stale local default branch
    once produced a SessionStart brief that listed four merged PRs as
    waiting at the merge gate.
    """
    for branch in ("main", "master"):
        try:
            out = runner(
                [
                    "git",
                    "-C",
                    str(project_dir),
                    "rev-list",
                    "--left-right",
                    "--count",
                    f"{branch}...origin/{branch}",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        parts = out.split()
        if len(parts) != 2:
            continue
        return {"branch": branch, "ahead": int(parts[0]), "behind": int(parts[1])}
    return None


def _sync_note(sync: dict | None) -> str:
    """One parenthetical for the brief, empty when the default branch is current."""
    if not sync or not (sync["ahead"] or sync["behind"]):
        return ""
    bits = []
    if sync["behind"]:
        bits.append(f"behind origin by {sync['behind']}")
    if sync["ahead"]:
        bits.append(f"ahead of origin by {sync['ahead']}")
    return f" (local {sync['branch']} {', '.join(bits)}; fetch and fast-forward before cutting a branch)"


def _project_dir(phase_files: list[Path]) -> Path:
    """The git repository that owns the phase files (the directory holding .git)."""
    for parent in phase_files[0].parents:
        if (parent / ".git").exists():
            return parent
    return phase_files[0].parent


def build_rows(
    project: str,
    phase_files: list[Path],
    check_git: bool = False,
    check_gh: bool = False,
    runner=subprocess.run,
) -> list[dict]:
    """Open items of one project with their next action, in phase-file order.

    With ``check_gh``, items at a reviewed stage whose PR shows no review
    evidence get ``next`` replaced by the UNREVIEWED block and ``evidence``
    filled in; the recorded stage is reported as is so the mismatch is visible.
    """
    items = collect_items(phase_files)
    open_ids = {i["id"] for i in items if not i["passes"]}
    project_dir = _project_dir(phase_files)
    branches = _local_branches(project_dir) if check_git else set()
    rows = []
    for item in items:
        if item["passes"]:
            continue
        branch = item.get("branch") or ""
        pr = item.get("pr", "")
        row = {
            "project": project,
            "id": item["id"],
            "phase": item["phase"],
            "title": item.get("title", ""),
            "stage": item["stage"],
            "disposition": item.get("disposition", ""),
            "branch": branch,
            "branch_exists": bool(branch and branch in branches) if check_git else None,
            "pr": pr,
            "next": next_action(item, open_ids),
            "evidence": None,
        }
        if check_gh and pr and item["stage"] in REVIEWED_STAGES:
            evidence = pr_evidence(project_dir, pr, runner=runner)
            row["evidence"] = evidence
            if not has_review_evidence(evidence):
                row["next"] = UNREVIEWED.format(pr=pr)
        rows.append(row)
    return rows


def build_world(
    projects: dict[str, list[Path]],
    check_git: bool = False,
    check_gh: bool = False,
    runner=subprocess.run,
) -> dict[str, dict]:
    """Per project: duplicate ids, open rows, in-flight rows."""
    world: dict[str, dict] = {}
    for name, files in projects.items():
        rows = build_rows(
            name, files, check_git=check_git, check_gh=check_gh, runner=runner
        )
        world[name] = {
            "duplicate_ids": find_duplicate_ids(collect_items(files)),
            "open": rows,
            "in_flight": [r for r in rows if is_in_flight(r)],
            "sync": default_branch_sync(_project_dir(files), runner=runner)
            if check_git
            else None,
        }
    return world


def _row_line(r: dict, check_git: bool) -> str:
    branch = r["branch"]
    if check_git and branch and not r["branch_exists"]:
        branch += " (missing)"
    return (
        f"| {r['id']} | {r['stage']} | {r['disposition']} "
        f"| {branch} | {r['pr']} | {r['next']} |"
    )


def build_report(world: dict[str, dict], check_git: bool = False) -> str:
    """Full markdown report, one section per project."""
    lines: list[str] = []
    for name, data in world.items():
        lines.append(f"## {name}")
        if data["duplicate_ids"]:
            lines.append(
                "DUPLICATE IDS (fix before assigning stages): "
                + ", ".join(data["duplicate_ids"])
            )
        lines.append(
            f"Open items: {len(data['open'])}, in flight: {len(data['in_flight'])}"
            + _sync_note(data.get("sync"))
        )
        lines.append("")
        lines.append("| id | stage | disp | branch | pr | next |")
        lines.append("|---|---|---|---|---|---|")
        lines.extend(_row_line(r, check_git) for r in data["open"])
        lines.append("")
    if not world:
        lines.append("No projects with phase files found.")
    return "\n".join(lines).rstrip()


def build_brief(world: dict[str, dict]) -> str:
    """Short SessionStart text: what is on the hook across all projects."""
    lines: list[str] = ["# Orchestrator: work on the hook"]
    any_flight = False
    for name, data in world.items():
        flight = data["in_flight"]
        dupes = data["duplicate_ids"]
        if not flight and not dupes:
            continue
        any_flight = True
        lines.append(
            f"- {name}: {len(data['open'])} open, {len(flight)} in flight"
            + _sync_note(data.get("sync"))
        )
        if dupes:
            lines.append(f"  - DUPLICATE IDS: {', '.join(dupes)}")
        for r in flight:
            lines.append(f"  - {r['id']} [{r['stage']}] -> {r['next']}")
    if not any_flight:
        total = sum(len(d["open"]) for d in world.values())
        lines.append(
            f"- nothing in flight across {len(world)} project(s), {total} open items. "
            "Run /orchestrator:next to pick one."
        )
    else:
        lines.append("Run /orchestrator:advance <project>/<id> to move one item.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="overrides TOOLSHED_PROJECTS_ROOT")
    parser.add_argument("--phases", help="overrides TOOLSHED_PHASES_ROOT")
    parser.add_argument("--project", help="limit to one project directory name")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--brief", action="store_true")
    parser.add_argument("--git", action="store_true")
    parser.add_argument(
        "--gh",
        action="store_true",
        help="check review evidence on recorded PRs; needs gh, fails closed",
    )
    args = parser.parse_args(argv)
    try:
        root, phases = resolve_config(args.root, args.phases)
    except ConfigError as exc:
        print(f"orchestrator: {exc}", file=sys.stderr)
        return 1
    projects = discover_projects(root, phases)
    if args.project:
        projects = {k: v for k, v in projects.items() if k == args.project}
        if not projects:
            print(f"orchestrator: no project named {args.project}", file=sys.stderr)
            return 1
    world = build_world(projects, check_git=args.git, check_gh=args.gh)
    if args.json:
        print(json.dumps(world, indent=1))
    elif args.brief:
        print(build_brief(world))
    else:
        print(build_report(world, check_git=args.git))
    return 0


if __name__ == "__main__":
    sys.exit(main())
