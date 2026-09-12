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


def test_hook_does_not_block_on_a_tty_stdin(tmp_path):
    """Run by hand at a terminal (no piped SessionStart JSON), the hook must
    default to 'startup' immediately rather than block on
    `json.load(sys.stdin)` waiting for an EOF a human at a keyboard never
    sends."""
    import pty

    env = dict(os.environ, MIND_REPO=str(tmp_path / "missing.git"), CLAUDE_PLUGIN_ROOT=str(PLUGIN))
    controller_fd, follower_fd = pty.openpty()
    try:
        proc = subprocess.Popen(
            ["sh", str(PLUGIN / "scripts" / "session-start.sh")],
            stdin=follower_fd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, cwd=tmp_path, text=True,
        )
        os.close(follower_fd)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            pytest.fail("hook blocked on a tty stdin instead of defaulting to startup")
        assert proc.returncode == 0
    finally:
        os.close(controller_fd)


def test_main_add_reports_clone_failure_on_stderr_and_returns_1(tmp_path, capsys):
    """Only inject (the session-start hook) may swallow a clone failure and
    exit 0; every other command must fail loudly, or the owner sees a
    silent no-op 'mind: added ..., pushed'-shaped success that never wrote
    anything at all."""
    env = {"MIND_REPO": str(tmp_path / "missing.git"), "MIND_HOME": str(tmp_path / "h")}
    draft = tmp_path / "d.md"
    draft.write_text(NOTE)
    rc = mind.main(["add", str(draft), "--scope", "global"], env=env, cwd=tmp_path)
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("mind: clone failed")


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
        "type must be one of: principle, preference, decision, procedure, gotcha, reference, precedence",
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


def test_load_notes_skips_malformed_frontmatter_and_bad_id(tmp_path):
    """A hand-edited or hand-migrated note whose frontmatter fails
    validate_meta (off-enum stage, most often) or whose id doesn't match
    the ID shape must never render as a blank `- |  | ` index row."""
    (tmp_path / "PREF-REV-001-ok.md").write_text(mind.render_frontmatter(
        {"id": "PREF-REV-001", "title": "OK", "type": "preference", "stage": "review", "strength": "must"}, "b\n"))
    (tmp_path / "PREF-REV-002-badstage.md").write_text(mind.render_frontmatter(
        {"id": "PREF-REV-002", "title": "Bad", "type": "preference", "stage": "wishful", "strength": "must"}, "b\n"))
    (tmp_path / "bad-id.md").write_text(mind.render_frontmatter(
        {"id": "not-an-id", "title": "Bad id", "type": "preference", "stage": "review", "strength": "must"}, "b\n"))
    notes = mind.load_notes(tmp_path)
    assert [n.id for n in notes] == ["PREF-REV-001"]


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
    cfg2 = mind.Config.from_env({"MIND_REPO": "/u", "HOME": str(tmp_path)}, tmp_path)
    assert cfg2.home == tmp_path / ".mind" / "repo"


def test_config_requires_repo(tmp_path):
    with pytest.raises(mind.ConfigError, match="MIND_REPO is not set"):
        mind.Config.from_env({}, tmp_path)


def test_config_env_defaults_to_os_environ(tmp_path):
    cfg = mind.Config.from_env({"MIND_REPO": "/x"}, tmp_path)
    assert cfg.env is os.environ


def test_config_rejects_disallowed_repo_url_scheme(tmp_path):
    """`--` blocks option injection at the clone call, but not a transport
    like ext::sh -c ..., which executes at clone time."""
    with pytest.raises(mind.ConfigError, match="MIND_REPO must be an ssh, https, file URL or absolute path"):
        mind.Config.from_env({"MIND_REPO": "ext::sh -c touch pwned"}, tmp_path)


def test_config_accepts_every_documented_repo_url_form(tmp_path):
    for repo in ("ssh://git@host/o/r.git", "git@host:o/r.git", "https://host/o/r.git",
                 "file:///tmp/r.git", "/abs/path/r.git"):
        assert mind.Config.from_env({"MIND_REPO": repo}, tmp_path).repo == repo


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


def test_ensure_checkout_clone_uses_dash_dash_before_repo_url(repo, monkeypatch):
    """A MIND_REPO beginning with '-' must never be parsed as a git option."""
    cfg, _, _ = repo
    captured = {}
    real_git = mind.git

    def spy(c, args, cwd, timeout):
        if args and args[0] == "clone":
            captured["args"] = args
        return real_git(c, args, cwd, timeout)

    monkeypatch.setattr(mind, "git", spy)
    home2 = cfg.home.parent / "second"
    cfg2 = dataclasses.replace(cfg, home=home2)
    assert mind.ensure_checkout(cfg2) is None
    assert captured["args"] == ["clone", "-q", "--", cfg.repo, str(home2)]


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


def test_pull_first_run_when_no_upstream_yet(tmp_path):
    """A brand-new, still-empty data repo has no upstream tracking branch at
    all: pull() must say so plainly rather than call it offline forever."""
    bare = tmp_path / "remote.git"
    _git(["init", "--bare", "-q", "--initial-branch=main", str(bare)], tmp_path)
    home = tmp_path / "home"
    env = {"MIND_REPO": str(bare), "MIND_HOME": str(home)}
    cfg = mind.Config.from_env(env, tmp_path)
    assert mind.ensure_checkout(cfg) is None
    assert mind.pull(cfg) == "mind: first run, nothing to pull yet"


def test_pull_diverged_reports_sync_blocked_not_offline(repo):
    """A genuinely diverged branch (both sides moved) is not a network
    problem: pull --ff-only refuses it outright, and that must be reported
    as a sync block the owner can act on, never mislabeled offline."""
    cfg, bare, seed = repo
    (cfg.home / "local.md").write_text("local\n")
    mind.commit_all(cfg, "mind: local change")
    (seed / "remote.md").write_text("remote\n")
    _git(["add", "."], seed)
    _git(["commit", "-q", "-m", "remote change"], seed)
    _git(["push", "-q"], seed)
    msg = mind.pull(cfg)
    assert msg.startswith("mind: sync blocked: ")
    assert "offline" not in msg


def test_rebase_failure_message_shares_pull_classification(repo):
    """_rebase_failure_message must route a non-conflict rebase refusal
    through the same classifier as pull(), not its own offline-only text."""
    cfg, _, _ = repo
    proc = subprocess.CompletedProcess(
        args=["git", "pull", "--rebase"], returncode=1, stdout="",
        stderr="fatal: Not possible to fast-forward, aborting.\n",
    )
    msg = mind._rebase_failure_message(cfg, proc)
    assert msg == "mind: sync blocked: fatal: Not possible to fast-forward, aborting."


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


def test_git_pops_inherited_git_dir_env_vars(repo, tmp_path):
    """If the owner's shell exports GIT_DIR (some tools do), every mind.py
    git call must still operate on cfg.home, not that other repo — reset
    --hard under an inherited GIT_DIR/GIT_WORK_TREE would hit the wrong
    working tree entirely."""
    cfg, _, _ = repo
    other_repo = tmp_path / "other"
    _git(["init", "-q", str(other_repo)], tmp_path)
    poisoned_env = dict(os.environ, GIT_DIR=str(other_repo / ".git"), GIT_WORK_TREE=str(other_repo),
                        GIT_INDEX_FILE=str(other_repo / ".git" / "index"), GIT_NAMESPACE="poisoned")
    poisoned_cfg = dataclasses.replace(cfg, env=poisoned_env)
    out = mind.git(poisoned_cfg, ["rev-parse", "--show-toplevel"], poisoned_cfg.home, 5).stdout.strip()
    assert Path(out).resolve() == poisoned_cfg.home.resolve()


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


def test_ensure_checkout_reports_broken_checkout_when_git_dir_has_no_head(tmp_path):
    """A clone the timeout killed mid-transfer (or any other half write)
    leaves .git present with nothing usable inside. That must be reported
    as broken, not pass as a healthy (if empty) checkout."""
    home = tmp_path / "h"
    (home / ".git").mkdir(parents=True)
    cfg = mind.Config.from_env({"MIND_REPO": "/irrelevant", "MIND_HOME": str(home)}, tmp_path)
    msg = mind.ensure_checkout(cfg)
    assert msg == f"mind: checkout at {home} is broken, delete it and rerun"


def test_ensure_checkout_removes_partial_dir_on_clone_timeout(tmp_path, monkeypatch):
    home = tmp_path / "h"
    cfg = mind.Config.from_env({"MIND_REPO": "/irrelevant", "MIND_HOME": str(home)}, tmp_path)

    def fake_git(c, args, cwd, timeout):
        if args and args[0] == "clone":
            (c.home / ".git").mkdir(parents=True)  # what a killed clone leaves behind
            raise subprocess.TimeoutExpired(cmd="git clone", timeout=timeout)
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(mind, "git", fake_git)
    msg = mind.ensure_checkout(cfg)
    assert msg == "mind: clone failed, timed out"
    assert not home.exists()


def test_ensure_checkout_removes_partial_dir_on_clone_failure(tmp_path, monkeypatch):
    home = tmp_path / "h"
    cfg = mind.Config.from_env({"MIND_REPO": "/irrelevant", "MIND_HOME": str(home)}, tmp_path)

    def fake_git(c, args, cwd, timeout):
        if args and args[0] == "clone":
            (c.home / ".git").mkdir(parents=True)
            return subprocess.CompletedProcess(args=args, returncode=128, stdout="", stderr="fatal: boom\n")
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(mind, "git", fake_git)
    msg = mind.ensure_checkout(cfg)
    assert msg == "mind: clone failed, fatal: boom"
    assert not home.exists()


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


def _write_project(cfg, slug, aliases=(), stack=("go", "postgres"), body="Backend API service. Second sentence."):
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


def test_resolve_candidate_ignores_inherited_git_dir(tmp_path, repo):
    """An exported GIT_DIR (as inside any git hook) must not redirect
    resolve_candidate's probes to a different repo than the untrusted cwd."""
    cfg, _, _ = repo
    work = tmp_path / "real-repo"
    work.mkdir()
    _git(["init", "-q", str(work)], tmp_path)
    _git(["remote", "add", "origin", "git@example.com:o/real-repo.git"], work)
    other_repo = tmp_path / "other"
    _git(["init", "-q", str(other_repo)], tmp_path)
    _git(["remote", "add", "origin", "git@example.com:o/other.git"], other_repo)
    poisoned_env = dict(os.environ, GIT_DIR=str(other_repo / ".git"), GIT_WORK_TREE=str(other_repo))
    poisoned_cfg = dataclasses.replace(cfg, env=poisoned_env)
    assert mind.resolve_candidate(poisoned_cfg, work) == "real-repo"


def test_resolve_candidate_strips_mind_token_from_child_environment(repo, tmp_path, monkeypatch):
    """A hostile .git/config in the untrusted cwd (core.sshCommand, a
    credential helper) must never inherit MIND_TOKEN."""
    cfg, _, _ = repo
    cfg = dataclasses.replace(cfg, token="sekrit", env=dict(os.environ, MIND_TOKEN="sekrit"))
    work = tmp_path / "w"
    work.mkdir()
    captured = {}
    real_popen = subprocess.Popen

    def spy(args, **kwargs):
        captured["env"] = kwargs.get("env")
        return real_popen(args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spy)
    mind.resolve_candidate(cfg, work)
    assert "MIND_TOKEN" not in captured["env"]


def test_resolve_candidate_falls_back_to_cwd_name_on_timeout(repo, tmp_path, monkeypatch):
    """No timeout previously meant a hung git could block the SessionStart
    hook past every budget; a timed-out probe must fall through cleanly,
    not raise."""
    cfg, _, _ = repo
    monkeypatch.setattr(
        mind, "git",
        lambda c, a, cw, t: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="git", timeout=t)))
    work = tmp_path / "Fallback-Name"
    work.mkdir()
    assert mind.resolve_candidate(cfg, work) == "fallback-name"


def test_match_project_by_slug_and_alias(repo):
    cfg, _, _ = repo
    _write_project(cfg, "acme-api", aliases=("acme-api-old", "acme-backend"))
    assert mind.match_project(cfg, "acme-api") == "acme-api"
    assert mind.match_project(cfg, "acme-api-old") == "acme-api"
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
    p = mind.project_notes_dir(cfg, "acme-api"); p.mkdir(parents=True)
    assert mind.next_id(p, "preference", "review") == "PREF-REV-001"


def test_build_index_groups_by_stage_and_skips_drafts():
    """Only status: accepted notes ever appear in a generated index — draft,
    superseded, and deprecated must all be excluded (a filter that changed
    from `== "accepted"` to `!= "draft"` would let the latter two leak in
    and still pass a test that only tries draft)."""
    def note(i, stage, strength, status="accepted"):
        return mind.Note(Path(i), {"id": i, "title": f"T {i}", "stage": stage, "strength": strength, "status": status}, "b\n")
    text = mind.build_index([note("PREF-REV-001", "review", "must"), note("GOT-DEV-001", "development", "should"),
                             note("PREF-REV-002", "review", "default", "draft"),
                             note("PREF-REV-003", "review", "should", "superseded"),
                             note("PREF-REV-004", "review", "should", "deprecated")], "Global")
    assert text == (
        "# Global\n\n"
        "## development\n"
        "- GOT-DEV-001 | T GOT-DEV-001 | should\n\n"
        "## review\n"
        "- PREF-REV-001 | T PREF-REV-001 | must\n"
    )


def test_priority_order_keeps_must_first_then_round_robins_stages():
    """8 rows across 3 stages: the must row survives any budget, and the
    round-robin means the first cut after it takes one row per stage
    before taking a second row from any single stage."""
    def note(i, stage, strength):
        return mind.Note(Path(i), {"id": i, "title": f"T {i}", "stage": stage, "strength": strength, "status": "accepted"}, "b\n")
    notes = [
        note("PRIN-ID-001", "identity", "must"),
        note("PREF-ID-001", "identity", "should"),
        note("PREF-ID-002", "identity", "should"),
        note("PREF-PROD-001", "product", "should"),
        note("PREF-PROD-002", "product", "should"),
        note("PREF-PROD-003", "product", "should"),
        note("PREF-PLAN-001", "planning", "should"),
        note("PREF-PLAN-002", "planning", "should"),
    ]
    ordered = mind._priority_order(notes)
    assert [n.id for n in ordered] == [
        "PRIN-ID-001", "PREF-ID-001", "PREF-PROD-001", "PREF-PLAN-001",
        "PREF-ID-002", "PREF-PROD-002", "PREF-PLAN-002", "PREF-PROD-003",
    ]
    # Budget for exactly 4 kept rows: all must rows, then one per stage.
    assert [n.id for n in ordered[:4]] == ["PRIN-ID-001", "PREF-ID-001", "PREF-PROD-001", "PREF-PLAN-001"]


def test_build_projects_index_and_reindex(repo):
    cfg, _, _ = repo
    _write_project(cfg, "acme-api")
    _write_project(cfg, "alpha", stack=("go",), body="Alpha thing.")
    mind.global_notes_dir(cfg).mkdir(parents=True)
    mind.reindex(cfg)
    assert (cfg.home / "projects" / "index.md").read_text() == (
        "# Projects\n\n"
        "- acme-api | Acme-Api | go, postgres | Backend API service.\n"
        "- alpha | Alpha | go | Alpha thing.\n"
    )
    assert (cfg.home / "global" / "index.md").read_text() == "# Global\n"
    assert (cfg.home / "projects" / "acme-api" / "index.md").read_text() == "# acme-api\n"


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


def test_commit_all_surfaces_add_failure_without_committing(repo, monkeypatch):
    """A failed `git add -A` (index.lock from a concurrent mind, a corrupt
    index) must not let `git commit` proceed and silently succeed on
    whatever else happened to be staged."""
    cfg, _, _ = repo
    (cfg.home / "x.md").write_text("x\n")
    real_git = mind.git

    def fake_git(c, args, cwd, timeout):
        if args[:2] == ["add", "-A"]:
            return subprocess.CompletedProcess(args=args, returncode=128, stdout="", stderr="fatal: index.lock exists\n")
        return real_git(c, args, cwd, timeout)

    monkeypatch.setattr(mind, "git", fake_git)
    proc = mind.commit_all(cfg, "mind: test")
    assert proc.returncode == 128
    assert proc.stderr.strip() == "fatal: index.lock exists"
    log = _git(["log", "--format=%s"], cfg.home).stdout.splitlines()
    assert log[0] != "mind: test"


def test_cmd_add_raises_when_add_fails(repo, tmp_path, monkeypatch):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    real_git = mind.git

    def fake_git(c, args, cwd, timeout):
        if args[:2] == ["add", "-A"]:
            return subprocess.CompletedProcess(args=args, returncode=128, stdout="", stderr="fatal: index.lock exists\n")
        return real_git(c, args, cwd, timeout)

    monkeypatch.setattr(mind, "git", fake_git)
    draft = tmp_path / "d.md"
    draft.write_text(DRAFT)
    with pytest.raises(mind.ValidationError, match="fatal: index.lock exists"):
        mind.cmd_add(cfg, draft, "global", None, tmp_path)


def test_cmd_add_amend_failure_raises_before_push(repo, tmp_path, monkeypatch):
    """If the collision-rename amend fails, the pre-amend commit (still
    carrying the duplicate ID) must never be the one pushed, and the wrong
    ID reported."""
    cfg_a, bare, _ = repo
    mind.cmd_init(cfg_a)
    home_b = tmp_path / "home_b"
    cfg_b = dataclasses.replace(cfg_a, home=home_b)
    assert mind.ensure_checkout(cfg_b) is None

    draft_a = tmp_path / "a.md"
    draft_a.write_text(DRAFT)
    draft_b = tmp_path / "b.md"
    draft_b.write_text(DRAFT.replace("Tests must assert concrete values", "Never skip the plan tests step"))

    real_sync = mind.sync
    monkeypatch.setattr(
        mind, "sync",
        lambda c, pull_only=False: None if (pull_only and c.home == cfg_b.home) else real_sync(c, pull_only),
    )
    out_a = mind.cmd_add(cfg_a, draft_a, "global", None, tmp_path)
    assert out_a == "mind: added PRIN-TEST-001 (global), pushed"

    real_git = mind.git

    def fake_git(c, args, cwd, timeout):
        if args[:3] == ["commit", "-q", "--amend"]:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="hook declined\n")
        return real_git(c, args, cwd, timeout)

    monkeypatch.setattr(mind, "git", fake_git)
    before = _git(["ls-remote", "--heads", str(bare)], tmp_path).stdout
    with pytest.raises(mind.ValidationError, match="hook declined"):
        mind.cmd_add(cfg_b, draft_b, "global", None, tmp_path)
    after = _git(["ls-remote", "--heads", str(bare)], tmp_path).stdout
    assert before == after  # nothing new pushed


def test_git_base_args_resets_credential_helpers_before_custom_one(repo):
    """Without an explicit reset, a configured osxkeychain/gh helper answers
    first and (on success) every configured helper's store action runs too,
    persisting the cloud token to the owner's real keychain."""
    cfg, _, _ = repo
    cfg = dataclasses.replace(cfg, token="tok")
    args = mind.git_base_args(cfg)
    reset_idx = args.index("credential.helper=")
    custom_idx = next(i for i, a in enumerate(args) if a.startswith("credential.helper=") and a != "credential.helper=")
    assert args[reset_idx - 1] == "-c"
    assert args[custom_idx - 1] == "-c"
    assert reset_idx < custom_idx


def test_git_base_args_quotes_mind_token_for_tokens_with_whitespace(repo):
    """An unquoted $MIND_TOKEN in the credential helper would word-split a
    token containing whitespace across multiple argv entries."""
    cfg, _, _ = repo
    cfg = dataclasses.replace(cfg, token="tok with spaces")
    args = mind.git_base_args(cfg)
    helper = next(a for a in args if a.startswith("credential.helper=!f"))
    assert '"$MIND_TOKEN"' in helper


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


def test_cmd_add_pulls_before_assigning_id(repo, tmp_path, seed_note):
    """Another machine already pushed PRIN-TEST-001 before this add starts.
    The pre-write pull brings that note down before next_id() is computed,
    so this machine is assigned 002 directly — no collision or rename."""
    cfg, bare, seed = repo
    mind.cmd_init(cfg)
    seed_note(seed, "global/notes/PRIN-TEST-001-other.md", "PRIN-TEST-001", "Other")   # pushed by the other machine
    draft = tmp_path / "d.md"
    draft.write_text(DRAFT)
    out = mind.cmd_add(cfg, draft, "global", None, tmp_path)
    assert out == "mind: added PRIN-TEST-002 (global), pushed"
    names = sorted(p.name for p in mind.global_notes_dir(cfg).glob("*.md"))
    assert names == ["PRIN-TEST-001-other.md", "PRIN-TEST-002-tests-must-assert-concrete-values.md"]


def test_cmd_add_prefixes_result_with_pre_write_sync_message(repo, tmp_path, monkeypatch):
    """When the pre-write pull fails (offline, or a hand-resolve conflict),
    the ID was still assigned against stale local state; the owner must be
    told, not left to discover it only later."""
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    real_sync = mind.sync

    def fake_sync(c, pull_only=False):
        if pull_only:
            return "mind: offline, using cached copy from 2026-09-12"
        return real_sync(c, pull_only)

    monkeypatch.setattr(mind, "sync", fake_sync)
    draft = tmp_path / "d.md"
    draft.write_text(DRAFT)
    out = mind.cmd_add(cfg, draft, "global", None, tmp_path)
    assert out == "mind: added PRIN-TEST-001 (global), mind: offline, using cached copy from 2026-09-12; pushed"


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


def test_cmd_inject_builds_projects_index_when_pull_fails_on_fresh_clone(repo, tmp_path, monkeypatch):
    """A fresh clone whose startup pull then fails offline must still show
    real projects, not silently claim there are zero of them."""
    cfg_a, bare, _ = repo
    mind.cmd_init(cfg_a)
    work = tmp_path / "acme-api"
    work.mkdir()
    _add(cfg_a, tmp_path, "Some rule", "b", scope="project", cwd=work)
    home_b = tmp_path / "home_b"
    cfg_b = dataclasses.replace(cfg_a, home=home_b)
    assert mind.ensure_checkout(cfg_b) is None
    assert not (cfg_b.home / "projects" / "index.md").is_file()
    monkeypatch.setattr(mind, "sync", lambda c: "mind: offline, using cached copy from 2026-09-12")
    out = mind.cmd_inject(cfg_b, "startup", tmp_path)
    assert "- acme-api | acme-api |" in out


def test_cmd_inject_builds_projects_index_on_compact_when_missing(repo, tmp_path):
    """clear/compact never sync or reindex: a fresh clone injected first
    on one of those events must still get a real projects index."""
    cfg_a, bare, _ = repo
    mind.cmd_init(cfg_a)
    work = tmp_path / "acme-api"
    work.mkdir()
    _add(cfg_a, tmp_path, "Some rule", "b", scope="project", cwd=work)
    home_b = tmp_path / "home_b"
    cfg_b = dataclasses.replace(cfg_a, home=home_b)
    assert mind.ensure_checkout(cfg_b) is None
    assert not (cfg_b.home / "projects" / "index.md").is_file()
    out = mind.cmd_inject(cfg_b, "compact", tmp_path)
    assert "- acme-api | acme-api |" in out


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


def test_cmd_accept_rejects_path_traversal_in_slug(repo):
    """`accept ../../../../etc/notes/PREF-DEV-001` must never read a file
    outside MIND_HOME by walking the slug up with `..`."""
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    with pytest.raises(mind.ValidationError, match="invalid project slug"):
        mind.cmd_accept(cfg, "../../../../etc/notes/PREF-DEV-001")


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


def test_cmd_ask_word_boundary_matching_short_term_does_not_match_substring(repo, tmp_path):
    """A two-letter term like 'pr' must not match inside 'process' or
    'prefer': substring matching makes short queries far less selective."""
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    _add(cfg, tmp_path, "Follow the review process closely", "We prefer a careful process.")
    assert mind.cmd_ask(cfg, ["pr"], False, None, False, tmp_path) == "mind: no note matches 'pr'"
    assert "PREF-REV-001" in mind.cmd_ask(cfg, ["process"], False, None, False, tmp_path)


def test_cmd_ask_drafts_lists_only_drafts(repo, tmp_path):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    _add(cfg, tmp_path, "Accepted one", "a")
    _add(cfg, tmp_path, "Draft one", "d", status="draft")
    assert mind.cmd_ask(cfg, [], False, None, True, tmp_path) == "PREF-REV-002 | Draft one | global | should | draft\n  d\n"


def test_precedence_type_and_refers_field(repo, tmp_path):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    d = tmp_path / "p.md"
    d.write_text("---\ntitle: When PREF-REV-001 conflicts with PREF-REV-002, the first wins on public repos\n"
                 "type: precedence\nstage: review\nstrength: should\nrefers: [PREF-REV-001, PREF-REV-002]\n---\n"
                 "When PREF-REV-001 conflicts with PREF-REV-002, PREF-REV-001 wins when the repo is public.\n")
    out = mind.cmd_add(cfg, d, "global", None, tmp_path)
    assert out == "mind: added PREC-REV-001 (global), pushed"
    meta, _ = mind.parse_frontmatter(next(mind.global_notes_dir(cfg).glob("PREC-REV-001-*.md")).read_text())
    assert meta["refers"] == ["PREF-REV-001", "PREF-REV-002"]


def test_ask_precedence_first_and_limit(repo, tmp_path):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    for i in range(3):
        _add(cfg, tmp_path, f"Threads rule {i}", "threads body")
    d = tmp_path / "p.md"
    d.write_text("---\ntitle: Threads precedence\ntype: precedence\nstage: review\nstrength: should\n"
                 "refers: [PREF-REV-001, PREF-REV-002]\n---\nWhen PREF-REV-001 conflicts with PREF-REV-002, PREF-REV-001 wins on threads.\n")
    mind.cmd_add(cfg, d, "global", None, tmp_path)
    out = mind.cmd_ask(cfg, ["threads"], False, None, False, tmp_path, limit=2)
    assert out.startswith("[precedence] PREC-REV-001 | Threads precedence | global | should\n")
    assert out.count("\n  ") == 3   # precedence row + 2 limited rows
    out2 = mind.cmd_ask(cfg, ["threads"], False, None, False, tmp_path, stage="testing")
    assert out2 == "mind: no note matches 'threads'"


def test_ask_precedence_not_promoted_when_hits_do_not_share_a_stage(repo, tmp_path):
    """Two matching notes in different stages must not trigger the
    precedence promotion, even when a precedence note's `refers` names both
    of them: the plan's promotion gate is 'two or more hits share a stage',
    checked before refers is ever consulted."""
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    d1 = tmp_path / "dev.md"
    d1.write_text(mind.render_frontmatter(
        {"title": "Dev threads rule", "type": "preference", "stage": "development", "strength": "should"},
        "threads body.\n"))
    mind.cmd_add(cfg, d1, "global", None, tmp_path)
    d2 = tmp_path / "rev.md"
    d2.write_text(mind.render_frontmatter(
        {"title": "Review threads rule", "type": "preference", "stage": "review", "strength": "should"},
        "threads body.\n"))
    mind.cmd_add(cfg, d2, "global", None, tmp_path)
    d3 = tmp_path / "prec.md"
    d3.write_text("---\ntitle: Dev vs review precedence\ntype: precedence\nstage: review\nstrength: should\n"
                  "refers: [PREF-DEV-001, PREF-REV-001]\n---\nWhen PREF-DEV-001 conflicts with PREF-REV-001, PREF-DEV-001 wins.\n")
    mind.cmd_add(cfg, d3, "global", None, tmp_path)
    out = mind.cmd_ask(cfg, ["threads"], False, None, False, tmp_path)
    assert "[precedence]" not in out


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
        + "\nMode: apply notes silently and cite. Conflicts: use precedence notes.\n"
        + "\n# Global\n\n## review\n- PREF-REV-001 | Global rule | should\n"
        + "\n# proj-a\n\n## review\n- PREF-REV-001 | Project rule | should\n"
        + "\n# Projects\n\n- proj-a | proj-a |  | Describe the project: purpose, kind of work, repo URL.\n"
        + "\n1 draft awaits acceptance: run /mind:ask --drafts\n"
    )


def test_cmd_inject_plural_draft_count_wording(repo, tmp_path):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    _add(cfg, tmp_path, "Draft one", "d", status="draft")
    _add(cfg, tmp_path, "Draft two", "d", status="draft")
    out = mind.cmd_inject(cfg, "startup", tmp_path)
    assert "\n2 drafts await acceptance: run /mind:ask --drafts\n" in out


def test_cmd_inject_reports_malformed_note_count_and_hides_off_enum_stage(repo, tmp_path):
    """An off-enum stage note must disappear from the index (not render
    blank) and be counted, not silently dropped with no trace at all."""
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    _add(cfg, tmp_path, "Good rule", "g")
    bad_path = mind.global_notes_dir(cfg) / "PREF-REV-999-hand-edited.md"
    bad_path.write_text(mind.render_frontmatter(
        {"id": "PREF-REV-999", "title": "Hand edited", "type": "preference", "stage": "not-a-stage",
         "strength": "must", "status": "accepted"}, "b\n"))
    out = mind.cmd_inject(cfg, "clear", tmp_path)
    assert "PREF-REV-999" not in out
    assert f"1 malformed notes skipped, see {cfg.home}\n" in out


def test_cmd_inject_without_project(repo, tmp_path):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    nowhere = tmp_path / "Nowhere"
    nowhere.mkdir()
    out = mind.cmd_inject(cfg, "startup", nowhere)
    assert "\nno notes for nowhere yet\n" in out
    assert out.endswith("\n# Projects\n")


def test_cmd_inject_startup_pushes_local_unpushed_commit(repo, tmp_path):
    """The push-failed message promises the note will go out "on the next
    remember or session start": inject on startup/resume must actually
    push, not just pull, or that promise is a lie."""
    cfg, bare, _ = repo
    mind.cmd_init(cfg)
    (cfg.home / "unpushed.md").write_text("local only\n")
    mind.commit_all(cfg, "mind: local unpushed")
    log_before = _git(["log", "--format=%s", "main"], bare).stdout.splitlines()
    assert "mind: local unpushed" not in log_before
    mind.cmd_inject(cfg, "startup", tmp_path)
    log_after = _git(["log", "--format=%s", "main"], bare).stdout.splitlines()
    assert "mind: local unpushed" in log_after


def test_cmd_inject_compact_makes_no_network_call(repo, tmp_path, monkeypatch):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    monkeypatch.setattr(mind, "pull", lambda c: pytest.fail("pull called on compact"))
    monkeypatch.setattr(mind, "cmd_proposals", lambda c: pytest.fail("cmd_proposals called on compact"))
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


def test_cmd_inject_truncation_round_robins_stages_and_keeps_must(repo, tmp_path, monkeypatch):
    """Without the priority order, a flat prefix truncation would keep every
    identity row before ever showing a product or planning row, and could
    drop a must rule just because it sorts late. Under a budget that keeps
    exactly 4 of these 8 rows, the survivors must be the must row plus one
    row from each of the three stages, not four identity rows."""
    cfg, _, _ = repo
    mind.cmd_init(cfg)

    def add_note(title, stage, strength="should"):
        d = tmp_path / f"{mind._kebab(title)}-{stage}.md"
        d.write_text(mind.render_frontmatter(
            {"title": title, "type": "preference", "stage": stage, "strength": strength}, "b\n"))
        return mind.cmd_add(cfg, d, "global", None, tmp_path)

    add_note("T long enough title to matter here", "identity", "must")
    add_note("T long enough title to matter here", "identity")
    add_note("T long enough title to matter here", "product")
    add_note("T long enough title to matter here", "planning")
    add_note("T long enough title to matter here", "identity")
    add_note("T long enough title to matter here", "product")
    add_note("T long enough title to matter here", "planning")
    add_note("T long enough title to matter here", "product")

    monkeypatch.setattr(mind, "INDEX_BUDGET", 400)
    cfg_no_project = dataclasses.replace(cfg, project="zzz-no-such-project")
    out = mind.cmd_inject(cfg_no_project, "clear", tmp_path)
    assert "+4 more, run /mind:ask <topic>\n" in out
    assert "PREF-ID-001" in out  # the must row
    assert "PREF-ID-002" in out  # one per stage round-robin
    assert "PREF-PROD-001" in out
    assert "PREF-PLAN-001" in out
    assert "PREF-ID-003" not in out
    assert "PREF-PROD-002" not in out
    assert "PREF-PROD-003" not in out
    assert "PREF-PLAN-002" not in out


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


def test_main_inject_reports_config_error_on_stdout_and_returns_0(tmp_path, capsys):
    """The hook only redirects stderr; a ConfigError from inject (e.g. a
    missing MIND_REPO reaching main() directly, or a future validation
    error) must be visible on stdout, not silently exit 0 with nothing
    printed at all."""
    rc = mind.main(["inject", "--event", "startup"], env={}, cwd=tmp_path)
    assert rc == 0
    assert capsys.readouterr().out == "mind: MIND_REPO is not set\n"


def test_main_inject_never_fails_the_hook(repo, tmp_path, monkeypatch, capsys):
    cfg, _, _ = repo
    monkeypatch.setattr(mind, "cmd_inject", lambda c, e, w: (_ for _ in ()).throw(RuntimeError("boom")))
    env = {"MIND_REPO": cfg.repo, "MIND_HOME": str(cfg.home)}
    assert mind.main(["inject", "--event", "startup"], env=env, cwd=tmp_path) == 0
    assert capsys.readouterr().out == "mind: inject failed, RuntimeError: boom\n"


def test_main_inject_redacts_credential_url_from_exception_text(repo, tmp_path, monkeypatch, capsys):
    """A KeyError, UnicodeDecodeError, or any other exception text must not
    leak a token embedded in MIND_REPO (https://x-access-token:TOK@...)."""
    cfg, _, _ = repo
    monkeypatch.setattr(
        mind, "cmd_inject",
        lambda c, e, w: (_ for _ in ()).throw(RuntimeError("https://x-access-token:sekrit@github.com/o/r.git failed")),
    )
    env = {"MIND_REPO": cfg.repo, "MIND_HOME": str(cfg.home)}
    assert mind.main(["inject", "--event", "startup"], env=env, cwd=tmp_path) == 0
    out = capsys.readouterr().out
    assert "sekrit" not in out
    assert "https://***@github.com/o/r.git" in out


def test_ensure_checkout_redacts_credential_url_from_clone_failure(tmp_path, monkeypatch):
    """A clone failure's stderr can echo the repo URL back; an https URL
    with an embedded token must never reach the owner unredacted."""
    home = tmp_path / "h"
    cfg = mind.Config.from_env(
        {"MIND_REPO": "https://x-access-token:sekrit@example.com/o/r.git", "MIND_HOME": str(home)}, tmp_path)

    def fake_git(c, args, cwd, timeout):
        return subprocess.CompletedProcess(
            args=args, returncode=128, stdout="",
            stderr="fatal: could not clone https://x-access-token:sekrit@example.com/o/r.git\n")

    monkeypatch.setattr(mind, "git", fake_git)
    msg = mind.ensure_checkout(cfg)
    assert "sekrit" not in msg
    assert "https://***@example.com/o/r.git" in msg


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


class FakeGh:
    """Records argv; returns a PR URL for `pr create`, a JSON list for `pr list`."""
    def __init__(self, existing=None):
        self.calls = []
        self.existing = existing or []

    def __call__(self, cfg, args, cwd, timeout=20):
        self.calls.append(args)
        if args[:2] == ["pr", "create"]:
            return subprocess.CompletedProcess(args, 0, "https://example.test/pr/7\n", "")
        if args[:2] == ["pr", "list"]:
            return subprocess.CompletedProcess(args, 0, json.dumps(self.existing), "")
        if args[:2] == ["auth", "status"]:
            return subprocess.CompletedProcess(args, 0, "", "Logged in")
        return subprocess.CompletedProcess(args, 0, "", "")


def test_cmd_propose_branch_commits_pr_and_returns_to_main(repo, tmp_path, monkeypatch):
    cfg, bare, _ = repo
    mind.cmd_init(cfg)
    fake = FakeGh(); monkeypatch.setattr(mind, "_gh", fake)
    monkeypatch.setattr(mind, "_today", lambda: "2026-09-12")
    d1 = tmp_path / "a.md"; d1.write_text(DRAFT)
    d2 = tmp_path / "b.md"; d2.write_text(DRAFT.replace("Tests must assert concrete values", "Second claim"))
    out = mind.cmd_propose(cfg, [d1, d2], "Digest Run", "global", None, None, tmp_path)
    assert out == "mind: proposed 2 notes on propose/2026-09-12-digest-run, PR https://example.test/pr/7"
    assert _git(["branch", "--show-current"], cfg.home).stdout.strip() == "main"
    assert not list(cfg.home.parent.glob("worktree-*"))          # temporary worktree removed
    assert _git(["worktree", "list"], cfg.home).stdout.count("\n") == 1   # only the main checkout remains
    log = _git(["log", "--format=%s", "propose/2026-09-12-digest-run", "-2"], bare).stdout.splitlines()
    assert log == ["mind: propose PRIN-TEST-002 Second claim", "mind: propose PRIN-TEST-001 Tests must assert concrete values"]
    assert not list(mind.global_notes_dir(cfg).glob("PRIN-TEST-*.md"))   # main untouched
    create = [c for c in fake.calls if c[:2] == ["pr", "create"]][0]
    assert "--title" in create and create[create.index("--title") + 1] == "mind: Digest Run (2 notes)"
    body = Path(create[create.index("--body-file") + 1]).read_text()
    assert body.startswith("- PRIN-TEST-001 | Tests must assert concrete values | global | must\n  Assert exact values, never `is not None`.\n")


def test_cmd_propose_without_gh(repo, tmp_path, monkeypatch):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    monkeypatch.setattr(mind, "_gh", lambda *a, **k: None)
    monkeypatch.setattr(mind, "_today", lambda: "2026-09-12")
    d1 = tmp_path / "a.md"; d1.write_text(DRAFT)
    assert mind.cmd_propose(cfg, [d1], "x", "global", None, None, tmp_path) == \
        "mind: proposed 1 note on propose/2026-09-12-x, open the PR by hand"


def test_cmd_propose_rejects_batch_on_invalid_draft(repo, tmp_path, monkeypatch):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    monkeypatch.setattr(mind, "_gh", FakeGh())
    good = tmp_path / "a.md"; good.write_text(DRAFT)
    bad = tmp_path / "b.md"; bad.write_text("---\ntitle: x\ntype: wish\nstage: review\nstrength: must\n---\nb\n")
    with pytest.raises(mind.ValidationError, match="b.md: type must be one of"):
        mind.cmd_propose(cfg, [good, bad], "x", "global", None, None, tmp_path)
    assert _git(["branch", "--list", "propose/*"], cfg.home).stdout == ""


def test_cmd_propose_supersedes_flips_old_note_in_branch(repo, tmp_path, monkeypatch):
    cfg, bare, _ = repo
    mind.cmd_init(cfg)
    _add(cfg, tmp_path, "Old rule", "old")
    monkeypatch.setattr(mind, "_gh", FakeGh()); monkeypatch.setattr(mind, "_today", lambda: "2026-09-12")
    d = tmp_path / "n.md"
    d.write_text("---\ntitle: New rule\ntype: preference\nstage: review\nstrength: should\nsupersedes: PREF-REV-001\n---\nnew\n")
    mind.cmd_propose(cfg, [d], "revise", "global", None, None, tmp_path)
    shown = _git(["show", "propose/2026-09-12-revise:global/notes/PREF-REV-001-old-rule.md"], bare).stdout
    assert "status: superseded" in shown


def test_cmd_proposals_lists_open_branches(repo, monkeypatch):
    cfg, _, seed = repo
    mind.cmd_init(cfg)
    _git(["checkout", "-q", "-b", "propose/2026-09-12-x"], seed); (seed / "z.md").write_text("z\n")
    _git(["add", "."], seed); _git(["commit", "-q", "-m", "z"], seed); _git(["push", "-q", "-u", "origin", "propose/2026-09-12-x"], seed)
    monkeypatch.setattr(mind, "_gh", FakeGh(existing=[{"headRefName": "propose/2026-09-12-x", "url": "https://example.test/pr/9"}]))
    assert mind.cmd_proposals(cfg) == [("propose/2026-09-12-x", "https://example.test/pr/9")]


def test_cmd_proposals_lists_unpushed_local_branch(repo):
    """A propose branch committed but never pushed (a failed push) must
    still be visible to the owner, tagged "(unpushed)"."""
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    _git(["checkout", "-q", "-b", "propose/2026-09-12-stuck"], cfg.home)
    (cfg.home / "stuck.md").write_text("stuck\n")
    _git(["add", "."], cfg.home); _git(["commit", "-q", "-m", "stuck"], cfg.home)
    _git(["checkout", "-q", "main"], cfg.home)
    assert mind.cmd_proposals(cfg) == [("propose/2026-09-12-stuck", "(unpushed)")]


def test_cmd_propose_concurrent_inject_sees_no_unmerged_note(repo, tmp_path, monkeypatch):
    """Step 3b concurrency test: while cmd_propose is mid-flight, an inject
    running against the shared checkout must never see the unmerged note."""
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    monkeypatch.setattr(mind, "_today", lambda: "2026-09-12")
    captured = {}

    def fake_gh(c, args, cwd, timeout=20):
        if args[:2] == ["pr", "create"]:
            captured["inject"] = mind.cmd_inject(cfg, "compact", tmp_path)
            return subprocess.CompletedProcess(args, 0, "https://example.test/pr/1\n", "")
        if args[:2] == ["pr", "list"]:
            return subprocess.CompletedProcess(args, 0, "[]", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(mind, "_gh", fake_gh)
    d = tmp_path / "a.md"
    d.write_text(DRAFT)
    mind.cmd_propose(cfg, [d], "concurrency test", "global", None, None, tmp_path)
    assert "Tests must assert concrete values" not in captured["inject"]


def test_cmd_propose_removes_worktree_on_commit_failure(repo, tmp_path, monkeypatch):
    """Given the first draft commits fine but the second draft's commit
    fails / the worktree must still be removed via the `finally` clause."""
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    monkeypatch.setattr(mind, "_gh", FakeGh())
    monkeypatch.setattr(mind, "_today", lambda: "2026-09-12")
    d1 = tmp_path / "a.md"; d1.write_text(DRAFT)
    d2 = tmp_path / "b.md"; d2.write_text(DRAFT.replace("Tests must assert concrete values", "Second claim"))
    real_commit_all = mind.commit_all
    calls = {"n": 0}

    def flaky_commit(c, message):
        calls["n"] += 1
        if calls["n"] == 2:
            return subprocess.CompletedProcess(args=["git", "commit"], returncode=1, stdout="", stderr="hook declined\n")
        return real_commit_all(c, message)

    monkeypatch.setattr(mind, "commit_all", flaky_commit)
    with pytest.raises(mind.ValidationError, match="commit failed: hook declined"):
        mind.cmd_propose(cfg, [d1, d2], "x", "global", None, None, tmp_path)
    assert not list(cfg.home.parent.glob("worktree-*"))
    assert _git(["worktree", "list"], cfg.home).stdout.count("\n") == 1


def test_cmd_propose_push_failure_keeps_branch_locally(repo, tmp_path, monkeypatch):
    """Given the branch's `git push` fails / cmd_propose returns the
    committed-locally message, removes the worktree, and the branch
    survives locally per spec section 11."""
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    monkeypatch.setattr(mind, "_gh", FakeGh())
    monkeypatch.setattr(mind, "_today", lambda: "2026-09-12")
    real_git = mind.git

    def fake_git(c, args, cwd, timeout):
        if args[:1] == ["push"]:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="fatal: push failed\n")
        return real_git(c, args, cwd, timeout)

    monkeypatch.setattr(mind, "git", fake_git)
    d = tmp_path / "a.md"; d.write_text(DRAFT)
    out = mind.cmd_propose(cfg, [d], "x", "global", None, None, tmp_path)
    assert out == "mind: proposal branch propose/2026-09-12-x is committed locally; push failed"
    assert not list(cfg.home.parent.glob("worktree-*"))
    assert _git(["branch", "--list", "propose/2026-09-12-x"], cfg.home).stdout.strip() == "propose/2026-09-12-x"


def test_cmd_propose_reuses_existing_branch_and_pr(repo, tmp_path, monkeypatch):
    """Given propose/2026-09-12-x already exists on origin with PRIN-TEST-001
    (from a prior cmd_propose call) / a second cmd_propose call omits -b from
    worktree add, both notes land on the branch, and no new pr create call
    is made (the existing PR is reused)."""
    cfg, bare, _ = repo
    mind.cmd_init(cfg)
    monkeypatch.setattr(mind, "_today", lambda: "2026-09-12")
    fake = FakeGh()
    monkeypatch.setattr(mind, "_gh", fake)
    d1 = tmp_path / "a.md"; d1.write_text(DRAFT)
    out1 = mind.cmd_propose(cfg, [d1], "x", "global", None, None, tmp_path)
    assert out1 == "mind: proposed 1 note on propose/2026-09-12-x, PR https://example.test/pr/7"
    fake.existing = [{"headRefName": "propose/2026-09-12-x", "url": "https://example.test/pr/7"}]

    captured = {}
    real_git = mind.git

    def spy(c, args, cwd, timeout):
        if args[:2] == ["worktree", "add"]:
            captured["args"] = args
        return real_git(c, args, cwd, timeout)

    monkeypatch.setattr(mind, "git", spy)
    calls_before = len(fake.calls)
    d2 = tmp_path / "b.md"; d2.write_text(DRAFT.replace("Tests must assert concrete values", "Second claim"))
    out2 = mind.cmd_propose(cfg, [d2], "x", "global", None, None, tmp_path)
    assert out2 == "mind: proposed 1 note on propose/2026-09-12-x, PR https://example.test/pr/7"
    assert "-b" not in captured["args"]
    new_calls = fake.calls[calls_before:]
    assert [c for c in new_calls if c[:2] == ["pr", "create"]] == []
    log = _git(["log", "--format=%s", "propose/2026-09-12-x", "-2"], bare).stdout.splitlines()
    assert log == ["mind: propose PRIN-TEST-002 Second claim", "mind: propose PRIN-TEST-001 Tests must assert concrete values"]


def test_cmd_propose_starts_from_fresh_origin_main_not_stale_local(repo, tmp_path, seed_note, monkeypatch):
    """Given origin/main already has PRIN-TEST-001 pushed directly via seed
    while cfg.home's local main is stale/behind / the assigned ID is
    PRIN-TEST-002, proving the worktree started from freshly-fetched
    origin/main, not cfg.home's stale local main."""
    cfg, bare, seed = repo
    mind.cmd_init(cfg)
    monkeypatch.setattr(mind, "_gh", FakeGh())
    monkeypatch.setattr(mind, "_today", lambda: "2026-09-12")
    seed_note(seed, "global/notes/PRIN-TEST-001-other.md", "PRIN-TEST-001", "Other")
    d = tmp_path / "a.md"; d.write_text(DRAFT)
    out = mind.cmd_propose(cfg, [d], "x", "global", None, None, tmp_path)
    assert out == "mind: proposed 1 note on propose/2026-09-12-x, PR https://example.test/pr/7"
    log = _git(["log", "--format=%s", "propose/2026-09-12-x", "-1"], bare).stdout.splitlines()
    assert log == ["mind: propose PRIN-TEST-002 Tests must assert concrete values"]


def test_cmd_propose_unmerged_note_invisible_to_ask_on_main(repo, tmp_path, monkeypatch):
    """Cross-layer: a proposed note must never be visible to ask on the
    shared checkout before the proposal branch is merged."""
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    monkeypatch.setattr(mind, "_gh", FakeGh())
    monkeypatch.setattr(mind, "_today", lambda: "2026-09-12")
    d = tmp_path / "a.md"; d.write_text(DRAFT)
    mind.cmd_propose(cfg, [d], "x", "global", None, None, tmp_path)
    assert mind.cmd_ask(cfg, ["assert", "concrete"], False, None, False, tmp_path) == \
        "mind: no note matches 'assert concrete'"


def test_cmd_propose_note_appears_after_branch_is_merged(repo, tmp_path, monkeypatch):
    """Cross-layer: the trust boundary flips only on merge — after the
    branch is merged into main and synced down, ask finds the note."""
    cfg, bare, seed = repo
    mind.cmd_init(cfg)
    monkeypatch.setattr(mind, "_gh", FakeGh())
    monkeypatch.setattr(mind, "_today", lambda: "2026-09-12")
    d = tmp_path / "a.md"; d.write_text(DRAFT)
    mind.cmd_propose(cfg, [d], "x", "global", None, None, tmp_path)
    _git(["fetch", "-q", "origin", "propose/2026-09-12-x"], seed)
    _git(["merge", "-q", "--ff-only", "origin/propose/2026-09-12-x"], seed)
    _git(["push", "-q"], seed)
    assert mind.sync(cfg) is None
    out = mind.cmd_ask(cfg, ["assert", "concrete"], False, None, False, tmp_path)
    assert "PRIN-TEST-001 | Tests must assert concrete values" in out


def _capture(env, payload, cwd):
    return subprocess.run(["sh", str(PLUGIN / "scripts" / "capture.sh")], env=env, input=json.dumps(payload),
                          capture_output=True, text=True, cwd=cwd)


def test_capture_writes_one_json_line(repo, tmp_path):
    cfg, _, _ = repo
    env = dict(os.environ, MIND_REPO=cfg.repo, MIND_HOME=str(cfg.home), CLAUDE_PLUGIN_ROOT=str(PLUGIN))
    proc = _capture(env, {"session_id": "s1", "prompt": "never use em dashes in output", "cwd": str(tmp_path)}, tmp_path)
    assert proc.returncode == 0 and proc.stdout == ""
    lines = (cfg.home.parent / "pending.jsonl").read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["session"] == "s1" and row["prompt"] == "never use em dashes in output"
    assert row["project"] == tmp_path.name.lower() and row["cwd"] == str(tmp_path)
    assert row["ts"].endswith("Z") and len(row["ts"]) == 20


def test_capture_skips_slash_and_short_and_is_inert_without_repo(repo, tmp_path):
    cfg, _, _ = repo
    env = dict(os.environ, MIND_REPO=cfg.repo, MIND_HOME=str(cfg.home), CLAUDE_PLUGIN_ROOT=str(PLUGIN))
    _capture(env, {"session_id": "s", "prompt": "/mind:ask threads", "cwd": str(tmp_path)}, tmp_path)
    _capture(env, {"session_id": "s", "prompt": "ok thanks", "cwd": str(tmp_path)}, tmp_path)
    assert not (cfg.home.parent / "pending.jsonl").exists()
    env2 = {k: v for k, v in env.items() if k != "MIND_REPO"}
    proc = _capture(env2, {"session_id": "s", "prompt": "a long enough prompt here", "cwd": str(tmp_path)}, tmp_path)
    assert proc.returncode == 0 and not (cfg.home.parent / "pending.jsonl").exists()


def test_capture_caps_file_at_two_megabytes(repo, tmp_path):
    cfg, _, _ = repo
    pending = cfg.home.parent / "pending.jsonl"
    pending.write_text(("{\"ts\": \"2026-01-01T00:00:00Z\", \"prompt\": \"" + "x" * 1000 + "\"}\n") * 2200)
    env = dict(os.environ, MIND_REPO=cfg.repo, MIND_HOME=str(cfg.home), CLAUDE_PLUGIN_ROOT=str(PLUGIN))
    _capture(env, {"session_id": "s", "prompt": "the newest prompt of them all", "cwd": str(tmp_path)}, tmp_path)
    lines = pending.read_text().splitlines()
    assert 1100 <= len(lines) <= 1102
    assert json.loads(lines[-1])["prompt"] == "the newest prompt of them all"


def test_read_and_mark_pending(repo):
    cfg, _, _ = repo
    pending = cfg.home.parent / "pending.jsonl"
    pending.write_text('{"ts": "2026-09-12T10:00:00Z", "prompt": "one"}\n{"ts": "2026-09-12T11:00:00Z", "prompt": "two"}\n')
    assert [r["prompt"] for r in mind.read_pending(cfg, None, 200)] == ["one", "two"]
    mind.mark_pending(cfg, "2026-09-12T10:00:00Z")
    assert (cfg.home.parent / "pending.jsonl.processed").read_text() == "2026-09-12T10:00:00Z\n"
    assert [r["prompt"] for r in mind.read_pending(cfg, None, 200)] == ["two"]
    assert mind.read_pending(cfg, "2026-09-12T11:00:00Z", 200) == []


def test_capture_ignores_malformed_json_stdin(repo, tmp_path):
    """A malformed hook payload must never crash the hook or raise past
    main's try/except; it is simply dropped."""
    cfg, _, _ = repo
    env = dict(os.environ, MIND_REPO=cfg.repo, MIND_HOME=str(cfg.home), CLAUDE_PLUGIN_ROOT=str(PLUGIN))
    proc = subprocess.run(["sh", str(PLUGIN / "scripts" / "capture.sh")], env=env, input="not valid json{",
                          capture_output=True, text=True, cwd=tmp_path)
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert not (cfg.home.parent / "pending.jsonl").exists()


def test_capture_defaults_cwd_when_payload_omits_it(repo, tmp_path):
    """A payload with no "cwd" key must fall back to the subprocess's own
    cwd, never the literal string "None"."""
    cfg, _, _ = repo
    env = dict(os.environ, MIND_REPO=cfg.repo, MIND_HOME=str(cfg.home), CLAUDE_PLUGIN_ROOT=str(PLUGIN))
    _capture(env, {"session_id": "s1", "prompt": "never use em dashes ever again please"}, tmp_path)
    row = json.loads((cfg.home.parent / "pending.jsonl").read_text().splitlines()[0])
    assert row["cwd"] == str(tmp_path)


def test_capture_preserves_non_ascii_and_emoji_unescaped(repo, tmp_path):
    """The written line must carry literal UTF-8 bytes (ensure_ascii=False),
    not \\uXXXX escapes, and round-trip exactly through json.loads."""
    cfg, _, _ = repo
    env = dict(os.environ, MIND_REPO=cfg.repo, MIND_HOME=str(cfg.home), CLAUDE_PLUGIN_ROOT=str(PLUGIN))
    prompt = "siempre usa é acentos y emoji 😀 en las notas"
    _capture(env, {"session_id": "s1", "prompt": prompt, "cwd": str(tmp_path)}, tmp_path)
    line = (cfg.home.parent / "pending.jsonl").read_text().splitlines()[0]
    assert "é" in line and "😀" in line
    assert "\\u" not in line
    assert json.loads(line)["prompt"] == prompt


def test_stale_affirm_retire(repo, tmp_path, monkeypatch):
    cfg, bare, _ = repo
    mind.cmd_init(cfg)
    _add(cfg, tmp_path, "Old should rule", "o")
    _add(cfg, tmp_path, "Old must rule", "m")
    for p in mind.global_notes_dir(cfg).glob("*.md"):
        t = p.read_text().replace(f"affirmed: {dt.date.today().isoformat()}", "affirmed: 2026-01-01")
        if "Old must" in t:
            t = t.replace("strength: should", "strength: must")
        p.write_text(t)
    monkeypatch.setattr(mind, "_today", lambda: "2026-07-01")
    out = mind.cmd_stale(cfg, 90, False, tmp_path)
    assert out == ("PREF-REV-001 | Old should rule | global | should | 2026-01-01 | 181 days\n"
                   "PREF-REV-002 | Old must rule | global | must (must, no decay) | 2026-01-01 | 181 days\n")
    assert mind.cmd_affirm(cfg, "PREF-REV-001", "default") == "mind: affirmed PREF-REV-001 (strength default), pushed"
    meta, _ = mind.parse_frontmatter(next(mind.global_notes_dir(cfg).glob("PREF-REV-001-*.md")).read_text())
    assert meta["affirmed"] == "2026-07-01" and meta["strength"] == "default"
    assert mind.cmd_retire(cfg, "PREF-REV-002") == "mind: retired PREF-REV-002, pushed"
    assert mind.cmd_stale(cfg, 90, False, tmp_path) == "mind: nothing stale"
    assert _git(["log", "--format=%s", "main", "-2"], bare).stdout.splitlines() == ["mind: retire PREF-REV-002", "mind: affirm PREF-REV-001"]


def _raw_note(cfg, name, **over):
    meta = {"id": "PREF-REV-001", "title": "T", "type": "preference", "stage": "review", "scope": "global",
            "strength": "should", "status": "accepted", "affirmed": "2026-09-01", "supersedes": None, "source": "t"}
    meta.update(over)
    p = mind.global_notes_dir(cfg) / name
    p.write_text(mind.render_frontmatter(meta, "body\n"))
    return p


def test_lint_clean(repo, tmp_path):
    cfg, _, _ = repo; mind.cmd_init(cfg); _add(cfg, tmp_path, "Fine", "f")
    assert mind.cmd_lint(cfg, 180) == "mind: lint clean\n"


def test_lint_rows(repo, tmp_path, monkeypatch):
    cfg, _, _ = repo; mind.cmd_init(cfg)
    monkeypatch.setattr(mind, "_today", lambda: "2026-09-12")
    _raw_note(cfg, "PREF-REV-001-t.md")
    _raw_note(cfg, "PREF-REV-002-t.md", id="PREF-REV-002", title="T")            # duplicate title
    _raw_note(cfg, "PREF-REV-003-x.md", id="PREF-REV-003", title="X", supersedes="PREF-REV-001")   # 001 still accepted
    _raw_note(cfg, "PREF-REV-004-y.md", id="PREF-REV-004", title="Y", supersedes="PREF-REV-999")   # dangling
    _raw_note(cfg, "PREF-REV-005-z.md", id="PREF-REV-006", title="Z")            # id/filename mismatch
    _raw_note(cfg, "PREF-REV-007-w.md", id="PREF-REV-007", title="W", stage="wish")   # malformed
    _raw_note(cfg, "PREF-REV-008-old.md", id="PREF-REV-008", title="Old", affirmed="2025-01-01")
    mind._ensure_project(cfg, "stubby")
    out = mind.cmd_lint(cfg, 180)
    assert out == (
        "malformed: global/notes/PREF-REV-007-w.md: stage must be one of: identity, product, planning, development, testing, review, release, deployment, monitoring, security\n"
        "mismatch: global/notes/PREF-REV-005-z.md id=PREF-REV-006\n"
        "dangling: PREF-REV-004 supersedes PREF-REV-999\n"
        "unsuperseded: PREF-REV-001 (by PREF-REV-003)\n"
        "duplicate: PREF-REV-001 and PREF-REV-002\n"
        "stub: stubby\n"
        "stale: PREF-REV-008 (619 days)\n"
        "mind: lint found 7 issues\n"
    )


def test_lint_reports_budget_overflow(repo, tmp_path, monkeypatch):
    cfg, _, _ = repo; mind.cmd_init(cfg)
    monkeypatch.setattr(mind, "INDEX_BUDGET", 200)
    for i in range(8):
        _add(cfg, tmp_path, f"Rule {i}", f"body {i}")
    out = mind.cmd_lint(cfg, 180)
    assert "budget: 4 of 8 global rows inject\n" in out


def test_lint_does_not_flag_duplicate_titles_across_scopes(repo, tmp_path):
    """The dedup key is scoped by prefix ('' vs 'acme/'), so identical
    normalised titles in different scopes never collide."""
    cfg, _, _ = repo; mind.cmd_init(cfg)
    mind._ensure_project(cfg, "acme")
    _raw_note(cfg, "PREF-REV-001-t.md", title="Fine")
    p = mind.project_notes_dir(cfg, "acme") / "PREF-REV-001-t.md"
    p.write_text(mind.render_frontmatter(
        {"id": "PREF-REV-001", "title": "Fine", "type": "preference", "stage": "review",
         "scope": "project:acme", "strength": "should", "status": "accepted",
         "affirmed": "2026-09-01", "supersedes": None, "source": "t"}, "body\n"))
    out = mind.cmd_lint(cfg, 180)
    assert "duplicate:" not in out


def test_lint_malformed_rows_are_global_then_project_order(repo, tmp_path):
    cfg, _, _ = repo; mind.cmd_init(cfg)
    mind._ensure_project(cfg, "zzz")
    _raw_note(cfg, "PREF-REV-007-w.md", id="PREF-REV-007", title="W", stage="wish")
    p = mind.project_notes_dir(cfg, "zzz") / "PREF-REV-008-x.md"
    p.write_text(mind.render_frontmatter(
        {"id": "PREF-REV-008", "title": "X", "type": "preference", "stage": "wish",
         "scope": "project:zzz", "strength": "should", "status": "accepted",
         "affirmed": "2026-09-01", "supersedes": None, "source": "t"}, "body\n"))
    out = mind.cmd_lint(cfg, 180)
    lines = [l for l in out.splitlines() if l.startswith("malformed:")]
    assert lines == [
        "malformed: global/notes/PREF-REV-007-w.md: stage must be one of: identity, product, planning, development, testing, review, release, deployment, monitoring, security",
        "malformed: projects/zzz/notes/PREF-REV-008-x.md: stage must be one of: identity, product, planning, development, testing, review, release, deployment, monitoring, security",
    ]


def test_settings_defaults_and_set(repo):
    cfg, _, _ = repo
    assert mind.load_settings(cfg) == {"auto_answer": True, "escalate": False}
    assert mind.cmd_settings(cfg, ["escalate=true"]) == "mind: settings auto_answer=true escalate=true"
    assert json.loads((cfg.home.parent / "settings.json").read_text()) == {"auto_answer": True, "escalate": True}
    with pytest.raises(mind.ValidationError, match="unknown setting: foo"):
        mind.cmd_settings(cfg, ["foo=1"])
    (cfg.home.parent / "settings.json").write_text('{"auto_answer": "false", "escalate": 3}')
    assert mind.load_settings(cfg) == {"auto_answer": False, "escalate": False}   # string false is false; junk keeps the default


def test_load_settings_corrupt_json_returns_defaults(repo):
    cfg, _, _ = repo
    (cfg.home.parent / "settings.json").write_text("{not json")
    assert mind.load_settings(cfg) == {"auto_answer": True, "escalate": False}


def test_inject_mode_proposals_and_pending_lines(repo, tmp_path, monkeypatch):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    monkeypatch.setattr(mind, "cmd_proposals", lambda c: [("propose/2026-09-12-x", "https://example.test/pr/9")])
    pending = cfg.home.parent / "pending.jsonl"
    pending.write_text("".join(f'{{"ts": "2026-09-12T10:00:{i:02d}Z", "prompt": "p{i}"}}\n' for i in range(25)))
    mind.mark_pending(cfg, "2026-09-12T10:00:04Z")
    out = mind.cmd_inject(cfg, "startup", tmp_path)
    assert "\nMode: apply notes silently and cite. Conflicts: use precedence notes.\n" in out
    assert out.endswith("\n1 open proposal: propose/2026-09-12-x https://example.test/pr/9\n"
                        "\n20 pending prompts since 2026-09-12: run /mind:digest\n")
    mind.cmd_settings(cfg, ["auto_answer=false", "escalate=true"])
    out2 = mind.cmd_inject(cfg, "compact", tmp_path)
    assert "\nMode: confirm before applying a note. Conflicts: always ask.\n" in out2
    assert "1 open proposal: propose/2026-09-12-x https://example.test/pr/9" in out2   # served from the cache on compact


def test_inject_compact_without_proposals_cache_makes_no_call_and_prints_nothing(repo, tmp_path, monkeypatch):
    cfg, _, _ = repo
    mind.cmd_init(cfg)
    monkeypatch.setattr(mind, "cmd_proposals", lambda c: pytest.fail("cmd_proposals called on compact"))
    out = mind.cmd_inject(cfg, "compact", tmp_path)
    assert "open proposal" not in out
