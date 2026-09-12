#!/usr/bin/env python3
"""mind: the owner's preference store. One script, several subcommands."""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

USAGE = "usage: mind.py {inject,add,ask,reindex,accept,sync,init} ..."

TYPES = ["principle", "preference", "decision", "procedure", "gotcha", "reference"]
STAGES = ["identity", "product", "planning", "development", "testing", "review",
          "release", "deployment", "monitoring", "security"]
STRENGTHS = ["must", "should", "default", "optional"]
STATUSES = ["draft", "accepted", "superseded", "deprecated"]
TYPE_CODES = dict(zip(TYPES, ["PRIN", "PREF", "DEC", "PROC", "GOT", "REF"]))
STAGE_CODES = dict(zip(STAGES, ["ID", "PROD", "PLAN", "DEV", "TEST", "REV",
                                "REL", "DEPLOY", "MON", "SEC"]))
REQUIRED = ["title", "type", "stage", "strength"]
KNOWN = REQUIRED + ["id", "scope", "status", "affirmed", "supersedes", "source"]
ENUMS = {"type": TYPES, "stage": STAGES, "strength": STRENGTHS, "status": STATUSES}


LIST_FIELDS = {"stack", "aliases", "related"}


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


def load_notes(notes_dir: Path) -> list[Note]:
    notes = []
    if not notes_dir.is_dir():
        return notes
    for path in sorted(notes_dir.glob("*.md")):
        meta, body = parse_frontmatter(path.read_text())
        notes.append(Note(path, meta, body))
    return notes


GIT_TIMEOUTS = {"clone": 30, "pull": 10, "push": 20}


class ConfigError(Exception):
    pass


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
        helper = "!f() { echo username=x-access-token; echo password=$MIND_TOKEN; }; f"
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


def resolve_candidate(cfg: Config, cwd: Path) -> str:
    if cfg.project:
        return _slugify(cfg.project)
    origin = subprocess.run(["git", "remote", "get-url", "origin"], cwd=cwd, capture_output=True, text=True)
    if origin.returncode == 0 and origin.stdout.strip():
        return _slugify(origin.stdout.strip().rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1])
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True)
    if top.returncode == 0 and top.stdout.strip():
        return _slugify(Path(top.stdout.strip()).name)
    return _slugify(cwd.name)


def load_project(cfg: Config, slug: str) -> tuple[dict, str]:
    return parse_frontmatter((cfg.home / "projects" / slug / "project.md").read_text())


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
    (cfg.home / "global" / "index.md").write_text(build_index(load_notes(global_notes_dir(cfg)), "Global"))
    (cfg.home / "projects").mkdir(exist_ok=True)
    (cfg.home / "projects" / "index.md").write_text(build_projects_index(cfg))
    for slug in list_projects(cfg):
        (cfg.home / "projects" / slug / "index.md").write_text(build_index(load_notes(project_notes_dir(cfg, slug)), slug))


class ValidationError(Exception):
    pass


def _kebab(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]


def _today() -> str:
    return dt.date.today().isoformat()


def cmd_init(cfg: Config) -> str:
    schema = Path(__file__).resolve().parents[1] / "templates" / "schema.md"
    (cfg.home / "schema.md").write_text(schema.read_text())
    # Indexes are generated from notes, never hand-edited, and never committed:
    # two machines regenerating the same index.md would otherwise be the one
    # file every concurrent add/accept can conflict on.
    (cfg.home / ".gitignore").write_text("**/index.md\n")
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
    (d / "project.md").write_text(render_frontmatter(meta, STUB_PROJECT_BODY))
    return True


def _write_note(cfg: Config, notes_dir: Path, meta: dict, body: str) -> Path:
    meta["id"] = next_id(notes_dir, meta["type"], meta["stage"])
    ordered = {k: meta.get(k) for k in ["id", "title", "type", "stage", "scope", "strength", "status", "affirmed", "supersedes", "source"]}
    path = notes_dir / f"{ordered['id']}-{_kebab(ordered['title'])}.md"
    path.write_text(render_frontmatter(ordered, body))
    return path


def _find_collision(notes_dir: Path, note_id: str, path: Path) -> Path | None:
    """Return another file in notes_dir already claiming this note's ID, if any."""
    for p in notes_dir.glob(f"{note_id}-*.md"):
        if p != path:
            return p
    return None


def cmd_add(cfg: Config, draft: Path, scope: str, project: str | None, cwd: Path) -> str:
    meta, body = parse_frontmatter(draft.read_text())
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
    note_id = parse_frontmatter(path.read_text())[0]["id"]
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
    note.path.write_text(render_frontmatter(note.meta, note.body))
    reindex(cfg)
    _require_commit(commit_all(cfg, f"mind: accept {note_id}"))
    msg = sync(cfg)
    return f"mind: accepted {note_id}, " + (msg or "pushed")


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


def cmd_ask(cfg: Config, terms: list[str], all_projects: bool, project: str | None, drafts: bool, cwd: Path) -> str:
    wanted = "draft" if drafts else "accepted"
    lowered = [t.lower() for t in terms]
    scored = []
    for prefix, note in _scoped_notes(cfg, all_projects, project, cwd):
        if note.status != wanted:
            continue
        hay = (note.title + "\n" + note.body).lower()
        hits = sum(1 for t in lowered if re.search(rf"\b{re.escape(t)}\b", hay))
        if hits or not lowered:
            scored.append((-hits, prefix, note.id, prefix, note))
    if not scored:
        return f"mind: no note matches '{' '.join(terms)}'"
    out = []
    for _, _, _, prefix, note in sorted(scored, key=lambda r: (r[0], r[1], r[2]))[:10]:
        line = f"{prefix}{note.id} | {note.title} | {note.meta.get('scope', 'global')} | {note.strength}"
        if drafts:
            line += " | draft"
        out.append(line + "\n  " + note.first_paragraph + "\n")
    return "".join(out)


INDEX_BUDGET = 4000
PROTOCOL = (
    "Mind: the owner's preferences. Notes at `{home}`. Before asking the owner a "
    "question, run `/mind:ask <topic>`. If a note answers it, apply it and cite the ID. "
    "If none does, ask once, then `/mind:remember` the answer: universal facts go to "
    "global, facts about this repo go to the project. When this project is silent, look "
    "in related projects' notes. If two notes conflict, surface both IDs and ask. The "
    "project's own `CLAUDE.md` wins over any note. Save memories through "
    "`/mind:remember`, not the auto-memory directory.\n"
)


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
    candidate = resolve_candidate(cfg, cwd)
    slug = match_project(cfg, candidate)
    global_notes = load_notes(global_notes_dir(cfg))
    project_notes = load_notes(project_notes_dir(cfg, slug)) if slug else None
    project_heading = slug if slug else f"no notes for {candidate} yet\n"
    projects_idx = (cfg.home / "projects" / "index.md").read_text() if (cfg.home / "projects" / "index.md").is_file() else "# Projects\n"
    global_idx, project_idx = _fit(global_notes, "Global", project_notes, project_heading, projects_idx)
    out += ["\n" + global_idx, "\n" + project_idx, "\n" + projects_idx]
    drafts = _draft_count(cfg)
    if drafts:
        noun, verb = ("draft", "awaits") if drafts == 1 else ("drafts", "await")
        out.append(f"\n{drafts} {noun} {verb} acceptance: run /mind:ask --drafts\n")
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
    sub.add_parser("reindex")
    sub.add_parser("accept").add_argument("note_id")
    sub.add_parser("sync").add_argument("--pull-only", action="store_true")
    sub.add_parser("init")
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
    try:
        cfg = Config.from_env(env, cwd)
    except ConfigError as exc:
        print(f"mind: {exc}", file=sys.stderr)
        return 1
    if args.cmd != "reindex":
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
            msg = cmd_ask(cfg, args.terms, args.all, args.project, args.drafts, cwd)
        elif args.cmd == "reindex":
            reindex(cfg)
            msg = "mind: reindexed"
        elif args.cmd == "sync":
            msg = sync(cfg, pull_only=args.pull_only) or "mind: in sync"
    except ValidationError as exc:
        print(f"mind: {exc}", file=sys.stderr)
        return 1
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
