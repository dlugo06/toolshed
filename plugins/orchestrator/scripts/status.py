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
    status.py --git           also check that recorded branches exist
    status.py --project NAME  limit to one project

Stdlib only. Never writes anything.
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
    "tests_planned": "implement (subagent-driven-development, worktree)",
    "implementing": "evaluate (fresh-context evaluator)",
    "evaluated": "ship (/dev-kit:ship, tier chosen by orchestrator)",
    "tests_reviewed": "ship (/dev-kit:ship, tier chosen by orchestrator)",
    "shipped": "process review (/dev-kit:process-review <pr>)",
    "review_processed": "merge (HUMAN GATE)",
    "merged": "mark passes (HUMAN GATE: deployed and verified by the owner)",
    "done": "none: done",
}

HUMAN_GATES = {"review_processed", "merged"}
SKIP_DISPOSITIONS = {"defer": "deferred", "drop": "dropped", "fold": "folded"}


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
    return (
        row["stage"] not in ("idea", "done")
        and not row["next"].startswith("skip:")
        and not row["next"].startswith("blocked: P")
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


def build_rows(
    project: str, phase_files: list[Path], check_git: bool = False
) -> list[dict]:
    """Open items of one project with their next action, in phase-file order."""
    items = collect_items(phase_files)
    open_ids = {i["id"] for i in items if not i["passes"]}
    branches = _local_branches(phase_files[0].parent) if check_git else set()
    rows = []
    for item in items:
        if item["passes"]:
            continue
        branch = item.get("branch") or ""
        row = {
            "project": project,
            "id": item["id"],
            "phase": item["phase"],
            "title": item.get("title", ""),
            "stage": item["stage"],
            "disposition": item.get("disposition", ""),
            "branch": branch,
            "branch_exists": bool(branch and branch in branches) if check_git else None,
            "pr": item.get("pr", ""),
            "next": next_action(item, open_ids),
        }
        rows.append(row)
    return rows


def build_world(
    projects: dict[str, list[Path]], check_git: bool = False
) -> dict[str, dict]:
    """Per project: duplicate ids, open rows, in-flight rows."""
    world: dict[str, dict] = {}
    for name, files in projects.items():
        rows = build_rows(name, files, check_git=check_git)
        world[name] = {
            "duplicate_ids": find_duplicate_ids(collect_items(files)),
            "open": rows,
            "in_flight": [r for r in rows if is_in_flight(r)],
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
        lines.append(f"- {name}: {len(data['open'])} open, {len(flight)} in flight")
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
    world = build_world(projects, check_git=args.git)
    if args.json:
        print(json.dumps(world, indent=1))
    elif args.brief:
        print(build_brief(world))
    else:
        print(build_report(world, check_git=args.git))
    return 0


if __name__ == "__main__":
    sys.exit(main())
