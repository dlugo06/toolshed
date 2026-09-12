"""Tests for the orchestrator world reader (scripts/status.py)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from status import (  # noqa: E402
    STAGES,
    UNREVIEWED,
    ConfigError,
    build_brief,
    build_report,
    build_rows,
    build_world,
    collect_items,
    discover_projects,
    find_duplicate_ids,
    has_review_evidence,
    is_in_flight,
    main,
    next_action,
    pr_evidence,
    resolve_config,
)

PHASES = "docs/prd/phase*.json"


def _project(root: Path, name: str, phases: dict[str, dict]) -> Path:
    proj = root / name
    (proj / ".git").mkdir(parents=True)
    prd = proj / "docs" / "prd"
    prd.mkdir(parents=True)
    for fname, payload in phases.items():
        (prd / f"{fname}.json").write_text(json.dumps(payload))
    return proj


@pytest.fixture
def root(tmp_path: Path) -> Path:
    _project(
        tmp_path,
        "alpha",
        {
            "phase2-ai": {
                "phase": "phase2-ai",
                "sub_phases": {
                    "2b": {
                        "items": [
                            {"id": "P2b-001", "title": "MCP server", "passes": False},
                            {"id": "P2b-002", "title": "Done", "passes": True},
                        ]
                    }
                },
            },
            "phase5-hard": {
                "phase": "phase5-hard",
                "items": [
                    {
                        "id": "P5-001",
                        "title": "Jest",
                        "passes": False,
                        "stage": "implementing",
                        "branch": "feat/p5001-jest",
                    },
                    {
                        "id": "P5-006",
                        "title": "Webhook",
                        "passes": False,
                        "depends_on": ["P5-011"],
                    },
                    {
                        "id": "P5-011",
                        "title": "FastAPI",
                        "passes": False,
                        "disposition": "fold: SP3",
                    },
                    {
                        "id": "P5-015",
                        "title": "Routing",
                        "passes": False,
                        "stage": "merged",
                        "pr": 67,
                    },
                ],
            },
        },
    )
    _project(
        tmp_path,
        "beta",
        {
            "phase1": {
                "items": [
                    {"id": "B-001", "title": "a", "passes": False},
                    {"id": "B-001", "title": "b", "passes": False},
                ]
            }
        },
    )
    # not a git repo: ignored
    (tmp_path / "notes" / "docs" / "prd").mkdir(parents=True)
    (tmp_path / "notes" / "docs" / "prd" / "phase1.json").write_text("{}")
    # git repo with no phase files: ignored
    (tmp_path / "empty" / ".git").mkdir(parents=True)
    return tmp_path


def test_discover_projects_requires_git_and_phase_files(root: Path):
    projects = discover_projects(root, PHASES)
    assert list(projects) == ["alpha", "beta"]
    assert [p.name for p in projects["alpha"]] == ["phase2-ai.json", "phase5-hard.json"]


def test_resolve_config_reads_env_and_rejects_missing(monkeypatch, root: Path):
    monkeypatch.delenv("TOOLSHED_PROJECTS_ROOT", raising=False)
    monkeypatch.delenv("TOOLSHED_PHASES_ROOT", raising=False)
    with pytest.raises(ConfigError, match="TOOLSHED_PROJECTS_ROOT"):
        resolve_config(None, None)
    monkeypatch.setenv("TOOLSHED_PROJECTS_ROOT", str(root))
    with pytest.raises(ConfigError, match="TOOLSHED_PHASES_ROOT"):
        resolve_config(None, None)
    monkeypatch.setenv("TOOLSHED_PHASES_ROOT", PHASES)
    assert resolve_config(None, None) == (root, PHASES)
    with pytest.raises(ConfigError, match="not a directory"):
        resolve_config(str(root / "missing"), PHASES)


def test_collect_items_flattens_sub_phases_and_defaults_stage(root: Path):
    files = discover_projects(root, PHASES)["alpha"]
    by_id = {i["id"]: i for i in collect_items(files)}
    assert by_id["P2b-001"]["stage"] == "idea"
    assert by_id["P2b-001"]["phase"] == "phase2-ai"
    assert by_id["P5-001"]["stage"] == "implementing"
    assert by_id["P2b-002"]["stage"] == "done"


def test_find_duplicate_ids_reports_each_once(root: Path):
    files = discover_projects(root, PHASES)["beta"]
    assert find_duplicate_ids(collect_items(files)) == ["B-001"]


def test_next_action_blockers_dispositions_and_gates(root: Path):
    files = discover_projects(root, PHASES)["alpha"]
    items = collect_items(files)
    by_id = {i["id"]: i for i in items}
    open_ids = {i["id"] for i in items if not i["passes"]}
    assert next_action(by_id["P5-006"], open_ids) == "blocked: P5-011"
    assert next_action(by_id["P5-011"], open_ids) == "skip: folded"
    assert next_action(by_id["P5-001"], open_ids) == "review (whole-branch reviewer, then one fix dispatch)"
    assert next_action(by_id["P5-015"], open_ids).startswith("mark passes (HUMAN GATE")
    assert next_action(by_id["P2b-002"], open_ids) == "none: done"


def test_blocked_reason_blocks_non_gate_stages_only():
    open_ids: set[str] = set()
    item = {"id": "X", "passes": False, "stage": "implementing", "blocked_reason": "DB probe missing"}
    assert next_action(item, open_ids) == "blocked: DB probe missing"
    gate = {"id": "Y", "passes": False, "stage": "merged", "blocked_reason": "old note"}
    assert next_action(gate, open_ids).startswith("mark passes")


def test_in_flight_excludes_idea_skipped_and_dependency_blocked(root: Path):
    rows = build_rows("alpha", discover_projects(root, PHASES)["alpha"])
    flight = {r["id"] for r in rows if is_in_flight(r)}
    assert flight == {"P5-001", "P5-015"}


def test_stage_order_has_no_e2e_stage():
    assert STAGES[0] == "idea"
    assert STAGES[-1] == "done"
    assert "e2e_verified" not in STAGES
    assert STAGES.index("merged") == STAGES.index("review_processed") + 1


def test_report_and_brief(root: Path):
    world = build_world(discover_projects(root, PHASES))
    report = build_report(world)
    assert "## alpha" in report and "## beta" in report
    assert "DUPLICATE IDS (fix before assigning stages): B-001" in report
    assert "Open items: 5, in flight: 2" in report
    assert "P2b-002" not in report
    brief = build_brief(world)
    assert "- alpha: 5 open, 2 in flight" in brief
    assert "P5-001 [implementing] -> review (whole-branch reviewer, then one fix dispatch)" in brief
    assert "P2b-001" not in brief
    assert "DUPLICATE IDS: B-001" in brief


def test_brief_when_nothing_in_flight(tmp_path: Path):
    _project(tmp_path, "solo", {"phase1": {"items": [{"id": "S-1", "title": "t", "passes": False}]}})
    brief = build_brief(build_world(discover_projects(tmp_path, PHASES)))
    assert "nothing in flight across 1 project(s), 1 open items" in brief


class _FakeRun:
    """Stand-in for subprocess.run that answers `gh pr view` from a table."""

    def __init__(self, answers: dict[str, dict | Exception]):
        self.answers = answers
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        answer = self.answers[argv[3]]
        if isinstance(answer, Exception):
            raise answer

        class _Done:
            stdout = json.dumps(answer)

        return _Done()


def _reviewed_project(tmp_path: Path) -> Path:
    return _project(
        tmp_path,
        "gamma",
        {
            "phase1": {
                "items": [
                    {"id": "G-1", "title": "reviewed", "passes": False, "stage": "review_processed", "pr": 84},
                    {"id": "G-2", "title": "unreviewed", "passes": False, "stage": "review_processed", "pr": 85},
                    {"id": "G-3", "title": "report only", "passes": False, "stage": "shipped", "pr": 86},
                    {"id": "G-4", "title": "gh down", "passes": False, "stage": "shipped", "pr": 87},
                    {"id": "G-5", "title": "not shipped yet", "passes": False, "stage": "implementing", "pr": 88},
                ]
            }
        },
    )


def test_pr_evidence_counts_reviews_comments_and_reports(tmp_path: Path):
    proj = _reviewed_project(tmp_path)
    (proj / ".dev").mkdir()
    (proj / ".dev" / "SECURITY_REVIEW_PR86.md").write_text("x")
    run = _FakeRun({"86": {"reviews": [], "comments": [], "state": "OPEN"}})
    ev = pr_evidence(proj, 86, runner=run)
    assert ev == {"reviews": 0, "comments": 0, "reports": [".dev/SECURITY_REVIEW_PR86.md"], "state": "OPEN"}
    assert has_review_evidence(ev) is True
    assert run.calls[0][:4] == ["gh", "pr", "view", "86"]


def test_pr_evidence_fails_closed_when_gh_fails(tmp_path: Path):
    proj = _reviewed_project(tmp_path)
    run = _FakeRun({"87": OSError("gh not found")})
    ev = pr_evidence(proj, 87, runner=run)
    assert ev == {"reviews": 0, "comments": 0, "reports": [], "state": "unknown"}
    assert has_review_evidence(ev) is False


def test_gh_check_blocks_reviewed_stages_without_evidence(tmp_path: Path):
    proj = _reviewed_project(tmp_path)
    (proj / ".dev").mkdir()
    (proj / ".dev" / "SILENT_FAILURE_REVIEW_PR86.md").write_text("x")
    run = _FakeRun(
        {
            "84": {"reviews": [{"id": 1}], "comments": [], "state": "OPEN"},
            "85": {"reviews": [], "comments": [], "state": "OPEN"},
            "86": {"reviews": [], "comments": [], "state": "OPEN"},
            "87": OSError("offline"),
        }
    )
    rows = {r["id"]: r for r in build_rows("gamma", discover_projects(tmp_path, PHASES)["gamma"], check_gh=True, runner=run)}
    assert rows["G-1"]["next"] == "merge (HUMAN GATE)"
    assert rows["G-2"]["next"] == UNREVIEWED.format(pr=85)
    assert rows["G-2"]["stage"] == "review_processed"  # the mismatch stays visible
    assert rows["G-3"]["next"] == "process review (/dev-kit:process-review <pr>)"
    assert rows["G-4"]["next"] == UNREVIEWED.format(pr=87)
    assert rows["G-5"]["evidence"] is None  # not a reviewed stage: gh never called
    assert [c[3] for c in run.calls] == ["84", "85", "86", "87"]


def test_without_gh_flag_stage_is_trusted(tmp_path: Path):
    _reviewed_project(tmp_path)
    rows = {r["id"]: r for r in build_rows("gamma", discover_projects(tmp_path, PHASES)["gamma"])}
    assert rows["G-2"]["next"] == "merge (HUMAN GATE)"
    assert rows["G-2"]["evidence"] is None


def test_brief_shows_unreviewed_block(tmp_path: Path):
    _reviewed_project(tmp_path)
    run = _FakeRun({str(n): {"reviews": [], "comments": [], "state": "OPEN"} for n in (84, 85, 86, 87)})
    brief = build_brief(build_world(discover_projects(tmp_path, PHASES), check_gh=True, runner=run))
    assert "G-2 [review_processed] -> " + UNREVIEWED.format(pr=85) in brief
    assert "merge (HUMAN GATE)" not in brief


def test_main_exit_codes_and_json(root: Path, capsys, monkeypatch):
    monkeypatch.delenv("TOOLSHED_PROJECTS_ROOT", raising=False)
    monkeypatch.delenv("TOOLSHED_PHASES_ROOT", raising=False)
    assert main([]) == 1
    assert "TOOLSHED_PROJECTS_ROOT" in capsys.readouterr().err
    assert main(["--root", str(root), "--phases", PHASES, "--project", "nope"]) == 1
    assert main(["--root", str(root), "--phases", PHASES, "--project", "alpha", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert list(payload) == ["alpha"]
    assert [r["id"] for r in payload["alpha"]["in_flight"]] == ["P5-001", "P5-015"]


class _SyncRun:
    """Stand-in for subprocess.run answering `git rev-list --left-right --count`."""

    def __init__(self, stdout: str | None):
        self.stdout = stdout

    def __call__(self, argv, **kwargs):
        if self.stdout is None:
            raise OSError("no origin")

        class _Done:
            stdout = self.stdout

        return _Done()


def test_default_branch_sync_reports_ahead_and_behind(tmp_path: Path):
    from status import _sync_note, default_branch_sync

    sync = default_branch_sync(tmp_path, runner=_SyncRun("2\t1\n"))
    assert sync == {"branch": "main", "ahead": 2, "behind": 1}
    assert _sync_note(sync) == (
        " (local main behind origin by 1, ahead of origin by 2; "
        "fetch and fast-forward before cutting a branch)"
    )
    assert _sync_note({"branch": "main", "ahead": 0, "behind": 0}) == ""
    assert default_branch_sync(tmp_path, runner=_SyncRun(None)) is None
    assert _sync_note(None) == ""


def test_brief_and_report_carry_the_sync_note(root: Path, monkeypatch):
    import status as mod

    monkeypatch.setattr(
        mod, "default_branch_sync", lambda d, runner=None: {"branch": "master", "ahead": 0, "behind": 3}
    )
    world = build_world(discover_projects(root, PHASES), check_git=True)
    brief = build_brief(world)
    assert "- alpha: 5 open, 2 in flight (local master behind origin by 3; fetch and fast-forward before cutting a branch)" in brief
    report = build_report(world, check_git=True)
    assert "Open items: 5, in flight: 2 (local master behind origin by 3;" in report
    world = build_world(discover_projects(root, PHASES))
    assert world["alpha"]["sync"] is None
