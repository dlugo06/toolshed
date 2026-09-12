#!/usr/bin/env python3
"""mind: the owner's preference store. One script, several subcommands."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

USAGE = "usage: mind.py {inject,add,ask,reindex,accept,sync,init} ..."


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
