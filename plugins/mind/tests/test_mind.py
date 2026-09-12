"""Tests for the mind plugin script (scripts/mind.py) and its hook."""
import dataclasses
import datetime as dt
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "scripts"))

import mind  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_git_env(monkeypatch):
    """Keep every git call in this suite off the developer's real git config
    and identity, whatever machine or CI runner is running the tests."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@example.com")


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


def test_parse_frontmatter_only_parses_lists_for_stack_aliases_related(tmp_path):
    """A title, supersedes ID, or source string that happens to look like a
    YAML list (e.g. `title: [WIP]`) must stay a plain string: only stack,
    aliases, and related are ever list fields."""
    meta, _ = mind.parse_frontmatter(
        "---\ntitle: [WIP]\nsupersedes: [PREF-REV-001]\nstack: [python]\naliases: [a]\nrelated: [b]\n---\n")
    assert meta["title"] == "[WIP]"
    assert meta["supersedes"] == "[PREF-REV-001]"
    assert meta["stack"] == ["python"]
    assert meta["aliases"] == ["a"]
    assert meta["related"] == ["b"]


def test_validate_meta_rejects_non_string_title():
    errs = mind.validate_meta({"title": ["WIP"], "type": "gotcha", "stage": "deployment", "strength": "should"})
    assert errs == ["title must be a string"]


def test_cmd_add_handles_bracketed_title_as_a_plain_string_not_a_crash(repo, tmp_path):
    """title is no longer a list field: `[WIP]` stays the literal string
    title instead of reaching _kebab() as a list and crashing on .lower()."""
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    draft = tmp_path / "d.md"
    draft.write_text("---\ntitle: [WIP]\ntype: gotcha\nstage: deployment\nstrength: should\n---\nb\n")
    out = mind.cmd_add(cfg, draft, "global", None, tmp_path)
    assert out == "mind: added GOT-DEPLOY-001 (global), pushed"
    meta, _ = mind.parse_frontmatter(next(mind.global_notes_dir(cfg).glob("GOT-DEPLOY-001-*.md")).read_text())
    assert meta["title"] == "[WIP]"


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
    env = {"MIND_REPO": str(bare), "MIND_HOME": str(home)}
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


def test_config_env_defaults_to_os_environ(tmp_path):
    cfg = mind.Config.from_env({"MIND_REPO": "x"}, tmp_path)
    assert cfg.env is os.environ


def test_git_builds_environment_from_cfg_env_not_os_environ(repo):
    """git() must source its subprocess environment from cfg.env, so a
    Config built with a scoped env dict is not silently overridden by the
    live process environment (which the isolation fixture also patches)."""
    cfg, bare, _ = repo
    custom_env = dict(os.environ)
    custom_env.update({
        "GIT_AUTHOR_NAME": "custom-author", "GIT_AUTHOR_EMAIL": "custom@example.com",
        "GIT_COMMITTER_NAME": "custom-committer", "GIT_COMMITTER_EMAIL": "custom@example.com",
    })
    custom_cfg = dataclasses.replace(cfg, env=custom_env)
    (custom_cfg.home / "x.md").write_text("x\n")
    mind.commit_all(custom_cfg, "mind: test identity")
    author = _git(["log", "-1", "--format=%an"], custom_cfg.home).stdout.strip()
    assert author == "custom-author"


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


def test_cmd_init_against_empty_bare_repo_pushes_and_sets_upstream(tmp_path):
    """The documented first-run path: an empty data repo has no upstream
    branch yet. init must still push, not report offline forever."""
    bare = tmp_path / "remote.git"
    _git(["init", "--bare", "-q", "--initial-branch=main", str(bare)], tmp_path)
    home = tmp_path / "home"
    env = {"MIND_REPO": str(bare), "MIND_HOME": str(home)}
    cfg = mind.Config.from_env(env, tmp_path)
    assert mind.ensure_checkout(cfg) is None
    assert mind.cmd_init(cfg) == "mind: initialised global/ and projects/"
    log = _git(["log", "--format=%s", "main"], bare).stdout.splitlines()
    assert log == ["mind: init"]


def test_sync_commits_dirty_tree_before_pulling_or_pushing(repo):
    """The remember skill tells the agent to hand-edit project.md and then
    just run sync: sync must commit that edit itself, or the next pull
    --rebase anywhere refuses with a dirty working tree."""
    cfg, bare, _ = repo
    (cfg.home / "manual.md").write_text("edited by hand\n")
    assert mind.sync(cfg) is None
    log = _git(["log", "--format=%s"], cfg.home).stdout.splitlines()
    assert log[0] == "mind: manual edits"
    assert _git(["log", "--format=%s", "main"], bare).stdout.splitlines()[0] == "mind: manual edits"
    status = _git(["status", "--porcelain"], cfg.home).stdout
    assert status == ""


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


def test_git_sets_default_ssh_command_without_overriding_existing(repo, monkeypatch):
    cfg, _, _ = repo
    captured = {}
    real_popen = subprocess.Popen

    def spy(args, **kwargs):
        captured["env"] = kwargs.get("env")
        return real_popen(args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spy)
    mind.git(cfg, ["rev-parse", "--show-toplevel"], cfg.home, 5)
    assert captured["env"]["GIT_SSH_COMMAND"] == "ssh -oBatchMode=yes -oConnectTimeout=5"

    custom_cfg = dataclasses.replace(cfg, env=dict(os.environ, GIT_SSH_COMMAND="ssh -custom"))
    mind.git(custom_cfg, ["rev-parse", "--show-toplevel"], custom_cfg.home, 5)
    assert captured["env"]["GIT_SSH_COMMAND"] == "ssh -custom"


def test_git_uses_popen_with_closed_stdin_and_new_session(repo, monkeypatch):
    """git() must never wait on stdin (which would hang on an unknown ssh
    host-key prompt) and must run in its own process group, so a timeout can
    reach an orphaned ssh grandchild too, not just the direct git child."""
    cfg, _, _ = repo
    captured = {}
    real_popen = subprocess.Popen

    def spy(args, **kwargs):
        captured.update(kwargs)
        return real_popen(args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spy)
    mind.git(cfg, ["rev-parse", "--show-toplevel"], cfg.home, 5)
    assert captured.get("stdin") == subprocess.DEVNULL
    assert captured.get("start_new_session") is True


def test_git_kills_process_group_with_sigkill_on_timeout(repo, monkeypatch):
    cfg, _, _ = repo
    killed = {}
    real_killpg = os.killpg

    def spy_killpg(pgid, sig):
        killed["pgid"] = pgid
        killed["sig"] = sig
        return real_killpg(pgid, sig)

    monkeypatch.setattr(os, "killpg", spy_killpg)
    monkeypatch.setattr(mind, "git_base_args", lambda c: ["sleep"])
    with pytest.raises(subprocess.TimeoutExpired):
        mind.git(cfg, ["2"], cfg.home, 0.1)
    assert killed.get("sig") == signal.SIGKILL
    assert killed.get("pgid") is not None


def test_sync_retry_pull_timeout_returns_push_failed_line(repo, monkeypatch):
    """The push-retry pull --rebase must not raise TimeoutExpired uncaught:
    a slow link there should be treated as a failure, same as everywhere
    else, and sync() should report the push-failed line rather than crash."""
    cfg, bare, seed = repo
    (cfg.home / "a.md").write_text("a\n")
    mind.commit_all(cfg, "mind: add a")

    calls = {"push": 0, "pull_rebase": 0}
    real_push = mind.push
    real_git = mind.git

    def push_then_fail_once(c):
        calls["push"] += 1
        if calls["push"] == 1:
            return "mind: push failed, note is committed locally; it will push on the next remember or session start"
        return real_push(c)

    def fake_git(c, args, cwd, timeout):
        if args[:3] == ["pull", "-q", "--rebase"]:
            calls["pull_rebase"] += 1
            if calls["pull_rebase"] == 2:  # the retry pull, not the first one
                raise subprocess.TimeoutExpired(cmd="git pull", timeout=timeout)
        return real_git(c, args, cwd, timeout)

    monkeypatch.setattr(mind, "push", push_then_fail_once)
    monkeypatch.setattr(mind, "git", fake_git)
    msg = mind.sync(cfg)
    assert msg == "mind: push failed, note is committed locally; it will push on the next remember or session start"
    status = _git(["status", "--porcelain"], cfg.home).stdout
    assert status == ""  # no leftover rebase state


def test_token_goes_on_command_line_not_disk(repo):
    """A real git call with a token must neither expose it in argv (visible
    to `ps` on a shared cloud box) nor leave it written into .git/config."""
    cfg, bare, _ = repo
    cfg = dataclasses.replace(cfg, token="sekrit")
    mind.git(cfg, ["status"], cfg.home, 5)
    joined = " ".join(mind.git_base_args(cfg))
    assert "sekrit" not in joined
    assert "sekrit" not in (cfg.home / ".git" / "config").read_text()


def test_sync_rebase_content_conflict_returns_sync_conflict_message(repo):
    """Two checkouts write the same relative path directly: a genuine content
    conflict on a real (non-index) file. sync() must abort the rebase cleanly
    and report a sync conflict naming the file for hand resolution, leaving
    no rebase state or conflict markers behind."""
    cfg, bare, seed = repo
    (cfg.home / "clash.md").write_text("mine\n")
    mind.commit_all(cfg, "mind: add clash (local)")
    (seed / "clash.md").write_text("theirs\n")
    _git(["add", "."], seed)
    _git(["commit", "-q", "-m", "clash (remote)"], seed)
    _git(["push", "-q"], seed)
    msg = mind.sync(cfg)
    assert msg == f"mind: sync conflict in clash.md, resolve by hand in {cfg.home}"
    status = _git(["status", "--porcelain"], cfg.home).stdout
    assert status == ""


def test_ensure_checkout_reports_failure_for_nonempty_home_without_git(repo):
    """A crashed clone can leave a non-empty directory with no .git/: against
    a perfectly valid source, git clone still refuses to clone into a
    non-empty destination, and ensure_checkout must report that failure
    rather than raising or leaving the target half-populated."""
    cfg, bare, _ = repo
    home = cfg.home.parent / "nonempty_home"
    home.mkdir(parents=True)
    (home / "stray.txt").write_text("leftover\n")
    cfg2 = dataclasses.replace(cfg, home=home)
    msg = mind.ensure_checkout(cfg2)
    assert msg.startswith("mind: clone failed")
    assert not (home / ".git").exists()
    assert (home / "stray.txt").is_file()  # left untouched, not half-populated


def _write_project(cfg, slug, aliases=(), stack=("python",), body="Quotes from chat messages. Second sentence."):
    d = cfg.home / "projects" / slug
    (d / "notes").mkdir(parents=True, exist_ok=True)
    meta = {"slug": slug, "name": slug.title(), "repo": f"git@example.com:o/{slug}.git",
            "stack": list(stack), "aliases": list(aliases), "related": [], "updated": "2026-09-12"}
    (d / "project.md").write_text(mind.render_frontmatter(meta, body + "\n"))
    return d


def test_resolve_candidate_prefers_env_then_origin_then_dirs(tmp_path, repo):
    cfg, _, _ = repo
    work = tmp_path / "Some-Repo"
    work.mkdir()
    assert mind.resolve_candidate(cfg, work) == "some-repo"           # cwd basename
    _git(["init", "-q", str(work)], tmp_path)
    sub = work / "src"; sub.mkdir()
    assert mind.resolve_candidate(cfg, sub) == "some-repo"            # git top-level
    _git(["remote", "add", "origin", "git@example.com:o/Other.git"], work)
    assert mind.resolve_candidate(cfg, sub) == "other"                # origin
    forced = dataclasses.replace(cfg, project="Forced-Name")
    assert mind.resolve_candidate(forced, sub) == "forced-name"       # env, lowercased like the rest


def test_match_project_by_slug_and_alias(repo):
    cfg, _, _ = repo
    _write_project(cfg, "erp-quotes", aliases=("quotes-old", "/x/quotes"))
    assert mind.match_project(cfg, "erp-quotes") == "erp-quotes"
    assert mind.match_project(cfg, "quotes-old") == "erp-quotes"
    assert mind.match_project(cfg, "nothing") is None


def test_next_id_per_scope(repo):
    cfg, _, _ = repo
    g = mind.global_notes_dir(cfg); g.mkdir(parents=True)
    assert mind.next_id(g, "preference", "review") == "PREF-REV-001"
    (g / "PREF-REV-001-x.md").write_text(mind.render_frontmatter({"id": "PREF-REV-001", "title": "x", "type": "preference", "stage": "review", "strength": "must"}, "x\n"))
    (g / "PREF-REV-007-y.md").write_text(mind.render_frontmatter({"id": "PREF-REV-007", "title": "y", "type": "preference", "stage": "review", "strength": "must"}, "y\n"))
    assert mind.next_id(g, "preference", "review") == "PREF-REV-008"
    assert mind.next_id(g, "gotcha", "deployment") == "GOT-DEPLOY-001"
    (g / "PREF-REV-abc-z.md").write_text(mind.render_frontmatter({"id": "PREF-REV-abc", "title": "z", "type": "preference", "stage": "review", "strength": "must"}, "z\n"))
    assert mind.next_id(g, "preference", "review") == "PREF-REV-008"  # hand-edited id is skipped, never crashes
    p = mind.project_notes_dir(cfg, "erp-quotes"); p.mkdir(parents=True)
    assert mind.next_id(p, "preference", "review") == "PREF-REV-001"


def test_build_index_groups_by_stage_and_skips_drafts():
    def note(i, stage, strength, status="accepted"):
        return mind.Note(Path(i), {"id": i, "title": f"T {i}", "stage": stage, "strength": strength, "status": status}, "b\n")
    text = mind.build_index([note("PREF-REV-001", "review", "must"), note("GOT-DEV-001", "development", "should"),
                             note("PREF-REV-002", "review", "default", "draft")], "Global")
    assert text == (
        "# Global\n\n"
        "## development\n"
        "- GOT-DEV-001 | T GOT-DEV-001 | should\n\n"
        "## review\n"
        "- PREF-REV-001 | T PREF-REV-001 | must\n"
    )


def test_build_projects_index_and_reindex(repo):
    cfg, _, _ = repo
    _write_project(cfg, "erp-quotes")
    _write_project(cfg, "alpha", stack=("go",), body="Alpha thing.")
    mind.global_notes_dir(cfg).mkdir(parents=True)
    mind.reindex(cfg)
    assert (cfg.home / "projects" / "index.md").read_text() == (
        "# Projects\n\n"
        "- alpha | Alpha | go | Alpha thing.\n"
        "- erp-quotes | Erp-Quotes | python | Quotes from chat messages.\n"
    )
    assert (cfg.home / "global" / "index.md").read_text() == "# Global\n"
    assert (cfg.home / "projects" / "erp-quotes" / "index.md").read_text() == "# erp-quotes\n"


DRAFT = """---
title: Tests must assert concrete values
type: principle
stage: testing
strength: must
---
Assert exact values, never `is not None`.

**Why:** weak assertions hide bugs.
**How to apply:** compare to the literal expected value.
"""


@pytest.fixture
def seed_note():
    def _seed(seed, rel, note_id, title, status="accepted"):
        p = seed / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        _git(["pull", "-q", "--rebase"], seed)
        p.write_text(mind.render_frontmatter({"id": note_id, "title": title, "type": "principle", "stage": "testing",
                                              "scope": "global", "strength": "must", "status": status,
                                              "affirmed": "2026-09-12", "supersedes": None, "source": "t"}, f"{title} body.\n"))
        _git(["add", "."], seed)
        _git(["commit", "-q", "-m", f"seed {note_id}"], seed)
        _git(["push", "-q"], seed)
    return _seed


def test_cmd_init_creates_layout_and_pushes(repo):
    cfg, bare, _ = repo
    assert mind.cmd_init(cfg) == "mind: initialised global/ and projects/"
    assert (cfg.home / "schema.md").read_text() == (PLUGIN / "templates" / "schema.md").read_text()
    assert (cfg.home / "global" / "index.md").read_text() == "# Global\n"
    assert _git(["log", "--format=%s", "main"], bare).stdout.splitlines()[0] == "mind: init"


def test_cmd_init_writes_and_commits_gitignore_for_indexes(repo):
    """Indexes are generated, never committed: init must ship a .gitignore
    covering every index.md so no future add/accept ever tracks one."""
    cfg, bare, _ = repo
    mind.cmd_init(cfg)
    assert (cfg.home / ".gitignore").read_text() == "**/index.md\n"
    tracked = _git(["ls-tree", "-r", "--name-only", "main"], bare).stdout.split()
    assert ".gitignore" in tracked
    assert not any(p.endswith("index.md") for p in tracked)


def test_cmd_add_global_assigns_id_and_pushes(repo, tmp_path):
    cfg, bare, _ = repo
    mind.cmd_init(cfg)
    draft = tmp_path / "d.md"
    draft.write_text(DRAFT)
    out = mind.cmd_add(cfg, draft, "global", None, tmp_path)
    assert out == "mind: added PRIN-TEST-001 (global), pushed"
    path = cfg.home / "global" / "notes" / "PRIN-TEST-001-tests-must-assert-concrete-values.md"
    meta, body = mind.parse_frontmatter(path.read_text())
    assert meta == {"id": "PRIN-TEST-001", "title": "Tests must assert concrete values", "type": "principle",
                    "stage": "testing", "scope": "global", "strength": "must", "status": "accepted",
                    "affirmed": dt.date.today().isoformat(), "supersedes": None,
                    "source": f"session {dt.date.today().isoformat()}, {tmp_path.name.lower()}"}
    assert body.startswith("Assert exact values")
    assert (cfg.home / "global" / "index.md").read_text() == "# Global\n\n## testing\n- PRIN-TEST-001 | Tests must assert concrete values | must\n"
    assert _git(["log", "--format=%s", "main"], bare).stdout.splitlines()[0] == "mind: add PRIN-TEST-001 Tests must assert concrete values"


def test_cmd_add_sanitizes_slug_from_mind_project_no_path_traversal(repo, tmp_path):
    """A hostile or accidental MIND_PROJECT must never escape home/projects/."""
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    cfg = dataclasses.replace(cfg, project="../../escaped")
    draft = tmp_path / "d.md"
    draft.write_text(DRAFT)
    out = mind.cmd_add(cfg, draft, "project", None, tmp_path)
    assert out == "mind: added escaped/PRIN-TEST-001 (project escaped), pushed; project.md is a stub, fill it in"
    assert (cfg.home / "projects" / "escaped" / "project.md").is_file()
    assert not (cfg.home.parent / "escaped").exists()


def test_cmd_add_sanitizes_slash_in_explicit_project_flag(repo, tmp_path):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    draft = tmp_path / "d.md"
    draft.write_text(DRAFT)
    out = mind.cmd_add(cfg, draft, "project", "a/b", tmp_path)
    assert out == "mind: added a-b/PRIN-TEST-001 (project a-b), pushed; project.md is a stub, fill it in"
    assert (cfg.home / "projects" / "a-b" / "project.md").is_file()
    assert not (cfg.home / "projects" / "a").exists()


def test_cmd_add_rejects_slug_that_sanitizes_to_empty(repo, tmp_path):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    cfg = dataclasses.replace(cfg, project="..")
    draft = tmp_path / "d.md"
    draft.write_text(DRAFT)
    with pytest.raises(mind.ValidationError, match="invalid project slug"):
        mind.cmd_add(cfg, draft, "project", None, tmp_path)
    assert [p for p in (cfg.home / "projects").iterdir() if p.is_dir()] == []


def test_cmd_add_project_creates_stub(repo, tmp_path):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    work = tmp_path / "New-Proj"
    work.mkdir()
    draft = tmp_path / "d.md"
    draft.write_text(DRAFT)
    out = mind.cmd_add(cfg, draft, "project", None, work)
    assert out == "mind: added new-proj/PRIN-TEST-001 (project new-proj), pushed; project.md is a stub, fill it in"
    meta, body = mind.load_project(cfg, "new-proj")
    assert meta["slug"] == "new-proj"
    assert meta["aliases"] == []
    assert body == "Describe the project: purpose, kind of work, repo URL.\n"
    assert (cfg.home / "projects" / "index.md").read_text() == "# Projects\n\n- new-proj | new-proj |  | Describe the project: purpose, kind of work, repo URL.\n"


def test_cmd_add_rejects_invalid_frontmatter(repo, tmp_path):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    draft = tmp_path / "d.md"
    draft.write_text("---\ntitle: x\ntype: wish\nstage: review\nstrength: must\n---\nb\n")
    with pytest.raises(mind.ValidationError, match="type must be one of"):
        mind.cmd_add(cfg, draft, "global", None, tmp_path)
    assert list(mind.global_notes_dir(cfg).glob("*.md")) == []


def test_cmd_add_raises_on_commit_failure_and_keeps_earlier_unpushed_commit(repo, tmp_path, monkeypatch):
    """commit_all must surface a failed `git commit` rather than silently
    continuing as if the note were committed, and a failure must never touch
    an earlier commit that is itself still unpushed."""
    cfg, bare, _ = repo
    mind.cmd_init(cfg)
    (cfg.home / "earlier.md").write_text("earlier\n")
    mind.commit_all(cfg, "mind: earlier unpushed")

    def fail_commit(c, message):
        return subprocess.CompletedProcess(args=["git", "commit"], returncode=1, stdout="", stderr="hook declined\n")

    monkeypatch.setattr(mind, "commit_all", fail_commit)
    draft = tmp_path / "d.md"
    draft.write_text(DRAFT)
    with pytest.raises(mind.ValidationError, match="commit failed: hook declined"):
        mind.cmd_add(cfg, draft, "global", None, tmp_path)
    log = _git(["log", "--format=%s"], cfg.home).stdout.splitlines()
    assert log[0] == "mind: earlier unpushed"


def test_git_base_args_adds_identity_only_when_git_config_has_none(repo):
    """A fresh clone (e.g. a cloud container) has no configured git identity
    at all: git_base_args must supply one so commit_all does not fail with
    'unable to auto-detect email address'. A repo with its own configured
    identity must be left alone."""
    cfg, _, _ = repo
    args_without_config = mind.git_base_args(cfg)
    assert "user.name=mind" in args_without_config
    assert "user.email=mind@localhost" in args_without_config

    _git(["config", "user.email", "real@example.com"], cfg.home)
    _git(["config", "user.name", "Real Name"], cfg.home)
    args_with_config = mind.git_base_args(cfg)
    assert "user.email=mind@localhost" not in args_with_config
    assert "user.name=mind" not in args_with_config


def test_cmd_add_reports_push_failure_but_keeps_commit(repo, tmp_path, monkeypatch):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    monkeypatch.setattr(mind, "push", lambda c: "mind: push failed, note is committed locally; it will push on the next remember or session start")
    draft = tmp_path / "d.md"
    draft.write_text(DRAFT)
    out = mind.cmd_add(cfg, draft, "global", None, tmp_path)
    assert out == "mind: added PRIN-TEST-001 (global), mind: push failed, note is committed locally; it will push on the next remember or session start"
    assert _git(["log", "-1", "--format=%s"], cfg.home).stdout.strip() == "mind: add PRIN-TEST-001 Tests must assert concrete values"


def test_cmd_add_renames_on_duplicate_id_from_remote(repo, tmp_path, seed_note):
    """Two machines add PRIN-TEST-001 at once: the loser gets 002."""
    cfg, bare, seed = repo
    mind.cmd_init(cfg)
    seed_note(seed, "global/notes/PRIN-TEST-001-other.md", "PRIN-TEST-001", "Other")   # pushed by the other machine
    draft = tmp_path / "d.md"
    draft.write_text(DRAFT)
    out = mind.cmd_add(cfg, draft, "global", None, tmp_path)
    assert out == "mind: added PRIN-TEST-002 (global), pushed"
    names = sorted(p.name for p in mind.global_notes_dir(cfg).glob("*.md"))
    assert names == ["PRIN-TEST-001-other.md", "PRIN-TEST-002-tests-must-assert-concrete-values.md"]


def test_cmd_add_two_checkouts_different_ids_same_stage_both_land_on_remote(repo, tmp_path):
    """Two independent checkouts add different-ID notes to the same stage at
    once. Nothing collides (different type codes), so both notes must reach
    the bare remote and neither triggers the collision-rename path."""
    cfg_a, bare, _ = repo
    mind.cmd_init(cfg_a)
    home_b = tmp_path / "home_b"
    cfg_b = dataclasses.replace(cfg_a, home=home_b)
    assert mind.ensure_checkout(cfg_b) is None

    draft_a = tmp_path / "a.md"
    draft_a.write_text(DRAFT)
    out_a = mind.cmd_add(cfg_a, draft_a, "global", None, tmp_path)
    assert out_a == "mind: added PRIN-TEST-001 (global), pushed"

    draft_b = tmp_path / "b.md"
    draft_b.write_text(DRAFT.replace("type: principle", "type: gotcha").replace(
        "Tests must assert concrete values", "Flaky test retried three times before it failed for real"))
    out_b = mind.cmd_add(cfg_b, draft_b, "global", None, tmp_path)
    assert out_b == "mind: added GOT-TEST-001 (global), pushed"

    log = _git(["log", "--format=%s", "main"], bare).stdout.splitlines()
    assert "mind: add PRIN-TEST-001 Tests must assert concrete values" in log
    assert "mind: add GOT-TEST-001 Flaky test retried three times before it failed for real" in log
    listing = _git(["ls-tree", "--name-only", "main", "global/notes/"], bare).stdout.split()
    names = sorted(Path(p).name for p in listing)
    assert names == [
        "GOT-TEST-001-flaky-test-retried-three-times-before-it-failed-for-real.md",
        "PRIN-TEST-001-tests-must-assert-concrete-values.md",
    ]


def test_cmd_inject_reindexes_after_pull_on_fresh_clone(repo, tmp_path):
    """Indexes are gitignored: a fresh clone has no index.md at all. inject
    must regenerate it locally after a successful pull, not show it empty."""
    cfg_a, bare, _ = repo
    mind.cmd_init(cfg_a)
    _add(cfg_a, tmp_path, "Global rule", "g")
    home_b = tmp_path / "home_b"
    cfg_b = dataclasses.replace(cfg_a, home=home_b)
    assert mind.ensure_checkout(cfg_b) is None
    assert not (cfg_b.home / "global" / "index.md").is_file()
    out = mind.cmd_inject(cfg_b, "startup", tmp_path)
    assert "- PREF-REV-001 | Global rule | should" in out


def test_cmd_add_two_checkouts_race_through_cmd_add(repo, tmp_path, monkeypatch):
    """Two independent checkouts (not a raw seeded push) both race cmd_add for
    the same next ID. Neither collides at write time (each pulled before the
    other pushed), but the loser's own final sync() rebases the winner's note
    in cleanly (different filenames never conflict in git); the explicit
    post-rebase ID-collision scan then catches the duplicate ID, deletes the
    loser's own file, reassigns it to PRIN-TEST-002, and amends the commit
    before pushing again. The bare remote ends with both 001 and 002 present."""
    cfg_a, bare, _ = repo
    mind.cmd_init(cfg_a)
    home_b = tmp_path / "home_b"
    cfg_b = dataclasses.replace(cfg_a, home=home_b)
    assert mind.ensure_checkout(cfg_b) is None

    draft_a = tmp_path / "a.md"
    draft_a.write_text(DRAFT)
    draft_b = tmp_path / "b.md"
    draft_b.write_text(DRAFT.replace("Tests must assert concrete values", "Never skip the plan tests step"))

    # cfg_b's pre-write pull-only sync completes (finds nothing new) before cfg_a pushes.
    real_sync = mind.sync
    monkeypatch.setattr(
        mind, "sync",
        lambda c, pull_only=False: None if (pull_only and c.home == cfg_b.home) else real_sync(c, pull_only),
    )

    out_a = mind.cmd_add(cfg_a, draft_a, "global", None, tmp_path)
    assert out_a == "mind: added PRIN-TEST-001 (global), pushed"

    out_b = mind.cmd_add(cfg_b, draft_b, "global", None, tmp_path)
    assert out_b == "mind: added PRIN-TEST-002 (global), pushed"

    log = _git(["log", "--format=%s", "main"], bare).stdout.splitlines()
    assert "mind: add PRIN-TEST-001 Tests must assert concrete values" in log
    assert "mind: add PRIN-TEST-002 Never skip the plan tests step" in log
    listing = _git(["ls-tree", "--name-only", "main", "global/notes/"], bare).stdout.split()
    names = sorted(Path(p).name for p in listing)
    assert names == [
        "PRIN-TEST-001-tests-must-assert-concrete-values.md",
        "PRIN-TEST-002-never-skip-the-plan-tests-step.md",
    ]


def test_cmd_accept_flips_draft(repo, tmp_path):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    draft = tmp_path / "d.md"
    draft.write_text(DRAFT.replace("strength: must\n", "strength: must\nstatus: draft\n"))
    mind.cmd_add(cfg, draft, "global", None, tmp_path)
    assert (cfg.home / "global" / "index.md").read_text() == "# Global\n"
    assert mind.cmd_accept(cfg, "PRIN-TEST-001") == "mind: accepted PRIN-TEST-001, pushed"
    meta, _ = mind.parse_frontmatter(next(mind.global_notes_dir(cfg).glob("PRIN-TEST-001-*.md")).read_text())
    assert meta["status"] == "accepted"
    assert meta["affirmed"] == dt.date.today().isoformat()
    with pytest.raises(mind.ValidationError, match="no note with id NOPE-X-001"):
        mind.cmd_accept(cfg, "NOPE-X-001")


def test_cmd_accept_by_slug_prefixed_id(repo, tmp_path):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    work = tmp_path / "proj-a"
    work.mkdir()
    _add(cfg, tmp_path, "Draft one", "d", status="draft", scope="project", cwd=work)
    assert mind.cmd_accept(cfg, "proj-a/PREF-REV-001") == "mind: accepted proj-a/PREF-REV-001, pushed"
    meta, _ = mind.parse_frontmatter(next(mind.project_notes_dir(cfg, "proj-a").glob("PREF-REV-001-*.md")).read_text())
    assert meta["status"] == "accepted"


def test_cmd_accept_bare_id_ambiguous_across_projects_raises(repo, tmp_path):
    """A bare ID (no slug/) only ever searches global; if it is absent there
    but present in more than one project, it must not silently pick one."""
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    work_a = tmp_path / "proj-a"
    work_a.mkdir()
    work_b = tmp_path / "proj-b"
    work_b.mkdir()
    _add(cfg, tmp_path, "Draft in a", "d", status="draft", scope="project", cwd=work_a)
    _add(cfg, tmp_path, "Draft in b", "d", status="draft", scope="project", cwd=work_b)
    with pytest.raises(mind.ValidationError, match=r"ambiguous id, use <slug>/<ID>"):
        mind.cmd_accept(cfg, "PREF-REV-001")


def _add(cfg, tmp_path, title, body, stage="review", status="accepted", scope="global", cwd=None):
    d = tmp_path / f"{mind._kebab(title)}.md"
    d.write_text(mind.render_frontmatter({"title": title, "type": "preference", "stage": stage, "strength": "should", "status": status}, body + "\n"))
    return mind.cmd_add(cfg, d, scope, None, cwd or tmp_path)


def test_cmd_ask_ranks_by_terms_hit_and_scopes(repo, tmp_path):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    _add(cfg, tmp_path, "Reply to review threads, never resolve them", "Threads stay open for the owner.")
    _add(cfg, tmp_path, "Squash merge every PR", "One commit per PR on the default branch.")
    work = tmp_path / "proj-a"
    work.mkdir()
    _add(cfg, tmp_path, "Resolve threads only on trivial nits", "Project-local exception.", scope="project", cwd=work)
    other = tmp_path / "proj-b"
    other.mkdir()
    _add(cfg, tmp_path, "Threads in project b", "Unrelated.", scope="project", cwd=other)

    out = mind.cmd_ask(cfg, ["resolve", "threads"], False, None, False, work)
    assert out == (
        "PREF-REV-001 | Reply to review threads, never resolve them | global | should\n"
        "  Threads stay open for the owner.\n"
        "proj-a/PREF-REV-001 | Resolve threads only on trivial nits | project:proj-a | should\n"
        "  Project-local exception.\n"
    )
    out_all = mind.cmd_ask(cfg, ["threads"], True, None, False, work)
    assert "proj-b/PREF-REV-001 | Threads in project b | project:proj-b | should" in out_all
    assert mind.cmd_ask(cfg, ["kubernetes"], False, None, False, work) == "mind: no note matches 'kubernetes'"


def test_cmd_ask_drafts_lists_only_drafts(repo, tmp_path):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    _add(cfg, tmp_path, "Accepted one", "a")
    _add(cfg, tmp_path, "Draft one", "d", status="draft")
    assert mind.cmd_ask(cfg, [], False, None, True, tmp_path) == "PREF-REV-002 | Draft one | global | should | draft\n  d\n"


def test_cmd_inject_prints_sections_in_order(repo, tmp_path, monkeypatch):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    _add(cfg, tmp_path, "Global rule", "g")
    work = tmp_path / "proj-a"
    work.mkdir()
    _add(cfg, tmp_path, "Project rule", "p", scope="project", cwd=work)
    _add(cfg, tmp_path, "A draft", "d", status="draft")
    out = mind.cmd_inject(cfg, "startup", work)
    assert out == (
        mind.PROTOCOL.format(home=cfg.home)
        + "\n# Global\n\n## review\n- PREF-REV-001 | Global rule | should\n"
        + "\n# proj-a\n\n## review\n- PREF-REV-001 | Project rule | should\n"
        + "\n# Projects\n\n- proj-a | proj-a |  | Describe the project: purpose, kind of work, repo URL.\n"
        + "\n1 draft note awaits acceptance: run /mind:ask --drafts\n"
    )


def test_cmd_inject_without_project(repo, tmp_path):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    nowhere = tmp_path / "Nowhere"
    nowhere.mkdir()
    out = mind.cmd_inject(cfg, "startup", nowhere)
    assert "\nno notes for nowhere yet\n" in out
    assert out.endswith("\n# Projects\n")


def test_cmd_inject_compact_makes_no_network_call(repo, tmp_path, monkeypatch):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    monkeypatch.setattr(mind, "pull", lambda c: pytest.fail("pull called on compact"))
    out = mind.cmd_inject(cfg, "compact", tmp_path)
    assert out.startswith(mind.PROTOCOL.format(home=cfg.home))


def test_cmd_inject_offline_line(repo, tmp_path, monkeypatch):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    monkeypatch.setattr(mind, "pull", lambda c: "mind: offline, using cached copy from 2026-09-12")
    out = mind.cmd_inject(cfg, "resume", tmp_path)
    assert out.startswith("mind: offline, using cached copy from 2026-09-12\n")


def test_cmd_inject_truncates_global_first(repo, tmp_path, monkeypatch):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    monkeypatch.setattr(mind, "INDEX_BUDGET", 300)
    for i in range(8):
        _add(cfg, tmp_path, f"Global rule number {i} with a long enough title to fill", "g")
    work = tmp_path / "proj-a"
    work.mkdir()
    _add(cfg, tmp_path, "Project rule", "p", scope="project", cwd=work)
    out = mind.cmd_inject(cfg, "clear", work)
    assert "\n+7 more, run /mind:ask <topic>\n" in out                # exact cut count, not "+1"
    assert "- PREF-REV-001 | Global rule number 0 with a long enough title to fill | should" in out
    assert "- PREF-REV-001 | Project rule | should" in out          # project index intact
    assert "- proj-a | proj-a |" in out                               # projects index intact
    assert "Global rule number 7" not in out


def test_cmd_inject_index_budget_of_10_still_prints_projects_index(repo, tmp_path, monkeypatch):
    """A degenerate INDEX_BUDGET smaller than the projects index alone must
    still terminate (not raise or hang) and must never truncate the projects
    index, per the spec's 'never truncate projects' rule."""
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    monkeypatch.setattr(mind, "INDEX_BUDGET", 10)
    for i in range(5):
        _add(cfg, tmp_path, f"Global rule number {i} with a long enough title to fill", "g")
    work = tmp_path / "proj-a"
    work.mkdir()
    _add(cfg, tmp_path, "Project rule", "p", scope="project", cwd=work)
    out = mind.cmd_inject(cfg, "startup", work)
    assert "\n# Projects\n\n- proj-a | proj-a |  | Describe the project: purpose, kind of work, repo URL.\n" in out


def test_main_inject_never_fails_the_hook(repo, tmp_path, monkeypatch, capsys):
    cfg, _, _ = repo
    monkeypatch.setattr(mind, "cmd_inject", lambda c, e, w: (_ for _ in ()).throw(RuntimeError("boom")))
    env = {"MIND_REPO": cfg.repo, "MIND_HOME": str(cfg.home)}
    assert mind.main(["inject", "--event", "startup"], env=env, cwd=tmp_path) == 0
    assert capsys.readouterr().out == "mind: inject failed, boom\n"


def test_hook_end_to_end(repo, tmp_path):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    _add(cfg, tmp_path, "Global rule", "g")
    env = dict(os.environ, MIND_REPO=cfg.repo, MIND_HOME=str(cfg.home), CLAUDE_PLUGIN_ROOT=str(PLUGIN))
    proc = subprocess.run(
        ["sh", str(PLUGIN / "scripts" / "session-start.sh")],
        env=env, input=json.dumps({"source": "startup"}), capture_output=True, text=True, cwd=tmp_path,
    )
    assert proc.returncode == 0
    assert "- PREF-REV-001 | Global rule | should" in proc.stdout
