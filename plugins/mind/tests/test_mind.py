"""Tests for the mind plugin script (scripts/mind.py) and its hook."""
import dataclasses
import os
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "scripts"))

import mind  # noqa: E402


def test_hook_is_silent_without_mind_repo(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "MIND_REPO"}
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN)
    proc = subprocess.run(
        ["sh", str(PLUGIN / "scripts" / "session-start.sh")],
        env=env, capture_output=True, text=True, cwd=tmp_path,
    )
    assert proc.returncode == 0
    assert proc.stdout == ""


def test_main_unknown_subcommand_returns_2(capsys):
    assert mind.main(["bogus"], env={}, cwd=Path(".")) == 2
    assert "usage: mind.py" in capsys.readouterr().err


NOTE = """---
id: PREF-REV-003
title: Never auto-approve during process-review
type: preference
stage: review
scope: global
strength: must
status: accepted
affirmed: 2026-09-11
supersedes: null
source: CLAUDE.md, 2026-09-11
---
Never approve a PR on the owner's behalf.

**Why:** accountability.
"""


def test_parse_frontmatter_roundtrip():
    meta, body = mind.parse_frontmatter(NOTE)
    assert meta["id"] == "PREF-REV-003"
    assert meta["supersedes"] is None
    assert meta["source"] == "CLAUDE.md, 2026-09-11"
    assert body == "Never approve a PR on the owner's behalf.\n\n**Why:** accountability.\n"
    assert mind.render_frontmatter(meta, body) == NOTE


def test_parse_frontmatter_lists():
    meta, _ = mind.parse_frontmatter("---\naliases: [a-b, /x/y]\nstack: []\n---\n")
    assert meta["aliases"] == ["a-b", "/x/y"]
    assert meta["stack"] == []


def test_parse_frontmatter_missing_returns_empty_meta():
    assert mind.parse_frontmatter("just text\n") == ({}, "just text\n")


def test_validate_meta_reports_every_problem():
    errs = mind.validate_meta({"title": "x", "type": "wish", "stage": "review"})
    assert errs == [
        "type must be one of: principle, preference, decision, procedure, gotcha, reference",
        "missing required field: strength",
    ]
    assert mind.validate_meta({"title": "x", "type": "gotcha", "stage": "deployment", "strength": "should"}) == []


def test_validate_meta_rejects_blank_title_and_bad_stage():
    assert mind.validate_meta({"title": "", "type": "gotcha", "stage": "deployment", "strength": "should"}) == ["missing required field: title"]
    assert mind.validate_meta({"title": "x", "type": "principle", "stage": "wish", "strength": "must"}) == [
        "stage must be one of: identity, product, planning, development, testing, review, release, deployment, monitoring, security"]


def test_validate_meta_rejects_unknown_field():
    errs = mind.validate_meta({"title": "x", "type": "gotcha", "stage": "deployment", "strength": "should", "mood": "y"})
    assert errs == ["unknown field: mood"]


def test_load_notes_and_first_paragraph(tmp_path):
    (tmp_path / "PREF-REV-003-never.md").write_text(NOTE)
    notes = mind.load_notes(tmp_path)
    assert [n.id for n in notes] == ["PREF-REV-003"]
    assert notes[0].first_paragraph == "Never approve a PR on the owner's behalf."
    assert notes[0].strength == "must"


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    bare = tmp_path / "remote.git"
    _git(["init", "--bare", "-q", "--initial-branch=main", str(bare)], tmp_path)
    seed = tmp_path / "seed"
    _git(["clone", "-q", str(bare), str(seed)], tmp_path)
    _git(["config", "user.email", "t@example.com"], seed)
    _git(["config", "user.name", "t"], seed)
    (seed / "schema.md").write_text("# schema\n")
    _git(["add", "."], seed)
    _git(["commit", "-q", "-m", "init"], seed)
    _git(["push", "-q", "origin", "main"], seed)
    home = tmp_path / "home"
    env = {"MIND_REPO": str(bare), "MIND_HOME": str(home),
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    cfg = mind.Config.from_env(env, tmp_path)
    assert mind.ensure_checkout(cfg) is None
    return cfg, bare, seed


def test_config_from_env_defaults(tmp_path):
    cfg = mind.Config.from_env({"MIND_REPO": "git@x:y/z.git", "CLAUDE_PLUGIN_DATA": str(tmp_path)}, tmp_path)
    assert cfg.home == tmp_path / "repo"
    assert cfg.token is None
    cfg2 = mind.Config.from_env({"MIND_REPO": "u", "HOME": str(tmp_path)}, tmp_path)
    assert cfg2.home == tmp_path / ".mind" / "repo"


def test_config_requires_repo(tmp_path):
    with pytest.raises(mind.ConfigError, match="MIND_REPO is not set"):
        mind.Config.from_env({}, tmp_path)


def test_ensure_checkout_clones_once(repo):
    cfg, bare, _ = repo
    assert (cfg.home / "schema.md").read_text() == "# schema\n"
    assert mind.ensure_checkout(cfg) is None  # second call is a no-op


def test_ensure_checkout_reports_failure(tmp_path):
    cfg = mind.Config.from_env({"MIND_REPO": str(tmp_path / "missing.git"), "MIND_HOME": str(tmp_path / "h")}, tmp_path)
    msg = mind.ensure_checkout(cfg)
    assert msg.startswith("mind: clone failed")


def test_pull_offline_falls_back(repo, monkeypatch):
    cfg, bare, _ = repo
    monkeypatch.setattr(mind, "GIT_TIMEOUTS", {"clone": 30, "pull": 0.001, "push": 20})
    # A dead remote: point origin at a path that does not exist.
    _git(["remote", "set-url", "origin", str(cfg.home.parent / "gone.git")], cfg.home)
    msg = mind.pull(cfg)
    assert msg.startswith("mind: offline, using cached copy from ")


def test_sync_pushes_local_commits_and_retries_once(repo):
    cfg, bare, seed = repo
    (cfg.home / "a.md").write_text("a\n")
    mind.commit_all(cfg, "mind: add a")
    # Remote moves ahead in the meantime.
    (seed / "b.md").write_text("b\n")
    _git(["add", "."], seed); _git(["commit", "-q", "-m", "b"], seed); _git(["push", "-q"], seed)
    assert mind.sync(cfg) is None
    log = _git(["log", "--format=%s", "main"], bare).stdout.splitlines()
    assert log == ["mind: add a", "b", "init"]


def test_token_goes_on_command_line_not_disk(repo):
    cfg, bare, _ = repo
    cfg = dataclasses.replace(cfg, token="sekrit")
    args = mind.git_base_args(cfg)
    assert args[0:2] == ["git", "-c"]
    assert "sekrit" not in (cfg.home / ".git" / "config").read_text()


def test_sync_rebase_content_conflict_returns_offline_line(repo):
    """Two checkouts write the same relative path directly: a genuine content
    conflict, not a timeout. sync() must abort the rebase cleanly and report
    offline, leaving no rebase state or conflict markers behind."""
    cfg, bare, seed = repo
    (cfg.home / "clash.md").write_text("mine\n")
    mind.commit_all(cfg, "mind: add clash (local)")
    (seed / "clash.md").write_text("theirs\n")
    _git(["add", "."], seed)
    _git(["commit", "-q", "-m", "clash (remote)"], seed)
    _git(["push", "-q"], seed)
    msg = mind.sync(cfg)
    assert msg.startswith("mind: offline, using cached copy from ")
    status = _git(["status", "--porcelain"], cfg.home).stdout
    assert status == ""


def test_ensure_checkout_reports_failure_for_nonempty_home_without_git(tmp_path):
    """A crashed clone can leave a non-empty directory with no .git/: git
    clone refuses to clone into it, and ensure_checkout must report the
    failure rather than raising or leaving the target half-populated."""
    home = tmp_path / "h"
    home.mkdir(parents=True)
    (home / "stray.txt").write_text("leftover\n")
    cfg = mind.Config.from_env({"MIND_REPO": str(tmp_path / "missing.git"), "MIND_HOME": str(home)}, tmp_path)
    msg = mind.ensure_checkout(cfg)
    assert msg.startswith("mind: clone failed")
