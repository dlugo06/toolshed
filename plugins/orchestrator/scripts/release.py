#!/usr/bin/env python3
"""Release coordinator helper: the deterministic half of `/orchestrator:release`.

Two subcommands, stdlib only, every network read through `gh`:

  release.py prs --project-dir <dir> [--phases <glob>] [--pr N ...] [--json]
      Inventory of the open PRs on one project: the PRD item and tier each one
      belongs to, the surfaces it touches, the pipeline evidence on disk and on
      the PR, the owner steps its body asks for, the decision-table rows the
      run rejected, pairwise file overlaps, and a suggested batch split.

  release.py proposals --repo <mind data checkout> [--since YYYY-MM-DD] [--json]
      Audit of the merged `propose/*` pull requests on the mind data repo:
      which proposed notes the owner kept, dropped or edited before merging,
      plus the proposals still open.

The judgement (what a deviation means, how to order a batch, what a dropped
note says about the proposal rules) stays with the skill; this script only
reads and tabulates.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import subprocess
import sys
from itertools import combinations
from pathlib import Path

ITEM_RE = re.compile(r"\bp(\d+[a-z]?)-(\d{3})\b", re.IGNORECASE)
NOTE_ID_RE = re.compile(r"\b([A-Z]{2,5}-[A-Z]{2,7}-\d{3})\b")
DECISION_HEADER = "decision table"
APPEND_ONLY = ("docs/prd/", "docs/behaviour-register.md")


# --- pure helpers -----------------------------------------------------------


def item_id_from(branch: str, title: str) -> str | None:
    """The PRD item id named by a branch or a PR title, upper-cased."""
    for text in (branch, title):
        m = ITEM_RE.search(text or "")
        if m:
            return f"P{m.group(1).upper()}-{m.group(2)}"
    return None


def classify_files(files: list[str]) -> list[str]:
    """Deploy surfaces a change touches: bridge, config, docs, python (sorted)."""
    surfaces: set[str] = set()
    for f in files:
        name = f.rsplit("/", 1)[-1]
        if f.startswith("src/whatsapp/") and f.endswith(".js") or f.startswith("tests/bridge/"):
            surfaces.add("bridge")
        if (
            name in ("package.json", "package-lock.json", "Dockerfile", ".env.example")
            or name.startswith("requirements")
            or f.startswith("alembic/")
        ):
            surfaces.add("config")
        if f.endswith(".py"):
            surfaces.add("python")
        if f.endswith(".md") or f.startswith("docs/"):
            surfaces.add("docs")
    return sorted(surfaces)


def overlaps(prs: list[dict]) -> list[dict]:
    """Pairs of PRs that touch the same file, code and append-only docs apart."""
    rows = []
    for a, b in combinations(prs, 2):
        shared = sorted(set(a["files"]) & set(b["files"]))
        if not shared:
            continue
        docs = [f for f in shared if f.startswith(APPEND_ONLY)]
        code = [f for f in shared if f not in docs]
        rows.append({"a": a["number"], "b": b["number"], "code": code, "docs": docs})
    return rows


def owner_steps(body: str) -> dict[str, list[str]]:
    """Owner steps a PR body asks for: a human/owner heading, and open checkboxes."""
    pre: list[str] = []
    post: list[str] = []
    section = None
    for line in (body or "").splitlines():
        if line.startswith("#"):
            heading = line.lower()
            section = "owner" if ("human" in heading or "owner" in heading) else None
            continue
        stripped = line.strip()
        if section == "owner" and stripped.startswith("- "):
            pre.append(stripped[2:].strip())
        elif stripped.startswith("- [ ] "):
            post.append(stripped[6:].strip())
    return {"pre_merge": pre, "post_deploy": post}


def decision_rows(comment: str) -> list[dict]:
    """Rows of a process-review decision table comment (empty when it is not one)."""
    if DECISION_HEADER not in (comment or "").lower():
        return []
    rows = []
    for line in comment.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7 or not cells[0].isdigit():
            continue
        rows.append(
            {
                "n": cells[0],
                "file": cells[2],
                "comment": cells[3],
                "decision": cells[4],
                "basis": cells[5],
                "reasoning": cells[6],
            }
        )
    return rows


def _branch_docs(project_dir: Path, branch: str, runner) -> list[str]:
    """Tracked docs paths on origin/<branch>, or [] when git cannot answer."""
    if not branch:
        return []
    try:
        out = runner(
            ["git", "ls-tree", "-r", "--name-only", f"origin/{branch}", "docs/superpowers"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return out.split()


def report_dirs(project_dir: Path) -> list[Path]:
    """The project's `.dev` plus every run worktree's `.dev` (gitignored, per checkout)."""
    dirs = [project_dir / ".dev"]
    dirs += sorted(p for p in project_dir.glob(".claude/worktrees/*/.dev") if p.is_dir())
    return dirs


def evidence_for(
    project_dir: Path, pr: int, item: str | None, branch: str, runner=subprocess.run
) -> dict:
    """Pipeline artifacts for one PR, or None per missing artifact.

    Specs and plans are looked up on the PR branch (they are tracked and may not
    be on the default branch yet); the `.dev` reports are gitignored and looked up
    in the project's `.dev` and in every run worktree's `.dev`.
    """
    slug = (branch or "").replace("/", "-")
    compact = item.replace("-", "").lower() if item else None
    short = item.lower() if item else None
    docs = _branch_docs(project_dir, branch, runner)

    def doc(kind: str) -> str | None:
        if not compact:
            return None
        hits = sorted(d for d in docs if d.startswith(f"docs/superpowers/{kind}/") and compact in d)
        hits = [h for h in hits if "research" not in h] or hits
        return hits[0] if hits else None

    def first(*patterns: str) -> str | None:
        for base in report_dirs(project_dir):
            for pattern in patterns:
                hits = sorted(glob.glob(str(base / pattern)))
                if hits:
                    return str(Path(hits[0]).relative_to(project_dir))
        return None

    return {
        "spec": doc("specs"),
        "plan": doc("plans"),
        "impact": first(f"BEHAVIORAL_IMPACT_{slug}*.md"),
        "test_plan": first(f"test-plan-{slug}*.md"),
        "branch_review": first(
            f"REVIEW_{slug}*.md", f"review-{slug}*.md", f"WHOLE_BRANCH_REVIEW_{slug}*.md",
            *( [f"BRANCH_REVIEW_{short}*.md", f"review-{short}*.md"] if short else [] ),
        ),
        "pr_review": first(f"PR_REVIEW_PR{pr}.md"),
        "silent_failure": first(f"SILENT_FAILURE_REVIEW_PR{pr}.md"),
        "security": first(f"SECURITY_REVIEW_PR{pr}.md"),
    }


# --- inventory -------------------------------------------------------------


def build_inventory(
    project_dir: Path, prs: list[dict], items: list[dict], runner=subprocess.run
) -> list[dict]:
    """One row per PR joining the PR, its PRD item and the evidence."""
    by_id = {i["id"]: i for i in items}
    rows = []
    for pr in prs:
        item_id = item_id_from(pr.get("headRefName", ""), pr.get("title", ""))
        item = by_id.get(item_id) if item_id else None
        files = [f["path"] if isinstance(f, dict) else f for f in pr.get("files", [])]
        tables = [decision_rows(c.get("body", "")) for c in pr.get("comments", [])]
        table = next((t for t in tables if t), [])
        rows.append(
            {
                "pr": pr["number"],
                "title": pr.get("title", ""),
                "branch": pr.get("headRefName", ""),
                "draft": bool(pr.get("isDraft")),
                "mergeable": pr.get("mergeable"),
                "created": (pr.get("createdAt") or "")[:10],
                "item": item_id if item else item_id,
                "tier": item.get("tier") if item else None,
                "stage": item.get("stage") if item else None,
                "depends_on": list(item.get("depends_on", [])) if item else [],
                "steps_to_verify": list(item.get("steps_to_verify", [])) if item else [],
                "files": files,
                "surfaces": classify_files(files),
                "reviews": len(pr.get("reviews") or []),
                "decision_table": bool(table),
                "rejected": [r for r in table if r["decision"].startswith("Reject")],
                "owner_steps": owner_steps(pr.get("body", "")),
                "evidence": evidence_for(project_dir, pr["number"], item_id, pr.get("headRefName", ""), runner),
            }
        )
    return sorted(rows, key=lambda r: r["pr"])


def suggest_batches(rows: list[dict]) -> list[dict]:
    """A first split: docs+python together, bridge together, owner-gated PRs alone."""
    gated = [r["pr"] for r in rows if r["owner_steps"]["pre_merge"]]
    bridge = [r["pr"] for r in rows if "bridge" in r["surfaces"] and r["pr"] not in gated]
    quote = [r["pr"] for r in rows if r["pr"] not in gated and r["pr"] not in bridge]
    batches = []
    names = iter("ABCDEFGH")
    if quote:
        batches.append({"name": next(names), "kind": "docs and python quote path", "prs": sorted(quote)})
    if bridge:
        batches.append({"name": next(names), "kind": "bridge", "prs": sorted(bridge)})
    for pr in sorted(gated):
        batches.append({"name": next(names), "kind": "owner pre-merge steps (one PR per batch)", "prs": [pr]})
    return batches


def _flags(ev: dict) -> str:
    return " ".join(f"{k}:{'yes' if v else 'no'}" for k, v in ev.items())


def render_inventory(rows: list[dict], overlap_rows: list[dict]) -> str:
    out = ["## Open PRs", "", "| PR | item | tier | branch | surfaces | files | reviews | created |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(
            f"| {r['pr']} | {r['item'] or '-'} | {r['tier'] or '-'} | {r['branch']} | "
            f"{', '.join(r['surfaces']) or '-'} | {len(r['files'])} | {r['reviews']} | {r['created']} |"
        )
    out += ["", "## Evidence per PR", ""]
    for r in rows:
        out.append(f"- #{r['pr']}: {_flags(r['evidence'])} decision_table:{'yes' if r['decision_table'] else 'no'} reviews:{r['reviews']}")
        if r["depends_on"]:
            out.append(f"  depends_on: {', '.join(r['depends_on'])}")
        for step in r["owner_steps"]["pre_merge"]:
            out.append(f"  owner pre-merge: {step}")
        for step in r["owner_steps"]["post_deploy"]:
            out.append(f"  post-deploy check: {step}")
        for step in r["steps_to_verify"]:
            out.append(f"  steps_to_verify: {step}")
    out += ["", "## Rejected review findings", ""]
    any_rejected = False
    for r in rows:
        for row in r["rejected"]:
            any_rejected = True
            out.append(f"- #{r['pr']} row {row['n']} ({row['file']}): {row['comment']}. {row['decision']} [{row['basis']}]: {row['reasoning']}")
    if not any_rejected:
        out.append("none")
    out += ["", "## File overlaps", ""]
    if not overlap_rows:
        out.append("none")
    for o in overlap_rows:
        code = ", ".join(o["code"]) or "-"
        docs = ", ".join(o["docs"]) or "-"
        out.append(f"- #{o['a']} x #{o['b']}: code: {code}; append-only docs: {docs}")
    out += ["", "## Suggested batches (first cut)", ""]
    for b in suggest_batches(rows):
        out.append(f"- Batch {b['name']} ({b['kind']}): {', '.join('#' + str(p) for p in b['prs'])}")
    return "\n".join(out) + "\n"


# --- proposal audit --------------------------------------------------------


def _note_id(text: str) -> str | None:
    m = NOTE_ID_RE.search(text or "")
    return m.group(1) if m else None


def audit_proposal(number: int, title: str, commits: list[dict]) -> dict:
    """Kept / dropped / edited note IDs of one merged proposal PR, from its commits."""
    proposed: list[str] = []
    dropped: list[str] = []
    edited: list[str] = []
    other: list[str] = []
    for c in commits:
        head = c.get("messageHeadline", "")
        if head.startswith("mind: propose "):
            nid = _note_id(head)
            if nid:
                proposed.append(nid)
            continue
        if head.startswith("Delete ") or head.startswith("mind: drop "):
            nid = _note_id(head)
            if nid and nid not in dropped:
                dropped.append(nid)
            continue
        if head.startswith("Update "):
            nid = _note_id(head)
            if nid:
                edited.append(nid)
            continue
        other.append(head)
    kept = [p for p in proposed if p not in dropped]
    return {
        "pr": number,
        "title": title,
        "proposed": proposed,
        "kept": kept,
        "dropped": dropped,
        "edited": edited,
        "other": other,
    }


def render_proposals(audits: list[dict], open_proposals: list[str]) -> str:
    out = ["## Merged proposal PRs", "", "| PR | title | proposed | kept | dropped | edited |", "|---|---|---|---|---|---|"]
    proposed = kept = 0
    for a in audits:
        proposed += len(a["proposed"])
        kept += len(a["kept"])
        out.append(
            f"| {a['pr']} | {a['title']} | {len(a['proposed'])} | {len(a['kept'])} | "
            f"{', '.join(a['dropped']) or '-'} | {', '.join(a['edited']) or '-'} |"
        )
    rate = f"{round(100 * kept / proposed)}%" if proposed else "n/a"
    out += ["", f"Kept {kept} of {proposed} proposed ({rate}).", ""]
    others = [(a["pr"], o) for a in audits for o in a["other"]]
    if others:
        out.append("Other commits on the proposal branches (owner edits to read):")
        out += [f"- #{pr}: {o}" for pr, o in others]
        out.append("")
    out += ["## Open proposals", ""]
    out += [f"- {p}" for p in open_proposals] or ["none"]
    return "\n".join(out) + "\n"


# --- gh access -------------------------------------------------------------


def _gh(args: list[str], cwd: Path, runner) -> object:
    out = runner(
        ["gh", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout
    return json.loads(out)


def fetch_prs(project_dir: Path, numbers: list[int], runner) -> list[dict]:
    listing = _gh(
        ["pr", "list", "--state", "open", "--limit", "50", "--json",
         "number,title,headRefName,body,isDraft,mergeable,createdAt"],
        project_dir,
        runner,
    )
    prs = [p for p in listing if not numbers or p["number"] in numbers]
    for pr in prs:
        detail = _gh(["pr", "view", str(pr["number"]), "--json", "files,reviews,comments"], project_dir, runner)
        pr.update(detail)
    return prs


def load_items(project_dir: Path, phases: str) -> list[dict]:
    items: list[dict] = []
    for path in sorted(project_dir.glob(phases)):
        data = json.loads(Path(path).read_text())
        items.extend(data.get("items", []))
        for sub in data.get("sub_phases", {}).values():
            items.extend(sub.get("items", []))
    return items


def fetch_proposal_audits(repo: Path, since: str | None, runner) -> tuple[list[dict], list[str]]:
    merged = _gh(
        ["pr", "list", "--state", "merged", "--limit", "50", "--search", "head:propose/",
         "--json", "number,title,headRefName,mergedAt"],
        repo,
        runner,
    )
    audits = []
    for pr in sorted(merged, key=lambda p: p["number"]):
        if since and (pr.get("mergedAt") or "")[:10] < since:
            continue
        detail = _gh(["pr", "view", str(pr["number"]), "--json", "commits"], repo, runner)
        audits.append(audit_proposal(pr["number"], pr["title"], detail.get("commits", [])))
    opened = _gh(
        ["pr", "list", "--state", "open", "--limit", "50", "--search", "head:propose/",
         "--json", "number,headRefName,url"],
        repo,
        runner,
    )
    open_rows = [f"{p['headRefName']} {p['url']}" for p in sorted(opened, key=lambda p: p["number"])]
    return audits, open_rows


# --- CLI ---------------------------------------------------------------------


def main(argv: list[str] | None = None, runner=subprocess.run) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prs", help="inventory of the open PRs on one project")
    p.add_argument("--project-dir", required=True)
    p.add_argument("--phases", default="docs/prd/phase*.json")
    p.add_argument("--pr", type=int, action="append", default=[], help="limit to these PR numbers")
    p.add_argument("--json", action="store_true")
    q = sub.add_parser("proposals", help="audit merged propose/* PRs on the mind data repo")
    q.add_argument("--repo", required=True, help="path to the mind data checkout")
    q.add_argument("--since", help="only PRs merged on or after this date (YYYY-MM-DD)")
    q.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "prs":
            project_dir = Path(args.project_dir).expanduser().resolve()
            prs = fetch_prs(project_dir, args.pr, runner)
            rows = build_inventory(project_dir, prs, load_items(project_dir, args.phases), runner)
            pairs = overlaps([{"number": r["pr"], "files": r["files"]} for r in rows])
            if args.json:
                print(json.dumps({"prs": rows, "overlaps": pairs, "batches": suggest_batches(rows)}, indent=1))
            else:
                print(render_inventory(rows, pairs), end="")
        else:
            audits, open_rows = fetch_proposal_audits(Path(args.repo).expanduser().resolve(), args.since, runner)
            if args.json:
                print(json.dumps({"merged": audits, "open": open_rows}, indent=1))
            else:
                print(render_proposals(audits, open_rows), end="")
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"release: gh call failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
