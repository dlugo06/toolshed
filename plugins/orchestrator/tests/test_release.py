"""Tests for the release coordinator helper (scripts/release.py)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from release import (  # noqa: E402
    audit_proposal,
    build_inventory,
    classify_files,
    decision_rows,
    evidence_for,
    item_id_from,
    overlaps,
    owner_steps,
    render_inventory,
    render_proposals,
    suggest_batches,
)


def _fake_runner(responses: dict[str, str]):
    """A subprocess.run stand-in keyed by the joined argv."""

    class Result:
        def __init__(self, out: str) -> None:
            self.stdout = out
            self.returncode = 0

    def run(cmd, **kwargs):
        key = " ".join(cmd)
        for prefix, out in responses.items():
            if key.startswith(prefix):
                return Result(out)
        raise FileNotFoundError(key)

    return run


# --- pure helpers -----------------------------------------------------------


def test_item_id_from_branch_and_title():
    assert item_id_from("fix/p5-048-url-selects-variant", "anything") == "P5-048"
    assert item_id_from("feat/other", "feat(ai): note (P5-034)") == "P5-034"
    assert item_id_from("chore/prd-triage-2026-09-15-night", "docs(prd): triage") is None
    assert item_id_from("fix/p2b-003-x", "") == "P2B-003"


def test_classify_files_names_every_surface():
    assert classify_files(["docs/prd/x.progress.md", "docs/behaviour-register.md"]) == ["docs"]
    assert classify_files(["src/whatsapp/bridge.js", "tests/bridge/a.test.js"]) == ["bridge"]
    assert classify_files(["src/ai/parser.py", "docs/a.md"]) == ["docs", "python"]
    assert classify_files(["requirements.txt", "src/config.py"]) == ["config", "python"]
    assert classify_files(["alembic/versions/0009_x.py"]) == ["config", "python"]
    assert classify_files([".env.example", "package.json"]) == ["config"]


def test_overlaps_split_code_from_append_only_docs():
    prs = [
        {"number": 1, "files": ["src/a.py", "docs/prd/p.progress.md", "docs/behaviour-register.md"]},
        {"number": 2, "files": ["src/a.py", "docs/prd/p.progress.md", "tests/t.py"]},
        {"number": 3, "files": ["docs/behaviour-register.md"]},
    ]
    rows = overlaps(prs)
    assert rows == [
        {"a": 1, "b": 2, "code": ["src/a.py"], "docs": ["docs/prd/p.progress.md"]},
        {"a": 1, "b": 3, "code": [], "docs": ["docs/behaviour-register.md"]},
    ]


def test_owner_steps_reads_human_heading_and_open_checkboxes():
    body = (
        "## Summary\n- x\n\n## Human steps before merge (owner)\n"
        "- Set `KEY` in Railway\n- Register zip\n\n## Rulings\n- a [provisional]\n\n"
        "## Test plan\n- [x] suites\n- [ ] Production (human gate): send one URL\n"
    )
    assert owner_steps(body) == {
        "pre_merge": ["Set `KEY` in Railway", "Register zip"],
        "post_deploy": ["Production (human gate): send one URL"],
    }


def test_owner_steps_empty_when_absent():
    assert owner_steps("## Summary\n- nothing\n") == {"pre_merge": [], "post_deploy": []}


def test_decision_rows_returns_rejected_and_fixed():
    comment = (
        "## process-review decision table (2026-09-16)\n\n"
        "| # | Source | File:Line | Comment (truncated) | Decision | Basis | Reasoning |\n"
        "|---|---|---|---|---|---|---|\n"
        "| 1 | review | a.py:1 | note dropped | Reject (decided) | per item | why one |\n"
        "| 2 | review | b.py:2 | log field | Fix | provisional | why two |\n"
        "| 3 | review | c.py:3 | stock | Reject | provisional | why three |\n"
    )
    rows = decision_rows(comment)
    assert [r["n"] for r in rows] == ["1", "2", "3"]
    assert [r["decision"] for r in rows] == ["Reject (decided)", "Fix", "Reject"]
    assert rows[0]["comment"] == "note dropped"
    assert rows[2]["basis"] == "provisional"
    rejected = [r for r in rows if r["decision"].startswith("Reject")]
    assert [r["n"] for r in rejected] == ["1", "3"]


def test_decision_rows_ignores_non_table_comment():
    assert decision_rows("just a comment\n| not | a | table |\n") == []


def _git_runner(docs: list[str]):
    def run(cmd, **kwargs):
        class R:
            stdout = "\n".join(docs) + "\n"
        if cmd[:2] == ["git", "ls-tree"]:
            return R()
        raise FileNotFoundError(" ".join(cmd))
    return run


def test_evidence_for_reads_branch_docs_and_worktree_reports(tmp_path: Path):
    proj = tmp_path
    wt = proj / ".claude/worktrees/zen-keller-1/.dev"
    wt.mkdir(parents=True)
    (proj / ".dev").mkdir()
    (wt / "BEHAVIORAL_IMPACT_fix-p5-048-url.md").write_text("i")
    (wt / "test-plan-fix-p5-048-url.md").write_text("t")
    (wt / "WHOLE_BRANCH_REVIEW_fix-p5-048-url.md").write_text("r")
    (proj / ".dev/PR_REVIEW_PR120.md").write_text("r")
    docs = [
        "docs/superpowers/specs/2026-09-15-p5047-bigbox-api-swap-research.md",
        "docs/superpowers/specs/2026-09-15-p5048-x-design.md",
        "docs/superpowers/plans/2026-09-15-p5048-x.md",
    ]
    ev = evidence_for(proj, 120, "P5-048", "fix/p5-048-url", runner=_git_runner(docs))
    assert ev == {
        "spec": "docs/superpowers/specs/2026-09-15-p5048-x-design.md",
        "plan": "docs/superpowers/plans/2026-09-15-p5048-x.md",
        "impact": ".claude/worktrees/zen-keller-1/.dev/BEHAVIORAL_IMPACT_fix-p5-048-url.md",
        "test_plan": ".claude/worktrees/zen-keller-1/.dev/test-plan-fix-p5-048-url.md",
        "branch_review": ".claude/worktrees/zen-keller-1/.dev/WHOLE_BRANCH_REVIEW_fix-p5-048-url.md",
        "pr_review": ".dev/PR_REVIEW_PR120.md",
        "silent_failure": None,
        "security": None,
    }


def test_evidence_for_branch_review_by_item_name(tmp_path: Path):
    (tmp_path / ".dev").mkdir()
    (tmp_path / ".dev/BRANCH_REVIEW_p5-047.md").write_text("r")
    ev = evidence_for(tmp_path, 123, "P5-047", "fix/p5-047-bigbox", runner=_git_runner([]))
    assert ev["branch_review"] == ".dev/BRANCH_REVIEW_p5-047.md"
    assert ev["spec"] is None


def test_evidence_for_missing_everything(tmp_path: Path):
    ev = evidence_for(tmp_path, 7, None, "docs/x", runner=_git_runner([]))
    assert all(v is None for v in ev.values())


# --- inventory -------------------------------------------------------------


def _pr(number, branch, title, files, body="", reviews=1, comments=()):
    return {
        "number": number,
        "headRefName": branch,
        "title": title,
        "body": body,
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "createdAt": "2026-09-16T01:00:00Z",
        "files": [{"path": f, "additions": 1, "deletions": 0} for f in files],
        "reviews": [{"state": "COMMENTED"}] * reviews,
        "comments": [{"body": c} for c in comments],
    }


DECISION = (
    "## process-review decision table (2026-09-16)\n\n"
    "| # | Source | File:Line | Comment (truncated) | Decision | Basis | Reasoning |\n"
    "|---|---|---|---|---|---|---|\n"
    "| 1 | review | a.py:1 | dropped note | Reject | provisional | fine |\n"
)


def test_build_inventory_joins_prs_items_and_evidence(tmp_path: Path):
    items = [
        {"id": "P5-048", "tier": "fix", "stage": "review_processed", "depends_on": [],
         "steps_to_verify": ["Integration: no Nota", "Production: send an Amazon URL"]},
        {"id": "P5-049", "tier": "fix", "stage": "review_processed", "depends_on": ["P5-033"],
         "steps_to_verify": []},
    ]
    prs = [
        _pr(120, "fix/p5-048-url", "fix(ai): x (P5-048)", ["src/ai/a.py", "docs/behaviour-register.md"],
            body="## Test plan\n- [ ] Production (human gate): send one URL\n", comments=[DECISION]),
        _pr(122, "fix/p5-049-sentry", "fix(monitoring): y (P5-049)",
            ["src/whatsapp/bridge.js", "src/whatsapp/client.py", "docs/behaviour-register.md"]),
        _pr(119, "chore/prd-triage-2026-09-15", "docs(prd): triage", ["docs/prd/p5.json"], reviews=0),
    ]
    rows = build_inventory(tmp_path, prs, items, runner=_git_runner([]))
    by = {r["pr"]: r for r in rows}
    assert by[120]["item"] == "P5-048"
    assert by[120]["tier"] == "fix"
    assert by[120]["surfaces"] == ["docs", "python"]
    assert by[120]["decision_table"] is True
    assert by[120]["rejected"] == [{"n": "1", "file": "a.py:1", "comment": "dropped note",
                                    "decision": "Reject", "basis": "provisional", "reasoning": "fine"}]
    assert by[120]["owner_steps"]["post_deploy"] == ["Production (human gate): send one URL"]
    assert by[120]["steps_to_verify"] == ["Integration: no Nota", "Production: send an Amazon URL"]
    assert by[122]["surfaces"] == ["bridge", "docs", "python"]
    assert by[122]["depends_on"] == ["P5-033"]
    assert by[122]["decision_table"] is False
    assert by[119]["item"] is None
    assert by[119]["tier"] is None
    assert by[119]["reviews"] == 0
    assert by[119]["surfaces"] == ["docs"]


def test_suggest_batches_groups_docs_then_python_then_bridge_then_gated():
    rows = [
        {"pr": 119, "surfaces": ["docs"], "owner_steps": {"pre_merge": [], "post_deploy": []}, "depends_on": [], "item": None},
        {"pr": 120, "surfaces": ["docs", "python"], "owner_steps": {"pre_merge": [], "post_deploy": ["x"]}, "depends_on": [], "item": "P5-048"},
        {"pr": 122, "surfaces": ["bridge", "docs", "python"], "owner_steps": {"pre_merge": [], "post_deploy": []}, "depends_on": ["P5-033"], "item": "P5-049"},
        {"pr": 123, "surfaces": ["config", "docs", "python"], "owner_steps": {"pre_merge": ["Set key"], "post_deploy": []}, "depends_on": [], "item": "P5-047"},
        {"pr": 121, "surfaces": ["bridge", "python"], "owner_steps": {"pre_merge": [], "post_deploy": []}, "depends_on": [], "item": "P5-034"},
    ]
    batches = suggest_batches(rows)
    assert batches == [
        {"name": "A", "kind": "docs and python quote path", "prs": [119, 120]},
        {"name": "B", "kind": "bridge", "prs": [121, 122]},
        {"name": "C", "kind": "owner pre-merge steps (one PR per batch)", "prs": [123]},
    ]


def test_render_inventory_is_markdown_with_flags(tmp_path: Path):
    items = [{"id": "P5-048", "tier": "fix", "stage": "review_processed"}]
    prs = [_pr(120, "fix/p5-048-url", "fix(ai): x (P5-048)", ["src/ai/a.py"], comments=[DECISION])]
    rows = build_inventory(tmp_path, prs, items, runner=_git_runner([]))
    text = render_inventory(rows, overlaps([{"number": r["pr"], "files": r["files"]} for r in rows]))
    assert "| 120 | P5-048 | fix | fix/p5-048-url | python |" in text
    assert "spec:no plan:no impact:no test_plan:no branch_review:no pr_review:no" in text
    assert "decision_table:yes reviews:1" in text
    assert "## Rejected review findings" in text
    assert "- #120 row 1 (a.py:1): dropped note. Reject [provisional]: fine" in text
    assert "## File overlaps" in text
    assert "none" in text


# --- proposal audit --------------------------------------------------------


def test_audit_proposal_classifies_kept_dropped_edited():
    commits = [
        {"messageHeadline": "mind: propose PREF-DEV-019 A deterministic correction"},
        {"messageHeadline": "mind: propose GOT-PLAN-002 A backlog item filed"},
        {"messageHeadline": "mind: propose PREF-TEST-006 A cross-layer scenario"},
        {"messageHeadline": "Delete global/notes/PREF-TEST-006-a-cross-layer.md"},
        {"messageHeadline": "Delete global/notes/PREF-DEV-019-a-deterministic.md"},
        {"messageHeadline": "Update global/notes/GOT-PLAN-002-a-backlog-item.md"},
    ]
    audit = audit_proposal(12, "mind: window (3 notes)", commits)
    assert audit == {
        "pr": 12,
        "title": "mind: window (3 notes)",
        "proposed": ["PREF-DEV-019", "GOT-PLAN-002", "PREF-TEST-006"],
        "kept": ["GOT-PLAN-002"],
        "dropped": ["PREF-TEST-006", "PREF-DEV-019"],
        "edited": ["GOT-PLAN-002"],
        "other": [],
    }


def test_audit_proposal_with_project_scoped_ids_and_untouched():
    commits = [
        {"messageHeadline": "mind: propose DEC-PROD-001 A product URL whose sku"},
        {"messageHeadline": "mind: manual edits"},
    ]
    audit = audit_proposal(13, "t", commits)
    assert audit["kept"] == ["DEC-PROD-001"]
    assert audit["dropped"] == []
    assert audit["other"] == ["mind: manual edits"]


def test_audit_proposal_counts_mind_drop_commits_once():
    commits = [
        {"messageHeadline": "mind: propose PREF-PLAN-004 A"},
        {"messageHeadline": "mind: propose PREF-REV-006 B"},
        {"messageHeadline": "mind: drop PREF-PLAN-004 (fails PRIN-ID-001: agent working knowledge)"},
        {"messageHeadline": "mind: drop PREF-PLAN-004 (fails PRIN-ID-001: agent working knowledge)"},
    ]
    audit = audit_proposal(8, "t", commits)
    assert audit["dropped"] == ["PREF-PLAN-004"]
    assert audit["kept"] == ["PREF-REV-006"]
    assert audit["other"] == []


def test_render_proposals_totals_and_rate():
    audits = [
        {"pr": 12, "title": "a (3 notes)", "proposed": ["A", "B", "C"], "kept": ["A"], "dropped": ["B", "C"], "edited": [], "other": []},
        {"pr": 14, "title": "b (6 notes)", "proposed": ["D", "E"], "kept": ["D", "E"], "dropped": [], "edited": ["E"], "other": ["x"]},
    ]
    text = render_proposals(audits, open_proposals=["propose/2026-09-16-x https://x/pull/15"])
    assert "| 12 | a (3 notes) | 3 | 1 | B, C | - |" in text
    assert "| 14 | b (6 notes) | 2 | 2 | - | E |" in text
    assert "Kept 3 of 5 proposed (60%)" in text
    assert "## Open proposals" in text
    assert "- propose/2026-09-16-x https://x/pull/15" in text


# --- CLI ---------------------------------------------------------------------


def test_main_prs_uses_gh_and_phase_files(tmp_path: Path, capsys):
    from release import main

    prd = tmp_path / "docs/prd"
    prd.mkdir(parents=True)
    (prd / "phase5.json").write_text(json.dumps({"phase": "p5", "items": [
        {"id": "P5-048", "tier": "fix", "stage": "review_processed", "passes": False}]}))
    listing = json.dumps([{"number": 120, "headRefName": "fix/p5-048-url", "title": "x (P5-048)",
                           "body": "", "isDraft": False, "mergeable": "MERGEABLE",
                           "createdAt": "2026-09-16T01:00:00Z"}])
    view = json.dumps({"files": [{"path": "src/a.py"}], "reviews": [], "comments": []})
    runner = _fake_runner({"gh pr list": listing, "gh pr view 120": view, "git ls-tree": ""})
    rc = main(["prs", "--project-dir", str(tmp_path), "--phases", "docs/prd/phase*.json"], runner=runner)
    out = capsys.readouterr().out
    assert rc == 0
    assert "| 120 | P5-048 | fix | fix/p5-048-url | python |" in out
    assert "reviews:0" in out


def test_main_proposals_lists_merged_and_open(tmp_path: Path, capsys):
    from release import main

    merged = json.dumps([{"number": 12, "title": "mind: w (3 notes)", "headRefName": "propose/2026-09-16-w",
                          "mergedAt": "2026-09-16T22:00:00Z"}])
    commits = json.dumps({"commits": [
        {"messageHeadline": "mind: propose GOT-DEV-001 t"},
        {"messageHeadline": "Delete global/notes/GOT-DEV-001-t.md"}]})
    opened = json.dumps([{"number": 15, "headRefName": "propose/2026-09-16-x", "url": "https://x/pull/15"}])
    runner = _fake_runner({
        "gh pr list --state merged": merged,
        "gh pr view 12": commits,
        "gh pr list --state open": opened,
    })
    rc = main(["proposals", "--repo", str(tmp_path), "--since", "2026-09-16"], runner=runner)
    out = capsys.readouterr().out
    assert rc == 0
    assert "| 12 | mind: w (3 notes) | 1 | 0 | GOT-DEV-001 | - |" in out
    assert "Kept 0 of 1 proposed (0%)" in out
    assert "- propose/2026-09-16-x https://x/pull/15" in out
