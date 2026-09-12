#!/usr/bin/env python3
"""mind: the owner's preference store. One script, several subcommands."""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

USAGE = "usage: mind.py {inject,add,propose,proposals,ask,pending,stale,affirm,retire,lint,settings,doctor,reindex,accept,sync,init} ..."

TYPES = ["principle", "preference", "decision", "procedure", "gotcha", "reference", "precedence"]
STAGES = ["identity", "product", "planning", "development", "testing", "review",
          "release", "deployment", "monitoring", "security"]
STRENGTHS = ["must", "should", "default", "optional"]
STATUSES = ["draft", "accepted", "superseded", "deprecated"]
TYPE_CODES = dict(zip(TYPES, ["PRIN", "PREF", "DEC", "PROC", "GOT", "REF", "PREC"]))
STAGE_CODES = dict(zip(STAGES, ["ID", "PROD", "PLAN", "DEV", "TEST", "REV",
                                "REL", "DEPLOY", "MON", "SEC"]))
REQUIRED = ["title", "type", "stage", "strength"]
KNOWN = REQUIRED + ["id", "scope", "status", "affirmed", "supersedes", "source", "refers"]
ENUMS = {"type": TYPES, "stage": STAGES, "strength": STRENGTHS, "status": STATUSES}


LIST_FIELDS = {"stack", "aliases", "related", "refers"}


def _parse_value(key: str, raw: str):
    raw = raw.strip()
    if raw in ("null", "~", ""):
        return None
    if key in LIST_FIELDS and raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [v.strip() for v in inner.split(",")] if inner else []
    return raw


def _render_value(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, list):
        return "[" + ", ".join(value) + "]"
    return str(value)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    meta: dict = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        key = key.strip()
        meta[key] = _parse_value(key, raw)
    return meta, text[end + 5:]


def render_frontmatter(meta: dict, body: str) -> str:
    lines = [f"{k}: {_render_value(v)}" for k, v in meta.items()]
    return "---\n" + "\n".join(lines) + "\n---\n" + body


def validate_meta(meta: dict) -> list[str]:
    errs = []
    for key in REQUIRED:
        if key not in meta or meta[key] in (None, ""):
            errs.append(f"missing required field: {key}")
        elif key in ENUMS and meta[key] not in ENUMS[key]:
            errs.append(f"{key} must be one of: " + ", ".join(ENUMS[key]))
        elif key == "title" and not isinstance(meta[key], str):
            errs.append("title must be a string")
    if "status" in meta and meta["status"] not in STATUSES:
        errs.append("status must be one of: " + ", ".join(STATUSES))
    for key in meta:
        if key not in KNOWN:
            errs.append(f"unknown field: {key}")
    return errs


@dataclasses.dataclass
class Note:
    path: Path
    meta: dict
    body: str

    @property
    def id(self) -> str: return self.meta.get("id", "")
    @property
    def title(self) -> str: return self.meta.get("title", "")
    @property
    def stage(self) -> str: return self.meta.get("stage", "")
    @property
    def strength(self) -> str: return self.meta.get("strength", "")
    @property
    def status(self) -> str: return self.meta.get("status", "accepted")
    @property
    def first_paragraph(self) -> str:
        return self.body.strip().split("\n\n", 1)[0].strip()


_NOTE_ID_RE = re.compile(r"^[A-Z]+-[A-Z]+-\d{3}$")


def _is_well_formed(meta: dict) -> bool:
    return not validate_meta(meta) and bool(_NOTE_ID_RE.fullmatch(meta.get("id") or ""))


def load_notes(notes_dir: Path) -> list[Note]:
    """Only well-formed notes: a file whose frontmatter fails validate_meta
    (an off-enum stage from a hand edit, most often) or whose id doesn't
    match the ID shape must never render as a blank index row, or count
    toward `must` priority for a stage that then never shows it."""
    notes = []
    if not notes_dir.is_dir():
        return notes
    for path in sorted(notes_dir.glob("*.md")):
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        if _is_well_formed(meta):
            notes.append(Note(path, meta, body))
    return notes


def _malformed_count(cfg: Config) -> int:
    dirs = [global_notes_dir(cfg)] + [project_notes_dir(cfg, s) for s in list_projects(cfg)]
    count = 0
    for d in dirs:
        if not d.is_dir():
            continue
        for path in d.glob("*.md"):
            meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            if not _is_well_formed(meta):
                count += 1
    return count


GIT_TIMEOUTS = {"clone": 30, "pull": 10, "push": 20}


class ConfigError(Exception):
    pass


_REPO_SCHEME_RE = re.compile(r"^(?:ssh|https|file)://|^[^@/\s]+@[^:/\s]+:")


def _validate_repo_url(repo: str) -> None:
    """`--` blocks option injection at the clone call, but not a transport
    like `ext::sh -c ...`, which executes at clone time. Allow only the
    documented forms: ssh://, git@host:, https://, file://, or an absolute
    path."""
    if repo.startswith("/") or _REPO_SCHEME_RE.match(repo):
        return
    raise ConfigError("MIND_REPO must be an ssh, https, file URL or absolute path")


@dataclasses.dataclass(frozen=True)
class Config:
    repo: str
    home: Path
    token: str | None
    project: str | None
    env: dict = dataclasses.field(default_factory=lambda: os.environ)

    @classmethod
    def from_env(cls, env, cwd: Path) -> "Config":
        repo = env.get("MIND_REPO")
        if not repo:
            raise ConfigError("MIND_REPO is not set")
        _validate_repo_url(repo)
        if env.get("MIND_HOME"):
            home = Path(env["MIND_HOME"])
        elif env.get("CLAUDE_PLUGIN_DATA"):
            home = Path(env["CLAUDE_PLUGIN_DATA"]) / "repo"
        else:
            home = Path(env.get("HOME", str(Path.home()))) / ".mind" / "repo"
        return cls(repo, home, env.get("MIND_TOKEN") or None, env.get("MIND_PROJECT") or None)


def _has_configured_identity(cfg: Config) -> bool:
    """True when git already has a usable user.email, from any config file."""
    cwd = cfg.home if (cfg.home / ".git").is_dir() else None
    try:
        proc = subprocess.run(["git", "config", "user.email"], cwd=cwd, env=dict(cfg.env),
                              capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0 and proc.stdout.strip() != ""


def git_base_args(cfg: Config) -> list[str]:
    args = ["git"]
    if cfg.token:
        helper = '!f() { echo username=x-access-token; echo password="$MIND_TOKEN"; }; f'
        # An empty credential.helper resets any helpers configured earlier
        # (global osxkeychain, gh, etc.) so only ours answers and none of
        # them gets a chance to persist the cloud token to disk.
        args += ["-c", "credential.helper=", "-c", f"credential.helper={helper}"]
    if not _has_configured_identity(cfg):
        # A fresh clone (a cloud container, most often) may have no identity
        # configured anywhere; without one, `git commit` fails outright.
        args += ["-c", "user.name=mind", "-c", "user.email=mind@localhost"]
    return args


def git(cfg: Config, args: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess:
    env = dict(cfg.env)
    # An inherited GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE would make every call
    # operate on whatever repo the owner's shell happens to have exported,
    # not cfg.home — including a `reset --hard`.
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_NAMESPACE"):
        env.pop(var, None)
    if cfg.token:
        env["MIND_TOKEN"] = cfg.token
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    # An unknown host key or passphrase prompt would otherwise hang ssh (and
    # so this whole call) past the timeout below.
    env.setdefault("GIT_SSH_COMMAND", "ssh -oBatchMode=yes -oConnectTimeout=5")
    full_args = git_base_args(cfg) + args
    proc = subprocess.Popen(full_args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # subprocess.run's default kill() only signals the direct child; an
        # orphaned ssh grandchild would keep the stdout/stderr pipes open
        # and communicate() would block on it well past this timeout. Kill
        # the whole process group instead.
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        raise
    return subprocess.CompletedProcess(full_args, proc.returncode, stdout, stderr)


def _head_date(cfg: Config) -> str:
    out = git(cfg, ["log", "-1", "--format=%cs"], cfg.home, 5)
    return out.stdout.strip() or "unknown"


_OFFLINE_RE = re.compile(
    r"Could not resolve|Connection|timed out|Permission denied|Authentication|publickey",
    re.IGNORECASE,
)


def _pull_failure_message(cfg: Config, proc: subprocess.CompletedProcess | None) -> str:
    """Classify why a pull (or pull --rebase) failed. `proc` is None on a
    timeout. Order: no upstream at all (a brand-new empty data repo, nothing
    to pull yet) beats every other reading; a timeout or stderr naming a
    network/auth problem is offline; anything else (diverged, dirty tree,
    corrupt repo) is a sync block the owner must act on, not a transient
    offline blip."""
    if not _has_upstream(cfg):
        return "mind: first run, nothing to pull yet"
    if proc is None or _OFFLINE_RE.search(proc.stderr or ""):
        return f"mind: offline, using cached copy from {_head_date(cfg)}"
    lines = (proc.stderr or "").strip().splitlines()
    last = lines[-1] if lines else "unknown error"
    return f"mind: sync blocked: {last}"


_CREDENTIAL_URL_RE = re.compile(r"://[^@/]+@")


def _redact(text: str, cfg: Config | None = None) -> str:
    """Strip a userinfo-embedded credential (https://x-access-token:TOK@...,
    a natural alternative to MIND_TOKEN) from any git stderr or exception
    text before it reaches stdout, plus the literal token value if known."""
    text = _CREDENTIAL_URL_RE.sub("://***@", text)
    if cfg and cfg.token:
        text = text.replace(cfg.token, "***")
    return text


def _is_valid_git_dir(cfg: Config) -> bool:
    """True for a structurally sound repo, even one with no commits yet (a
    freshly cloned brand-new empty data repo)."""
    return git(cfg, ["rev-parse", "--git-dir"], cfg.home, 5).returncode == 0


def ensure_checkout(cfg: Config) -> str | None:
    if (cfg.home / ".git").is_dir():
        if _has_head(cfg) or _is_valid_git_dir(cfg):
            return None
        # A clone the 30s timeout killed mid-transfer (or any other half
        # write) leaves exactly this: .git present, nothing usable inside.
        # Every later run would otherwise report "offline" forever and
        # inject an empty index that reads as "you have no notes".
        return f"mind: checkout at {cfg.home} is broken, delete it and rerun"
    cfg.home.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = git(cfg, ["clone", "-q", "--", cfg.repo, str(cfg.home)], cfg.home.parent, GIT_TIMEOUTS["clone"])
    except subprocess.TimeoutExpired:
        if (cfg.home / ".git").exists():
            shutil.rmtree(cfg.home, ignore_errors=True)
        return "mind: clone failed, timed out"
    if proc.returncode != 0:
        if (cfg.home / ".git").exists():
            shutil.rmtree(cfg.home, ignore_errors=True)
        stderr = proc.stderr.strip()
        msg = ("mind: clone failed, " + stderr.splitlines()[-1]) if stderr else "mind: clone failed"
        return _redact(msg, cfg)
    return None


def pull(cfg: Config) -> str | None:
    try:
        proc = git(cfg, ["pull", "-q", "--ff-only"], cfg.home, GIT_TIMEOUTS["pull"])
    except subprocess.TimeoutExpired:
        proc = None
    if proc is not None and proc.returncode == 0:
        return None
    return _pull_failure_message(cfg, proc)


def commit_all(cfg: Config, message: str) -> subprocess.CompletedProcess:
    add_proc = git(cfg, ["add", "-A"], cfg.home, 10)
    if add_proc.returncode != 0:
        # A failed add (index.lock from a concurrent mind, permissions, a
        # corrupt index) can leave the note file on disk but unstaged, while
        # `git commit` would happily succeed on whatever else was staged.
        # Surface the add's own failure instead of proceeding to commit.
        return add_proc
    return git(cfg, ["commit", "-q", "-m", message], cfg.home, 10)


def _amend_all(cfg: Config, message: str) -> subprocess.CompletedProcess:
    add_proc = git(cfg, ["add", "-A"], cfg.home, 10)
    if add_proc.returncode != 0:
        return add_proc
    return git(cfg, ["commit", "-q", "--amend", "-m", message], cfg.home, 10)


def _require_commit(proc: subprocess.CompletedProcess) -> None:
    if proc.returncode != 0:
        lines = proc.stderr.strip().splitlines()
        raise ValidationError("commit failed: " + (lines[-1] if lines else "unknown error"))


def _has_upstream(cfg: Config) -> bool:
    proc = git(cfg, ["rev-parse", "--abbrev-ref", "@{u}"], cfg.home, 5)
    return proc.returncode == 0


def _has_head(cfg: Config) -> bool:
    proc = git(cfg, ["rev-parse", "--verify", "-q", "HEAD"], cfg.home, 5)
    return proc.returncode == 0


def _ahead(cfg: Config) -> bool:
    if not _has_upstream(cfg):
        # No upstream yet (e.g. a brand-new empty data repo): anything
        # committed locally is unpushed work, so treat it as ahead.
        return _has_head(cfg)
    proc = git(cfg, ["rev-list", "--count", "@{u}..HEAD"], cfg.home, 5)
    return proc.returncode == 0 and proc.stdout.strip() not in ("", "0")


def push(cfg: Config) -> str | None:
    args = ["push", "-q"] if _has_upstream(cfg) else ["push", "-q", "-u", "origin", "HEAD"]
    try:
        proc = git(cfg, args, cfg.home, GIT_TIMEOUTS["push"])
    except subprocess.TimeoutExpired:
        return "mind: push failed, note is committed locally; it will push on the next remember or session start"
    if proc.returncode != 0:
        return "mind: push failed, note is committed locally; it will push on the next remember or session start"
    return None


def _conflicted_paths(cfg: Config) -> list[str]:
    proc = git(cfg, ["diff", "--name-only", "--diff-filter=U"], cfg.home, 5)
    return [line for line in proc.stdout.splitlines() if line]


def _rebase_failure_message(cfg: Config, proc: subprocess.CompletedProcess | None) -> str:
    conflicts = _conflicted_paths(cfg) if proc is not None else []
    git(cfg, ["rebase", "--abort"], cfg.home, 5)
    if conflicts:
        return f"mind: sync conflict in {', '.join(conflicts)}, resolve by hand in {cfg.home}"
    return _pull_failure_message(cfg, proc)


def _rebase_onto_upstream(cfg: Config) -> str | None:
    """Run `pull --rebase`. Returns an error message on failure, else None."""
    try:
        proc = git(cfg, ["pull", "-q", "--rebase"], cfg.home, GIT_TIMEOUTS["pull"])
    except subprocess.TimeoutExpired:
        proc = None
    if proc is None or proc.returncode != 0:
        return _rebase_failure_message(cfg, proc)
    return None


def sync(cfg: Config, pull_only: bool = False) -> str | None:
    status = git(cfg, ["status", "--porcelain"], cfg.home, 10)
    if status.stdout.strip():
        # A hand-edited file (e.g. the remember skill's project.md stub
        # fill-in): commit it first, or the pull --rebase below refuses.
        _require_commit(commit_all(cfg, "mind: manual edits"))
    if _has_upstream(cfg):
        if _ahead(cfg):
            msg = _rebase_onto_upstream(cfg)
            if msg:
                return msg
        else:
            msg = pull(cfg)
            if msg:
                return msg
    if pull_only or not _ahead(cfg):
        return None
    msg = push(cfg)
    if msg is None:
        return None
    # One retry: the remote may have moved between the pull and the push.
    try:
        proc = git(cfg, ["pull", "-q", "--rebase"], cfg.home, GIT_TIMEOUTS["pull"])
    except subprocess.TimeoutExpired:
        proc = None
    if proc is None or proc.returncode != 0:
        git(cfg, ["rebase", "--abort"], cfg.home, 5)
        return msg
    return push(cfg)


def global_notes_dir(cfg: Config) -> Path:
    return cfg.home / "global" / "notes"


def project_notes_dir(cfg: Config, slug: str) -> Path:
    return cfg.home / "projects" / slug / "notes"


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", name.lower().removesuffix(".git")).strip("-.")


_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")


def _validate_slug(slug: str) -> None:
    if not slug or slug in (".", "..") or not _SLUG_RE.fullmatch(slug):
        raise ValidationError(f"invalid project slug: {slug!r}")


def _probe_cfg(cfg: Config) -> Config:
    """A Config for read-only probes in `cwd` -- the one genuinely untrusted
    repo here. No MIND_TOKEN in the child's environment at all (a hostile
    .git/config's core.sshCommand or credential helper must never be able to
    read it), and no token means git_base_args never adds our credential
    helper either."""
    env = {k: v for k, v in cfg.env.items() if k != "MIND_TOKEN"}
    return dataclasses.replace(cfg, token=None, env=env)


def _probe_git(cfg: Config, args: list[str], cwd: Path) -> subprocess.CompletedProcess | None:
    try:
        return git(cfg, args, cwd, 5)
    except subprocess.TimeoutExpired:
        return None


def resolve_candidate(cfg: Config, cwd: Path) -> str:
    if cfg.project:
        return _slugify(cfg.project)
    probe_cfg = _probe_cfg(cfg)
    origin = _probe_git(probe_cfg, ["remote", "get-url", "origin"], cwd)
    if origin is not None and origin.returncode == 0 and origin.stdout.strip():
        return _slugify(origin.stdout.strip().rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1])
    top = _probe_git(probe_cfg, ["rev-parse", "--show-toplevel"], cwd)
    if top is not None and top.returncode == 0 and top.stdout.strip():
        return _slugify(Path(top.stdout.strip()).name)
    return _slugify(cwd.name)


def load_project(cfg: Config, slug: str) -> tuple[dict, str]:
    return parse_frontmatter((cfg.home / "projects" / slug / "project.md").read_text(encoding="utf-8"))


def list_projects(cfg: Config) -> list[str]:
    root = cfg.home / "projects"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "project.md").is_file())


def match_project(cfg: Config, candidate: str) -> str | None:
    for slug in list_projects(cfg):
        meta, _ = load_project(cfg, slug)
        if candidate == slug or candidate in (meta.get("aliases") or []):
            return slug
    return None


def next_id(notes_dir: Path, note_type: str, stage: str) -> str:
    prefix = f"{TYPE_CODES[note_type]}-{STAGE_CODES[stage]}-"
    highest = 0
    for note in load_notes(notes_dir):
        if note.id.startswith(prefix) and note.id[len(prefix):].isdigit():
            highest = max(highest, int(note.id[len(prefix):]))
    return f"{prefix}{highest + 1:03d}"


def _render_notes(notes: list[Note], heading: str) -> str:
    out = [f"# {heading}\n"]
    for stage in STAGES:
        rows = [n for n in notes if n.stage == stage]
        if not rows:
            continue
        out.append(f"\n## {stage}\n")
        out.extend(f"- {n.id} | {n.title} | {n.strength}\n" for n in sorted(rows, key=lambda n: n.id))
    return "".join(out)


def _priority_order(notes: list[Note]) -> list[Note]:
    """Accepted notes ordered for a budget-truncated injection: every `must`
    row first (by id), then one row per stage round-robin among the rest,
    cycling through STAGES in order. A full mind under a tight budget must
    not systematically starve the later stages (security, monitoring, ...)
    just because _truncate used to keep a flat prefix, and a `must` rule
    must never be the one dropped."""
    accepted = [n for n in notes if n.status == "accepted"]
    must = sorted((n for n in accepted if n.strength == "must"), key=lambda n: n.id)
    queues = {s: sorted((n for n in accepted if n.strength != "must" and n.stage == s), key=lambda n: n.id)
              for s in STAGES}
    order = list(must)
    while any(queues.values()):
        for s in STAGES:
            if queues[s]:
                order.append(queues[s].pop(0))
    return order


def build_index(notes: list[Note], heading: str) -> str:
    accepted = [n for n in notes if n.status == "accepted"]
    return _render_notes(accepted, heading)


def build_projects_index(cfg: Config) -> str:
    out = ["# Projects\n"]
    slugs = list_projects(cfg)
    if slugs:
        out.append("\n")
    for slug in slugs:
        meta, body = load_project(cfg, slug)
        first = body.strip().split(". ", 1)[0].rstrip(".") + "." if body.strip() else ""
        out.append(f"- {slug} | {meta.get('name', slug)} | {', '.join(meta.get('stack') or [])} | {first}\n")
    return "".join(out)


def reindex(cfg: Config) -> None:
    (cfg.home / "global").mkdir(parents=True, exist_ok=True)
    (cfg.home / "global" / "index.md").write_text(
        build_index(load_notes(global_notes_dir(cfg)), "Global"), encoding="utf-8")
    (cfg.home / "projects").mkdir(exist_ok=True)
    (cfg.home / "projects" / "index.md").write_text(build_projects_index(cfg), encoding="utf-8")
    for slug in list_projects(cfg):
        (cfg.home / "projects" / slug / "index.md").write_text(
            build_index(load_notes(project_notes_dir(cfg, slug)), slug), encoding="utf-8")


class ValidationError(Exception):
    pass


def _kebab(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]


def _today() -> str:
    return dt.date.today().isoformat()


def cmd_init(cfg: Config) -> str:
    schema = Path(__file__).resolve().parents[1] / "templates" / "schema.md"
    (cfg.home / "schema.md").write_text(schema.read_text(encoding="utf-8"), encoding="utf-8")
    # Indexes are generated from notes, never hand-edited, and never committed:
    # two machines regenerating the same index.md would otherwise be the one
    # file every concurrent add/accept can conflict on.
    (cfg.home / ".gitignore").write_text("**/index.md\n", encoding="utf-8")
    global_notes_dir(cfg).mkdir(parents=True, exist_ok=True)
    (cfg.home / "projects").mkdir(exist_ok=True)
    reindex(cfg)
    _require_commit(commit_all(cfg, "mind: init"))
    msg = sync(cfg)
    return "mind: initialised global/ and projects/" + (f", {msg}" if msg else "")


STUB_PROJECT_BODY = "Describe the project: purpose, kind of work, repo URL.\n"


def _ensure_project(cfg: Config, slug: str) -> bool:
    """Create projects/<slug>/ with a stub project.md. Returns True when created."""
    d = cfg.home / "projects" / slug
    if (d / "project.md").is_file():
        return False
    (d / "notes").mkdir(parents=True, exist_ok=True)
    meta = {"slug": slug, "name": slug, "repo": None, "stack": [], "aliases": [], "related": [], "updated": _today()}
    (d / "project.md").write_text(render_frontmatter(meta, STUB_PROJECT_BODY), encoding="utf-8")
    return True


def _write_note(cfg: Config, notes_dir: Path, meta: dict, body: str) -> Path:
    meta["id"] = next_id(notes_dir, meta["type"], meta["stage"])
    fields = ["id", "title", "type", "stage", "scope", "strength", "status", "affirmed", "supersedes", "source"]
    if "refers" in meta:
        fields.append("refers")
    ordered = {k: meta.get(k) for k in fields}
    path = notes_dir / f"{ordered['id']}-{_kebab(ordered['title'])}.md"
    path.write_text(render_frontmatter(ordered, body), encoding="utf-8")
    return path


def _find_collision(notes_dir: Path, note_id: str, path: Path) -> Path | None:
    """Return another file in notes_dir already claiming this note's ID, if any."""
    for p in notes_dir.glob(f"{note_id}-*.md"):
        if p != path:
            return p
    return None


def cmd_add(cfg: Config, draft: Path, scope: str, project: str | None, cwd: Path) -> str:
    meta, body = parse_frontmatter(draft.read_text(encoding="utf-8"))
    errs = validate_meta(meta)
    if errs:
        raise ValidationError("; ".join(errs))
    created_stub = False
    if scope == "global":
        notes_dir, scope_value, prefix = global_notes_dir(cfg), "global", ""
    else:
        candidate = _slugify(project) if project else resolve_candidate(cfg, cwd)
        _validate_slug(candidate)
        slug = match_project(cfg, candidate) or candidate
        created_stub = _ensure_project(cfg, slug)
        notes_dir, scope_value, prefix = project_notes_dir(cfg, slug), f"project:{slug}", f"{slug}/"
    notes_dir.mkdir(parents=True, exist_ok=True)
    meta.setdefault("status", "accepted")
    meta.setdefault("affirmed", _today())
    meta.setdefault("supersedes", None)
    meta.setdefault("source", f"session {_today()}, {resolve_candidate(cfg, cwd)}")
    meta["scope"] = scope_value
    # Pull first so the ID is assigned against the latest remote state.
    pre_msg = sync(cfg, pull_only=True)
    path = _write_note(cfg, notes_dir, meta, body)
    collision = _find_collision(notes_dir, meta["id"], path)
    if collision is not None:
        path.unlink()
        path = _write_note(cfg, notes_dir, meta, body)
    reindex(cfg)
    _require_commit(commit_all(cfg, f"mind: add {meta['id']} {meta['title']}"))
    msg = push(cfg)
    if msg is not None:
        # Push was rejected: the remote moved. Rebase onto it before trying
        # again — different filenames never conflict in git, so the same ID
        # added on another machine merges in cleanly and must be caught
        # explicitly, before this (not yet pushed) commit goes out.
        rebase_msg = _rebase_onto_upstream(cfg)
        if rebase_msg:
            msg = rebase_msg
        else:
            collision = _find_collision(notes_dir, meta["id"], path)
            if collision is not None:
                path.unlink()
                path = _write_note(cfg, notes_dir, meta, body)
                reindex(cfg)
                # Raise before push: on an amend failure, the pre-amend commit
                # (the one still carrying the duplicate ID) must never be the
                # one that goes out.
                _require_commit(_amend_all(cfg, f"mind: add {meta['id']} {meta['title']}"))
            msg = push(cfg)
    note_id = parse_frontmatter(path.read_text(encoding="utf-8"))[0]["id"]
    scope_label = "global" if scope == "global" else f"project {prefix[:-1]}"
    result = f"mind: added {prefix}{note_id} ({scope_label}), "
    if pre_msg:
        # The ID above was assigned before this pull's outcome was known.
        result += f"{pre_msg}; "
    result += (msg or "pushed")
    if created_stub:
        result += "; project.md is a stub, fill it in"
    return result


def _find_note(cfg: Config, note_id: str) -> Note | None:
    """Resolve `slug/ID` to that project's note. A bare ID searches global
    only, unless it is absent there and unambiguous across projects."""
    if "/" in note_id:
        slug, _, bare_id = note_id.partition("/")
        _validate_slug(slug)
        for n in load_notes(project_notes_dir(cfg, slug)):
            if n.id == bare_id:
                return n
        return None
    for n in load_notes(global_notes_dir(cfg)):
        if n.id == note_id:
            return n
    matches = [n for slug in list_projects(cfg) for n in load_notes(project_notes_dir(cfg, slug)) if n.id == note_id]
    if len(matches) > 1:
        raise ValidationError("ambiguous id, use <slug>/<ID>")
    return matches[0] if matches else None


def cmd_accept(cfg: Config, note_id: str) -> str:
    note = _find_note(cfg, note_id)
    if note is None:
        raise ValidationError(f"no note with id {note_id}")
    note.meta["status"] = "accepted"
    note.meta["affirmed"] = _today()
    note.path.write_text(render_frontmatter(note.meta, note.body), encoding="utf-8")
    reindex(cfg)
    _require_commit(commit_all(cfg, f"mind: accept {note_id}"))
    msg = sync(cfg)
    return f"mind: accepted {note_id}, " + (msg or "pushed")


def _gh(cfg: Config, args: list[str], cwd: Path, timeout: float = 20) -> subprocess.CompletedProcess | None:
    """gh, never through a shell. None when gh is not installed."""
    if shutil.which("gh") is None:
        return None
    env = {k: v for k, v in cfg.env.items() if k != "MIND_TOKEN"}
    try:
        return subprocess.run(["gh", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None


def _worktree_path(cfg: Config, branch: str) -> Path:
    return cfg.home.parent / ("worktree-" + branch.replace("/", "-"))


def _proposal_body(rows: list[tuple[str, "Note"]], cwd_slug: str) -> str:
    out = []
    for prefix, n in rows:
        out.append(f"- {prefix}{n.id} | {n.title} | {n.meta.get('scope')} | {n.strength}\n  {n.first_paragraph}\n")
    out.append(f"\nSource: session {_today()}, {cwd_slug}\n")
    return "".join(out)


def cmd_propose(cfg: Config, drafts: list[Path], topic: str, scope: str, project: str | None,
                body: Path | None, cwd: Path) -> str:
    """Write proposals in a temporary git worktree of the data repo, never in
    the shared checkout: a concurrent inject/ask/add on cfg.home must never
    see an unmerged proposal branch as accepted notes, and cfg.home never
    leaves main."""
    parsed = []
    for d in drafts:
        meta, text = parse_frontmatter(d.read_text(encoding="utf-8"))
        draft_scope = meta.pop("scope", None)
        errs = validate_meta(meta)
        if errs:
            raise ValidationError(f"{d.name}: " + "; ".join(errs))
        parsed.append((d, meta, text, draft_scope))
    topic_slug = _slugify(topic)
    _validate_slug(topic_slug)
    branch = f"propose/{_today()}-{topic_slug}"
    git(cfg, ["fetch", "-q", "origin"], cfg.home, GIT_TIMEOUTS["pull"])
    wt = _worktree_path(cfg, branch)
    remote_has = git(cfg, ["rev-parse", "--verify", "-q", f"origin/{branch}"], cfg.home, 5).returncode == 0
    local_has = git(cfg, ["rev-parse", "--verify", "-q", f"refs/heads/{branch}"], cfg.home, 5).returncode == 0
    # Order matters: a retry after a failed push (branch committed locally,
    # never reached the remote) must append to that same local branch, not
    # die on `worktree add -b` because the branch already exists.
    if remote_has:
        add_args = ["worktree", "add", "-q", "--", str(wt), f"origin/{branch}"]
    elif local_has:
        add_args = ["worktree", "add", "-q", "--", str(wt), branch]
    else:
        start = "HEAD" if not _has_upstream(cfg) else "origin/main"
        add_args = ["worktree", "add", "-q", "-b", branch, "--", str(wt), start]
    proc = git(cfg, add_args, cfg.home, 20)
    if proc.returncode != 0:
        raise ValidationError("worktree failed: " + _redact((proc.stderr.strip().splitlines() or ["unknown"])[-1], cfg))
    if remote_has:
        git(cfg, ["checkout", "-q", "-B", branch, f"origin/{branch}"], wt, 10)
    wcfg = dataclasses.replace(cfg, home=wt)
    rows: list[tuple[str, Note]] = []
    try:
        for d, meta, text, draft_scope in parsed:
            eff_scope, eff_project = scope, project
            if draft_scope == "global":
                eff_scope = "global"
            elif draft_scope and draft_scope.startswith("project:"):
                eff_scope, eff_project = "project", draft_scope.split(":", 1)[1]
            if eff_scope == "global":
                notes_dir, prefix, scope_value = global_notes_dir(wcfg), "", "global"
            else:
                candidate = _slugify(eff_project) if eff_project else resolve_candidate(cfg, cwd)
                _validate_slug(candidate)
                slug = match_project(wcfg, candidate) or candidate
                _ensure_project(wcfg, slug)
                notes_dir, prefix, scope_value = project_notes_dir(wcfg, slug), f"{slug}/", f"project:{slug}"
            notes_dir.mkdir(parents=True, exist_ok=True)
            meta.setdefault("status", "accepted")
            meta.setdefault("affirmed", _today())
            meta.setdefault("supersedes", None)
            meta.setdefault("source", f"proposal {_today()}, {resolve_candidate(cfg, cwd)}")
            meta["scope"] = scope_value
            path = _write_note(wcfg, notes_dir, meta, text)
            old = _find_note(wcfg, meta["supersedes"]) if meta.get("supersedes") else None
            if old is not None:
                old.meta["status"] = "superseded"
                old.path.write_text(render_frontmatter(old.meta, old.body), encoding="utf-8")
            _require_commit(commit_all(wcfg, f"mind: propose {meta['id']} {meta['title']}"))
            rows.append((prefix, Note(path, *parse_frontmatter(path.read_text(encoding="utf-8")))))
        push_proc = git(wcfg, ["push", "-q", "-u", "origin", branch], wt, GIT_TIMEOUTS["push"])
        if push_proc.returncode != 0:
            return f"mind: proposal branch {branch} is committed locally; push failed"
        n = len(rows)
        noun = "note" if n == 1 else "notes"
        body_file = body or (cfg.home.parent / f"proposal-{topic_slug}.md")
        if body is None:
            body_file.write_text(_proposal_body(rows, resolve_candidate(cfg, cwd)), encoding="utf-8")
        listing = _gh(cfg, ["pr", "list", "--head", branch, "--json", "url"], cfg.home)
        if listing is None:
            return f"mind: proposed {n} {noun} on {branch}, open the PR by hand"
        try:
            found = json.loads(listing.stdout or "[]")
        except json.JSONDecodeError:
            found = []
        if found:
            url = found[0].get("url", "")
        else:
            created = _gh(cfg, ["pr", "create", "--base", "main", "--head", branch, "--title",
                                f"mind: {topic} ({n} {noun})", "--body-file", str(body_file)], cfg.home)
            if created is None or created.returncode != 0:
                return f"mind: proposed {n} {noun} on {branch}, open the PR by hand"
            url = created.stdout.strip().splitlines()[-1]
        return f"mind: proposed {n} {noun} on {branch}, PR {_redact(url, cfg)}"
    finally:
        git(cfg, ["worktree", "remove", "--force", "--", str(wt)], cfg.home, 20)
        git(cfg, ["worktree", "prune"], cfg.home, 10)


def cmd_proposals(cfg: Config) -> list[tuple[str, str]]:
    """Remote proposal branches not yet merged into origin/main, with their PR
    URL, plus local propose/* branches that never reached the remote (a
    failed push), marked "(unpushed)" so a stuck proposal is visible to the
    owner. A merged proposal (the PR landed, whether or not GitHub or the
    owner deleted the remote branch) must stop nagging forever: `--no-merged
    origin/main` drops it from both lists, and a merged local branch (the
    worktree's `remove` never deletes the branch it created) is deleted with
    `branch -d`, safe by definition."""
    try:
        git(cfg, ["fetch", "-q", "--prune"], cfg.home, GIT_TIMEOUTS["pull"])
    except subprocess.TimeoutExpired:
        # Offline: fall through and report whatever the last fetch left in
        # the local refs, same "cached copy" contract as sync()/pull().
        pass
    merged = git(cfg, ["branch", "--list", "propose/*", "--merged", "origin/main",
                       "--format=%(refname:short)"], cfg.home, 5)
    for b in merged.stdout.split():
        if b:
            # Already proven merged into origin/main above, so -D (rather
            # than -d) is still safe here: plain -d's own safety check is
            # against HEAD or the branch's upstream, and HEAD (the shared
            # checkout's local main) commonly lags origin/main until the
            # next sync, and the branch's own upstream ref is typically
            # gone by now (the remote propose/* branch was deleted on
            # merge).
            git(cfg, ["branch", "-D", "--", b], cfg.home, 5)
    proc = git(cfg, ["branch", "-r", "--list", "origin/propose/*", "--no-merged", "origin/main",
                     "--format=%(refname:short)"], cfg.home, 5)
    branches = [b.removeprefix("origin/") for b in proc.stdout.split() if b]
    local = git(cfg, ["branch", "--list", "propose/*", "--no-merged", "origin/main",
                      "--format=%(refname:short)"], cfg.home, 5)
    unpushed = [b for b in local.stdout.split() if b and b not in branches]
    urls: dict[str, str] = {}
    listing = _gh(cfg, ["pr", "list", "--state", "open", "--json", "headRefName,url"], cfg.home)
    if listing is not None and listing.returncode == 0:
        try:
            for row in json.loads(listing.stdout or "[]"):
                urls[row.get("headRefName", "")] = row.get("url", "")
        except json.JSONDecodeError:
            pass
    return [(b, urls.get(b, "")) for b in branches] + [(b, "(unpushed)") for b in unpushed]


PENDING_CAP = 2 * 1024 * 1024


def PENDING_FILE(cfg: Config) -> Path:
    return Path(cfg.env["MIND_PENDING"]) if cfg.env.get("MIND_PENDING") else cfg.home.parent / "pending.jsonl"


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_capture(cfg: Config, payload: dict, cwd: Path) -> None:
    prompt = str(payload.get("prompt") or "").strip()
    if len(prompt) < 12 or prompt.startswith("/"):
        return
    path = PENDING_FILE(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > PENDING_CAP:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        path.write_text("".join(lines[len(lines) // 2:]), encoding="utf-8")
    cwd_str = str(payload.get("cwd") or cwd)
    row = {"ts": _utc_now(), "session": str(payload.get("session_id") or ""),
           "project": resolve_candidate(cfg, Path(cwd_str)), "cwd": cwd_str, "prompt": prompt}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _watermark_file(cfg: Config) -> Path:
    return PENDING_FILE(cfg).with_name(PENDING_FILE(cfg).name + ".processed")


def read_pending(cfg: Config, since: str | None, limit: int) -> list[dict]:
    path = PENDING_FILE(cfg)
    if not path.exists():
        return []
    if since is None and _watermark_file(cfg).exists():
        since = _watermark_file(cfg).read_text(encoding="utf-8").strip() or None
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if since and row.get("ts", "") <= since:
            continue
        rows.append(row)
    return rows[:limit]


def mark_pending(cfg: Config, ts: str) -> None:
    _watermark_file(cfg).write_text(ts + "\n", encoding="utf-8")


def _scoped_notes(cfg: Config, all_projects: bool, project: str | None, cwd: Path) -> list[tuple[str, Note]]:
    rows = [("", n) for n in load_notes(global_notes_dir(cfg))]
    if all_projects:
        slugs = list_projects(cfg)
    else:
        candidate = _slugify(project) if project else resolve_candidate(cfg, cwd)
        _validate_slug(candidate)
        slug = match_project(cfg, candidate)
        slugs = [slug] if slug else []
    for slug in slugs:
        rows += [(slug + "/", n) for n in load_notes(project_notes_dir(cfg, slug))]
    return rows


def _age_days(affirmed: str) -> int:
    try:
        return (dt.date.fromisoformat(_today()) - dt.date.fromisoformat(affirmed)).days
    except ValueError:
        return 10**6


def cmd_stale(cfg: Config, days: int, all_projects: bool, cwd: Path) -> str:
    rows = []
    for prefix, n in _scoped_notes(cfg, all_projects, None, cwd):
        if n.status != "accepted":
            continue
        age = _age_days(str(n.meta.get("affirmed") or ""))
        if age > days:
            rows.append((age, prefix, n))
    if not rows:
        return "mind: nothing stale"
    rows.sort(key=lambda r: (-r[0], r[1], r[2].id))
    out = []
    for age, prefix, n in rows:
        strength = n.strength + (" (must, no decay)" if n.strength == "must" else "")
        out.append(f"{prefix}{n.id} | {n.title} | {n.meta.get('scope')} | {strength} | {n.meta.get('affirmed')} | {age} days\n")
    return "".join(out)


def _edit_note(cfg: Config, note_id: str, changes: dict, message: str) -> Note:
    note = _find_note(cfg, note_id)
    if note is None:
        raise ValidationError(f"no note with id {note_id}")
    note.meta.update(changes)
    note.path.write_text(render_frontmatter(note.meta, note.body), encoding="utf-8")
    reindex(cfg)
    _require_commit(commit_all(cfg, message))
    return note


def cmd_affirm(cfg: Config, note_id: str, strength: str | None) -> str:
    changes = {"affirmed": _today()}
    if strength:
        if strength not in STRENGTHS:
            raise ValidationError("strength must be one of: " + ", ".join(STRENGTHS))
        changes["strength"] = strength
    _edit_note(cfg, note_id, changes, f"mind: affirm {note_id}")
    msg = sync(cfg)
    suffix = f" (strength {strength})" if strength else ""
    return f"mind: affirmed {note_id}{suffix}, " + (msg or "pushed")


def cmd_retire(cfg: Config, note_id: str) -> str:
    _edit_note(cfg, note_id, {"status": "deprecated"}, f"mind: retire {note_id}")
    msg = sync(cfg)
    return f"mind: retired {note_id}, " + (msg or "pushed")


def _all_note_files(cfg: Config) -> list[tuple[str, Path]]:
    out = [("", p) for p in sorted(global_notes_dir(cfg).glob("*.md"))] if global_notes_dir(cfg).is_dir() else []
    for slug in list_projects(cfg):
        out += [(slug + "/", p) for p in sorted(project_notes_dir(cfg, slug).glob("*.md"))]
    return out


def cmd_lint(cfg: Config, days: int) -> str:
    # Two passes, not one: every malformed row must precede every mismatch
    # row (file order within each group), and a single interleaved pass over
    # _all_note_files (sorted by path) would instead interleave them by file
    # order across both categories -- wrong whenever a mismatch's file sorts
    # before a malformed one's, as the plan's own pinned test does (005
    # mismatch, 007 malformed).
    rows: list[str] = []
    wellformed: list[tuple[str, Path, dict, str]] = []
    for prefix, path in _all_note_files(cfg):
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        rel = path.relative_to(cfg.home).as_posix()
        errs = validate_meta(meta)
        if errs or not _NOTE_ID_RE.fullmatch(meta.get("id") or ""):
            rows.append(f"malformed: {rel}: " + ("; ".join(errs) or "bad id"))
            continue
        wellformed.append((prefix, path, meta, body))
    notes: list[tuple[str, Note]] = []
    for prefix, path, meta, body in wellformed:
        rel = path.relative_to(cfg.home).as_posix()
        if not path.name.startswith(meta["id"] + "-"):
            rows.append(f"mismatch: {rel} id={meta['id']}")
        notes.append((prefix, Note(path, meta, body)))
    ids = {p + n.id: n for p, n in notes}
    for p, n in notes:
        sup = n.meta.get("supersedes")
        if sup and (p + sup) not in ids and sup not in ids:
            rows.append(f"dangling: {p}{n.id} supersedes {sup}")
        for ref in n.meta.get("refers") or []:
            if (p + ref) not in ids and ref not in ids:
                rows.append(f"dangling: {p}{n.id} refers to {ref}")
    for p, n in notes:
        sup = n.meta.get("supersedes")
        old = ids.get(p + (sup or "")) or ids.get(sup or "")
        if old is not None and old.status == "accepted":
            rows.append(f"unsuperseded: {p}{old.id} (by {p}{n.id})")
    seen: dict[tuple[str, str], str] = {}
    for p, n in notes:
        if n.status != "accepted":
            continue
        key = (p, re.sub(r"[^a-z0-9]+", " ", n.title.lower()).strip())
        if key in seen:
            rows.append(f"duplicate: {p}{seen[key]} and {p}{n.id}")
        else:
            seen[key] = n.id
    for slug in list_projects(cfg):
        _, body = load_project(cfg, slug)
        if body.strip() == STUB_PROJECT_BODY.strip():
            rows.append(f"stub: {slug}")
    for p, n in notes:
        if n.status == "accepted":
            age = _age_days(str(n.meta.get("affirmed") or ""))
            if age > days:
                rows.append(f"stale: {p}{n.id} ({age} days)")
    global_notes = [n for p, n in notes if p == ""]
    accepted = [n for n in global_notes if n.status == "accepted"]
    projects_idx = build_projects_index(cfg)
    rendered, _ = _fit(global_notes, "Global", None, "", projects_idx)
    kept = rendered.count("\n- ")
    if kept < len(accepted):
        rows.append(f"budget: {kept} of {len(accepted)} global rows inject")
    tail = "mind: lint clean\n" if not rows else f"mind: lint found {len(rows)} issues\n"
    return "".join(r + "\n" for r in rows) + tail


def _checkout_state(cfg: Config) -> str:
    """Read-only classification of cfg.home's checkout: never calls
    ensure_checkout (which clones or mutates). Mirrors its branches with no
    side effects, for `doctor`, which must be safe to run against a home
    that was never cloned."""
    if not (cfg.home / ".git").is_dir():
        return "missing"
    if not _is_valid_git_dir(cfg):
        return "broken (not a git dir)"
    if not _has_head(cfg):
        return "broken (no HEAD)"
    return "ok"


def _remote_reachable(cfg: Config) -> tuple[bool, int | str]:
    """`git ls-remote` against cfg.repo directly (not the "origin" remote
    name), so this works even when cfg.home was never cloned."""
    t0 = time.monotonic()
    try:
        proc = git(cfg, ["ls-remote", "--heads", "--", cfg.repo], cfg.home.parent, 10)
    except (subprocess.TimeoutExpired, OSError):
        return False, "unreachable"
    if proc.returncode == 0:
        return True, int((time.monotonic() - t0) * 1000)
    lines = proc.stderr.strip().splitlines()
    return False, _redact(lines[-1] if lines else "unknown error", cfg)


def _git_user_email(cfg: Config) -> str | None:
    cwd = cfg.home if (cfg.home / ".git").is_dir() else None
    try:
        proc = subprocess.run(["git", "config", "user.email"], cwd=cwd, env=dict(cfg.env),
                              capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        return None
    value = proc.stdout.strip()
    return value if proc.returncode == 0 and value else None


def cmd_doctor(cfg: Config) -> str:
    lines: list[str] = []
    lines.append(_redact(
        f"config: MIND_REPO={cfg.repo} MIND_HOME={cfg.home} "
        f"MIND_TOKEN={'set' if cfg.token else 'unset'} MIND_PROJECT={cfg.project or 'unset'}", cfg))
    state = _checkout_state(cfg)
    lines.append(f"checkout: {state}")
    lines.append("upstream: main tracks origin/main" if state == "ok" and _has_upstream(cfg) else "upstream: none")
    reachable, info = _remote_reachable(cfg)
    lines.append(f"remote: reachable ({info} ms)" if reachable else f"remote: unreachable ({_redact(str(info), cfg)})")
    email = _git_user_email(cfg)
    lines.append(f"identity: {email or 'none, will use mind@localhost'}")
    version_proc = _gh(cfg, ["--version"], cfg.home)
    if version_proc is None:
        lines.append("gh: missing")
    else:
        m = re.search(r"gh version (\S+)", version_proc.stdout or "")
        auth_proc = _gh(cfg, ["auth", "status"], cfg.home)
        status = "authenticated" if auth_proc is not None and auth_proc.returncode == 0 else "present, not authenticated"
        lines.append(f"gh: {m.group(1) if m else 'unknown'} {status}")
    pending_path = PENDING_FILE(cfg)
    total = len(pending_path.read_text(encoding="utf-8").splitlines()) if pending_path.exists() else 0
    unprocessed = len(read_pending(cfg, None, 10**6))
    wm_path = _watermark_file(cfg)
    watermark = wm_path.read_text(encoding="utf-8").strip() if wm_path.exists() else "none"
    lines.append(f"pending: {total} lines, {unprocessed} unprocessed, watermark {watermark}")
    settings = load_settings(cfg)
    lines.append(f"settings: auto_answer={str(settings['auto_answer']).lower()} escalate={str(settings['escalate']).lower()}")
    accepted = draft = 0
    for d in [global_notes_dir(cfg)] + [project_notes_dir(cfg, s) for s in list_projects(cfg)]:
        for n in load_notes(d):
            if n.status == "accepted":
                accepted += 1
            elif n.status == "draft":
                draft += 1
    malformed = _malformed_count(cfg)
    lines.append(f"notes: {accepted} accepted, {draft} drafts, {malformed} malformed, {len(list_projects(cfg))} projects")
    return "\n".join(_redact(line, cfg) for line in lines) + "\n"


def _ask_row(prefix: str, note: "Note", drafts: bool, tag: str = "") -> str:
    line = f"{tag}{prefix}{note.id} | {note.title} | {note.meta.get('scope', 'global')} | {note.strength}"
    if drafts:
        line += " | draft"
    return line + "\n  " + note.first_paragraph + "\n"


def cmd_ask(cfg: Config, terms: list[str], all_projects: bool, project: str | None, drafts: bool, cwd: Path,
            limit: int = 10, stage: str | None = None) -> str:
    wanted = "draft" if drafts else "accepted"
    lowered = [t.lower() for t in terms]
    others_scored: list[tuple] = []
    precedence_all: list[tuple] = []
    for prefix, note in _scoped_notes(cfg, all_projects, project, cwd):
        if note.status != wanted:
            continue
        if stage is not None and note.stage != stage:
            continue
        hay = (note.title + "\n" + note.body).lower()
        hits = sum(1 for t in lowered if re.search(rf"\b{re.escape(t)}\b", hay))
        row = (-hits, prefix, note.id, prefix, note)
        if note.meta.get("type") == "precedence":
            # Collected regardless of its own hit count: a precedence note
            # surfaces through `refers` (below) even when its title and body
            # never say the query term, per the documented "When A conflicts
            # with B" convention.
            precedence_all.append(row)
        elif hits or not lowered:
            others_scored.append(row)

    def _qualifies(row: tuple) -> bool:
        return row[0] < 0 or not lowered

    if not others_scored and not any(_qualifies(r) for r in precedence_all):
        return f"mind: no note matches '{' '.join(terms)}'"
    others = sorted(others_scored, key=lambda r: (r[0], r[1], r[2]))
    precedence = sorted(precedence_all, key=lambda r: (r[0], r[1], r[2]))
    stage_counts: dict[str, int] = {}
    for r in others:
        stage_counts[r[4].stage] = stage_counts.get(r[4].stage, 0) + 1
    promote_ok = any(count >= 2 for count in stage_counts.values())
    hit_ids = {r[2] for r in others}
    promoted, remaining_precedence = [], []
    for r in precedence:
        matched_terms = r[0] < 0
        refers = r[4].meta.get("refers") or []
        if promote_ok and (matched_terms or (set(refers) & hit_ids)):
            promoted.append(r)
        elif _qualifies(r):
            remaining_precedence.append(r)
    out = [_ask_row(r[3], r[4], drafts, tag="[precedence] ") for r in promoted]
    rest = sorted(others + remaining_precedence, key=lambda r: (r[0], r[1], r[2]))
    out += [_ask_row(r[3], r[4], drafts) for r in rest[:limit]]
    return "".join(out)


INDEX_BUDGET = 4000
PROTOCOL = (
    "Mind: the owner's preferences. Notes at `{home}`. Before asking the owner a "
    "question, run `/mind:ask <topic>`. If a note answers it, apply it and cite the ID. "
    "If none does, ask once, then `/mind:remember` the answer: universal facts go to "
    "global, facts about this repo go to the project. When this project is silent, look "
    "in related projects' notes. If two notes conflict, surface both IDs and ask. The "
    "project's own `CLAUDE.md` wins over any note. Save memories through "
    "`/mind:remember`, not the auto-memory directory. Anything you inferred rather than "
    "the owner stated goes through `propose`, never `add`. Check precedence notes before "
    "surfacing a conflict.\n"
)

DEFAULT_SETTINGS = {"auto_answer": True, "escalate": False}


def SETTINGS_FILE(cfg: Config) -> Path:
    return Path(cfg.env["MIND_SETTINGS"]) if cfg.env.get("MIND_SETTINGS") else cfg.home.parent / "settings.json"


def load_settings(cfg: Config) -> dict:
    out = dict(DEFAULT_SETTINGS)
    p = SETTINGS_FILE(cfg)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            for k, v in data.items():
                if k not in DEFAULT_SETTINGS:
                    continue
                if isinstance(v, bool):
                    out[k] = v
                elif isinstance(v, str):
                    out[k] = v.strip().lower() in ("1", "true", "yes", "on")
                # any other JSON type keeps the default
        except (json.JSONDecodeError, AttributeError):
            pass
    return out


def cmd_settings(cfg: Config, sets: list[str]) -> str:
    current = load_settings(cfg)
    for item in sets:
        key, _, val = item.partition("=")
        if key not in DEFAULT_SETTINGS:
            raise ValidationError(f"unknown setting: {key}")
        current[key] = val.strip().lower() in ("1", "true", "yes", "on")
    if sets:
        SETTINGS_FILE(cfg).parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE(cfg).write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    return "mind: settings " + " ".join(f"{k}={str(v).lower()}" for k, v in current.items())


def _mode_line(cfg: Config) -> str:
    s = load_settings(cfg)
    mode = "apply notes silently and cite" if s["auto_answer"] else "confirm before applying a note"
    conflicts = "always ask" if s["escalate"] else "use precedence notes"
    return f"Mode: {mode}. Conflicts: {conflicts}.\n"


def _proposals_cache(cfg: Config) -> Path:
    return PENDING_FILE(cfg).with_name(PENDING_FILE(cfg).name + ".proposals")


def _truncate_notes(notes: list[Note], heading: str, keep: int) -> str:
    """Render `heading` plus the top `keep` rows in priority order (every
    `must` row first, then one row per stage round-robin) and say how many
    were cut. Keeping the priority order (not a flat prefix of the full
    render) means a tight budget still surfaces a must rule and a sample of
    every stage, not just whichever stage sorts first."""
    accepted = [n for n in notes if n.status == "accepted"]
    ordered = _priority_order(notes)
    if keep >= len(ordered):
        return _render_notes(accepted, heading)
    cut = len(ordered) - keep
    return _render_notes(ordered[:keep], heading) + f"+{cut} more, run /mind:ask <topic>\n"


def _fit(global_notes: list[Note], global_heading: str,
         project_notes: list[Note] | None, project_heading: str,
         projects_idx: str) -> tuple[str, str]:
    budget = INDEX_BUDGET - len(projects_idx)
    global_idx = _render_notes([n for n in global_notes if n.status == "accepted"], global_heading)
    # `project_heading` doubles as the "no notes for X yet" fallback text
    # when no project matched (project_notes is None): a plain string with
    # no note rows, so it is never itself truncated further.
    project_idx = (project_heading if project_notes is None
                   else _render_notes([n for n in project_notes if n.status == "accepted"], project_heading))
    if len(global_idx) + len(project_idx) <= budget:
        return global_idx, project_idx
    # Shrink global row by row, then project. Priority order (must rows
    # first, then one row per stage round-robin) is re-derived from the
    # original note list each time, never from the previous pass's
    # already-cut output, so the "+N more" count stays correct throughout.
    for which in ("global", "project"):
        notes, heading = (global_notes, global_heading) if which == "global" else (project_notes, project_heading)
        if notes is None:
            continue
        rows = len([n for n in notes if n.status == "accepted"])
        while rows > 0 and len(global_idx) + len(project_idx) > budget:
            rows -= 1
            cur = _truncate_notes(notes, heading, rows)
            if which == "global":
                global_idx = cur
            else:
                project_idx = cur
        if len(global_idx) + len(project_idx) <= budget:
            break
    return global_idx, project_idx


def _draft_count(cfg: Config) -> int:
    dirs = [global_notes_dir(cfg)] + [project_notes_dir(cfg, s) for s in list_projects(cfg)]
    return sum(1 for d in dirs for n in load_notes(d) if n.status == "draft")


def cmd_inject(cfg: Config, event: str, cwd: Path) -> str:
    out = []
    if event in ("startup", "resume"):
        # sync(), not a bare pull: a note committed locally (e.g. a push that
        # failed at the end of a previous /mind:remember) must actually go
        # out on the next startup/resume, not just stay promised forever.
        msg = sync(cfg)
        if msg:
            out.append(msg + "\n")
        else:
            # Indexes are gitignored, so a fresh clone (or one another
            # machine just pushed notes into) has no up-to-date index.md
            # on disk until it is regenerated locally.
            reindex(cfg)
    out.append(PROTOCOL.format(home=cfg.home))
    out.append("\n" + _mode_line(cfg))
    candidate = resolve_candidate(cfg, cwd)
    slug = match_project(cfg, candidate)
    global_notes = load_notes(global_notes_dir(cfg))
    project_notes = load_notes(project_notes_dir(cfg, slug)) if slug else None
    project_heading = slug if slug else f"no notes for {candidate} yet\n"
    projects_index_path = cfg.home / "projects" / "index.md"
    if not projects_index_path.is_file():
        # Indexes are gitignored: a fresh clone, a clear/compact (which never
        # sync/reindex above), or a failed pull can all leave this file
        # missing. Reading it missing as "# Projects\n" would silently tell
        # the owner they have zero projects, a wrong answer rather than an
        # error.
        reindex(cfg)
    projects_idx = projects_index_path.read_text(encoding="utf-8") if projects_index_path.is_file() else "# Projects\n"
    global_idx, project_idx = _fit(global_notes, "Global", project_notes, project_heading, projects_idx)
    out += ["\n" + global_idx, "\n" + project_idx, "\n" + projects_idx]
    drafts = _draft_count(cfg)
    if drafts:
        noun, verb = ("draft", "awaits") if drafts == 1 else ("drafts", "await")
        out.append(f"\n{drafts} {noun} {verb} acceptance: run /mind:ask --drafts\n")
    malformed = _malformed_count(cfg)
    if malformed:
        out.append(f"\n{malformed} malformed notes skipped, see {cfg.home}\n")
    cache = _proposals_cache(cfg)
    if event in ("startup", "resume"):
        try:
            rows = cmd_proposals(cfg)
        except Exception:
            # inject must never lose the payload already built above over a
            # proposals-listing failure (a hung git or gh call): degrade to
            # no proposals line, same as having none.
            rows = []
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(rows), encoding="utf-8")
    else:
        rows = []
        if cache.exists():
            try:
                rows = [tuple(r) for r in json.loads(cache.read_text(encoding="utf-8"))]
            except json.JSONDecodeError:
                rows = []
    if rows:
        n = len(rows)
        noun = "proposal" if n == 1 else "proposals"
        first_b, first_u = rows[0]
        out.append(f"\n{n} open {noun}: {first_b} {first_u}\n")
        out.extend(f"{b} {u}\n" for b, u in rows[1:])
    pending = read_pending(cfg, None, 10**6)
    if len(pending) >= 20:
        wm_path = _watermark_file(cfg)
        date = wm_path.read_text(encoding="utf-8").strip()[:10] if wm_path.exists() else "the beginning"
        out.append(f"\n{len(pending)} pending prompts since {date}: run /mind:digest\n")
    return "".join(out)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mind.py", add_help=True)
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("inject").add_argument("--event", default="startup")
    a = sub.add_parser("add")
    a.add_argument("draft")
    a.add_argument("--scope", choices=["global", "project"], required=True)
    a.add_argument("--project")
    q = sub.add_parser("ask")
    q.add_argument("terms", nargs="*")
    q.add_argument("--all", action="store_true")
    q.add_argument("--project")
    q.add_argument("--drafts", action="store_true")
    q.add_argument("--limit", type=int, default=10)
    q.add_argument("--stage", choices=STAGES)
    sub.add_parser("reindex")
    sub.add_parser("accept").add_argument("note_id")
    sub.add_parser("sync").add_argument("--pull-only", action="store_true")
    sub.add_parser("init")
    pr = sub.add_parser("propose")
    pr.add_argument("drafts", nargs="+")
    pr.add_argument("--topic", required=True)
    pr.add_argument("--scope", choices=["global", "project"], default="global")
    pr.add_argument("--project")
    pr.add_argument("--body")
    sub.add_parser("proposals")
    sub.add_parser("capture")
    pe = sub.add_parser("pending")
    pe.add_argument("--since")
    pe.add_argument("--limit", type=int, default=200)
    pe.add_argument("--mark")
    st = sub.add_parser("stale")
    st.add_argument("--days", type=int, default=90)
    st.add_argument("--all", action="store_true")
    af = sub.add_parser("affirm")
    af.add_argument("note_id")
    af.add_argument("--strength", choices=STRENGTHS)
    sub.add_parser("retire").add_argument("note_id")
    li = sub.add_parser("lint")
    li.add_argument("--days", type=int, default=180)
    se = sub.add_parser("settings")
    se.add_argument("--set", dest="sets", action="append", default=[])
    sub.add_parser("doctor")
    return p


def main(argv: list[str], env=os.environ, cwd: Path | None = None) -> int:
    cwd = cwd or Path.cwd()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        print(USAGE, file=sys.stderr)
        return 2
    if args.cmd is None:
        print(USAGE, file=sys.stderr)
        return 2
    if args.cmd == "inject":
        # The hook redirects only stderr to /dev/null and always exits 0:
        # any message meant to reach the owner (a bad MIND_REPO, a crash)
        # must go to stdout, or it is silently swallowed.
        cfg = None
        try:
            cfg = Config.from_env(env, cwd)
            msg = ensure_checkout(cfg) or cmd_inject(cfg, args.event, cwd)
        except ConfigError as exc:
            print(f"mind: {exc}")
            return 0
        except Exception as exc:
            # A bare KeyError, UnicodeDecodeError on one bad note, etc: name
            # the type so an unactionable "{}" isn't all the owner ever sees.
            print(_redact(f"mind: inject failed, {type(exc).__name__}: {exc}", cfg))
            return 0
        print(msg)
        return 0
    if args.cmd == "capture":
        # Passive capture must never fail the hook or print anything: any
        # problem (no MIND_REPO, malformed hook JSON, a write error) is
        # silently swallowed, same contract as the shell wrapper around it.
        try:
            cfg = Config.from_env(env, cwd)
            payload = json.load(sys.stdin)
            cmd_capture(cfg, payload, cwd)
        except Exception:
            pass
        return 0
    try:
        cfg = Config.from_env(env, cwd)
    except ConfigError as exc:
        print(f"mind: {exc}", file=sys.stderr)
        return 1
    if args.cmd not in ("reindex", "doctor"):
        clone_failed = ensure_checkout(cfg)
        if clone_failed:
            # Unlike inject (the session-start hook, which must never block
            # a session), every other command's whole point is to write or
            # read notes: silently reporting success with nothing done
            # would be worse than failing loudly.
            print(clone_failed, file=sys.stderr)
            return 1
    try:
        if args.cmd == "init":
            msg = cmd_init(cfg)
        elif args.cmd == "add":
            msg = cmd_add(cfg, Path(args.draft), args.scope, args.project, cwd)
        elif args.cmd == "accept":
            msg = cmd_accept(cfg, args.note_id)
        elif args.cmd == "ask":
            msg = cmd_ask(cfg, args.terms, args.all, args.project, args.drafts, cwd,
                          limit=args.limit, stage=args.stage)
        elif args.cmd == "reindex":
            reindex(cfg)
            msg = "mind: reindexed"
        elif args.cmd == "sync":
            msg = sync(cfg, pull_only=args.pull_only) or "mind: in sync"
        elif args.cmd == "propose":
            msg = cmd_propose(cfg, [Path(d) for d in args.drafts], args.topic, args.scope, args.project,
                              Path(args.body) if args.body else None, cwd)
        elif args.cmd == "proposals":
            rows = cmd_proposals(cfg)
            msg = "\n".join(f"{b} {u}" for b, u in rows) if rows else "mind: no open proposals"
        elif args.cmd == "pending":
            if args.mark:
                mark_pending(cfg, args.mark)
                msg = f"mind: pending marked at {args.mark}"
            else:
                rows = read_pending(cfg, args.since, args.limit)
                for row in rows:
                    print(json.dumps(row, ensure_ascii=False))
                return 0
        elif args.cmd == "stale":
            msg = cmd_stale(cfg, args.days, args.all, cwd)
        elif args.cmd == "affirm":
            msg = cmd_affirm(cfg, args.note_id, args.strength)
        elif args.cmd == "retire":
            msg = cmd_retire(cfg, args.note_id)
        elif args.cmd == "lint":
            msg = cmd_lint(cfg, args.days)
        elif args.cmd == "settings":
            msg = cmd_settings(cfg, args.sets)
        elif args.cmd == "doctor":
            msg = cmd_doctor(cfg)
    except ValidationError as exc:
        print(f"mind: {exc}", file=sys.stderr)
        return 1
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
