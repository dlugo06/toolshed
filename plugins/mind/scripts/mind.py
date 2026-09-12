#!/usr/bin/env python3
"""mind: the owner's preference store. One script, several subcommands."""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import os
import re
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
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
