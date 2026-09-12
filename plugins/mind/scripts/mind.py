#!/usr/bin/env python3
"""mind: the owner's preference store. One script, several subcommands."""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import os
import re
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


def _parse_value(raw: str):
    raw = raw.strip()
    if raw in ("null", "~", ""):
        return None
    if raw.startswith("[") and raw.endswith("]"):
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
        meta[key.strip()] = _parse_value(raw)
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


def git_base_args(cfg: Config) -> list[str]:
    args = ["git"]
    if cfg.token:
        helper = "!f() { echo username=x-access-token; echo password=$MIND_TOKEN; }; f"
        args += ["-c", f"credential.helper={helper}"]
    return args


def git(cfg: Config, args: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if cfg.token:
        env["MIND_TOKEN"] = cfg.token
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    return subprocess.run(git_base_args(cfg) + args, cwd=cwd, env=env, capture_output=True,
                          text=True, timeout=timeout)


def _head_date(cfg: Config) -> str:
    out = git(cfg, ["log", "-1", "--format=%cs"], cfg.home, 5)
    return out.stdout.strip() or "unknown"


def ensure_checkout(cfg: Config) -> str | None:
    if (cfg.home / ".git").is_dir():
        return None
    cfg.home.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = git(cfg, ["clone", "-q", cfg.repo, str(cfg.home)], cfg.home.parent, GIT_TIMEOUTS["clone"])
    except subprocess.TimeoutExpired:
        return "mind: clone failed, timed out"
    if proc.returncode != 0:
        return "mind: clone failed, " + proc.stderr.strip().splitlines()[-1:][0] if proc.stderr.strip() else "mind: clone failed"
    return None


def pull(cfg: Config) -> str | None:
    try:
        proc = git(cfg, ["pull", "-q", "--ff-only"], cfg.home, GIT_TIMEOUTS["pull"])
    except subprocess.TimeoutExpired:
        proc = None
    if proc is None or proc.returncode != 0:
        return f"mind: offline, using cached copy from {_head_date(cfg)}"
    return None


def commit_all(cfg: Config, message: str) -> None:
    git(cfg, ["add", "-A"], cfg.home, 10)
    git(cfg, ["commit", "-q", "-m", message], cfg.home, 10)


def _ahead(cfg: Config) -> bool:
    proc = git(cfg, ["rev-list", "--count", "@{u}..HEAD"], cfg.home, 5)
    return proc.returncode == 0 and proc.stdout.strip() not in ("", "0")


def push(cfg: Config) -> str | None:
    try:
        proc = git(cfg, ["push", "-q"], cfg.home, GIT_TIMEOUTS["push"])
    except subprocess.TimeoutExpired:
        return "mind: push failed, note is committed locally; it will push on the next remember or session start"
    if proc.returncode != 0:
        return "mind: push failed, note is committed locally; it will push on the next remember or session start"
    return None


def sync(cfg: Config, pull_only: bool = False) -> str | None:
    if _ahead(cfg):
        try:
            proc = git(cfg, ["pull", "-q", "--rebase"], cfg.home, GIT_TIMEOUTS["pull"])
        except subprocess.TimeoutExpired:
            proc = None
        if proc is None or proc.returncode != 0:
            git(cfg, ["rebase", "--abort"], cfg.home, 5)
            return f"mind: offline, using cached copy from {_head_date(cfg)}"
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
    proc = git(cfg, ["pull", "-q", "--rebase"], cfg.home, GIT_TIMEOUTS["pull"])
    if proc.returncode != 0:
        git(cfg, ["rebase", "--abort"], cfg.home, 5)
        return msg
    return push(cfg)


def global_notes_dir(cfg: Config) -> Path:
    return cfg.home / "global" / "notes"


def project_notes_dir(cfg: Config, slug: str) -> Path:
    return cfg.home / "projects" / slug / "notes"


def _slugify(name: str) -> str:
    return name.lower().removesuffix(".git")


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


def build_index(notes: list[Note], heading: str) -> str:
    accepted = [n for n in notes if n.status == "accepted"]
    out = [f"# {heading}\n"]
    for stage in STAGES:
        rows = [n for n in accepted if n.stage == stage]
        if not rows:
            continue
        out.append(f"\n## {stage}\n")
        out.extend(f"- {n.id} | {n.title} | {n.strength}\n" for n in sorted(rows, key=lambda n: n.id))
    return "".join(out)


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
    global_notes_dir(cfg).mkdir(parents=True, exist_ok=True)
    (cfg.home / "projects").mkdir(exist_ok=True)
    reindex(cfg)
    commit_all(cfg, "mind: init")
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


def cmd_add(cfg: Config, draft: Path, scope: str, project: str | None, cwd: Path) -> str:
    meta, body = parse_frontmatter(draft.read_text())
    errs = validate_meta(meta)
    if errs:
        raise ValidationError("; ".join(errs))
    created_stub = False
    if scope == "global":
        notes_dir, scope_value, prefix = global_notes_dir(cfg), "global", ""
    else:
        candidate = project or resolve_candidate(cfg, cwd)
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
    sync(cfg, pull_only=True)
    path = _write_note(cfg, notes_dir, meta, body)
    reindex(cfg)
    commit_all(cfg, f"mind: add {meta['id']} {meta['title']}")
    msg = sync(cfg)
    if msg and msg.startswith("mind: offline") and _conflicting_id(cfg, path):
        # Another machine took this ID: back out, take the next free one, retry once.
        git(cfg, ["reset", "-q", "--hard", "HEAD~1"], cfg.home, 10)
        git(cfg, ["pull", "-q", "--ff-only"], cfg.home, GIT_TIMEOUTS["pull"])
        path = _write_note(cfg, notes_dir, meta, body)
        reindex(cfg)
        commit_all(cfg, f"mind: add {meta['id']} {meta['title']}")
        msg = sync(cfg)
    note_id = parse_frontmatter(path.read_text())[0]["id"]
    scope_label = "global" if scope == "global" else f"project {prefix[:-1]}"
    result = f"mind: added {prefix}{note_id} ({scope_label}), " + (msg or "pushed")
    if created_stub:
        result += "; project.md is a stub, fill it in"
    return result


def _conflicting_id(cfg: Config, path: Path) -> bool:
    """True when the remote already has a different file with this note's ID."""
    note_id = parse_frontmatter(path.read_text())[0]["id"]
    git(cfg, ["fetch", "-q"], cfg.home, GIT_TIMEOUTS["pull"])
    rel = path.relative_to(cfg.home).parent.as_posix()
    listing = git(cfg, ["ls-tree", "--name-only", "@{u}", rel + "/"], cfg.home, 5).stdout.split()
    return any(Path(p).name.startswith(note_id + "-") and Path(p).name != path.name for p in listing)


def _find_note(cfg: Config, note_id: str) -> Note | None:
    dirs = [global_notes_dir(cfg)] + [project_notes_dir(cfg, s) for s in list_projects(cfg)]
    for d in dirs:
        for n in load_notes(d):
            if n.id == note_id:
                return n
    return None


def cmd_accept(cfg: Config, note_id: str) -> str:
    note = _find_note(cfg, note_id)
    if note is None:
        raise ValidationError(f"no note with id {note_id}")
    note.meta["status"] = "accepted"
    note.meta["affirmed"] = _today()
    note.path.write_text(render_frontmatter(note.meta, note.body))
    reindex(cfg)
    commit_all(cfg, f"mind: accept {note_id}")
    msg = sync(cfg)
    return f"mind: accepted {note_id}, " + (msg or "pushed")


def _scoped_notes(cfg: Config, all_projects: bool, project: str | None, cwd: Path) -> list[tuple[str, Note]]:
    rows = [("", n) for n in load_notes(global_notes_dir(cfg))]
    if all_projects:
        slugs = list_projects(cfg)
    else:
        slug = match_project(cfg, project or resolve_candidate(cfg, cwd))
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
        hits = sum(1 for t in lowered if t in hay)
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


def _truncate(section: str, keep: int) -> str:
    """Keep the heading and the first `keep` note rows; say how many were cut."""
    lines = section.splitlines(keepends=True)
    rows = [i for i, l in enumerate(lines) if l.startswith("- ")]
    if keep >= len(rows):
        return section
    cut = len(rows) - keep
    last = rows[keep - 1] + 1 if keep > 0 else rows[0]
    return "".join(lines[:last]) + f"+{cut} more, run /mind:ask <topic>\n"


def _fit(global_idx: str, project_idx: str, projects_idx: str) -> tuple[str, str]:
    budget = INDEX_BUDGET - len(projects_idx)
    total = len(global_idx) + len(project_idx)
    if total <= budget:
        return global_idx, project_idx
    # Shrink global row by row, then project.
    for idx_name in ("global", "project"):
        cur = global_idx if idx_name == "global" else project_idx
        rows = sum(1 for l in cur.splitlines() if l.startswith("- "))
        while rows > 0 and len(global_idx) + len(project_idx) > budget:
            rows -= 1
            cur = _truncate(cur, rows)
            if idx_name == "global":
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
        msg = pull(cfg)
        if msg:
            out.append(msg + "\n")
    out.append(PROTOCOL.format(home=cfg.home))
    global_idx = (cfg.home / "global" / "index.md").read_text() if (cfg.home / "global" / "index.md").is_file() else "# Global\n"
    candidate = resolve_candidate(cfg, cwd)
    slug = match_project(cfg, candidate)
    project_idx = (cfg.home / "projects" / slug / "index.md").read_text() if slug else f"no notes for {candidate} yet\n"
    projects_idx = (cfg.home / "projects" / "index.md").read_text() if (cfg.home / "projects" / "index.md").is_file() else "# Projects\n"
    global_idx, project_idx = _fit(global_idx, project_idx, projects_idx)
    out += ["\n" + global_idx, "\n" + project_idx, "\n" + projects_idx]
    drafts = _draft_count(cfg)
    if drafts:
        noun = "note awaits" if drafts == 1 else "notes await"
        out.append(f"\n{drafts} draft {noun} acceptance: run /mind:ask --drafts\n")
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
    try:
        cfg = Config.from_env(env, cwd)
    except ConfigError as exc:
        print(f"mind: {exc}", file=sys.stderr)
        return 1
    if args.cmd == "inject":
        try:
            msg = ensure_checkout(cfg) or cmd_inject(cfg, args.event, cwd)
        except Exception as exc:
            print(f"mind: inject failed, {exc}")
            return 0
        print(msg)
        return 0
    try:
        if args.cmd == "init":
            msg = ensure_checkout(cfg) or cmd_init(cfg)
        elif args.cmd == "add":
            msg = ensure_checkout(cfg) or cmd_add(cfg, Path(args.draft), args.scope, args.project, cwd)
        elif args.cmd == "accept":
            msg = ensure_checkout(cfg) or cmd_accept(cfg, args.note_id)
        elif args.cmd == "ask":
            msg = ensure_checkout(cfg) or cmd_ask(cfg, args.terms, args.all, args.project, args.drafts, cwd)
        elif args.cmd == "reindex":
            reindex(cfg)
            msg = "mind: reindexed"
        elif args.cmd == "sync":
            msg = ensure_checkout(cfg) or sync(cfg, pull_only=args.pull_only) or "mind: in sync"
        else:
            print(USAGE, file=sys.stderr)
            return 2
    except ValidationError as exc:
        print(f"mind: {exc}", file=sys.stderr)
        return 1
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
