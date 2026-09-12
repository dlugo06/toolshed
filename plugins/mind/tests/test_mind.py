"""Tests for the mind plugin script (scripts/mind.py) and its hook."""
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
