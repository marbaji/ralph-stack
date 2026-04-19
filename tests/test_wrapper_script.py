"""Tests for scripts/claude-ralph-wrapper.sh.

The wrapper translates ralph-stack's ./ralph/next-iter-model.txt override
into a --model flag on the real `claude` invocation. One-shot: the override
file is consumed (deleted) after being read.

Mapping (per SPIKE-NOTES.md Decision 2):
  opus   -> --model opus
  codex  -> --model opus   (TEMP: opus:max isn't a real CLI alias)
  (else) -> --model <value>
  (none) -> no --model flag
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = REPO_ROOT / "scripts" / "claude-ralph-wrapper.sh"


def _make_stub_claude(bin_dir: Path) -> Path:
    """Create a stub `claude` binary that just echoes its args."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "claude"
    stub.write_text("#!/usr/bin/env bash\necho \"$@\"\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return stub


def _run_wrapper(cwd: Path, bin_dir: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        [str(WRAPPER), *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_codex_override_maps_to_opus(tmp_path: Path) -> None:
    # TEMP: `opus:max` isn't a real Claude Code CLI alias — previous mapping
    # crashed the run with "It may not exist or you may not have access to it."
    # Until a real max-effort alias exists, codex overrides fall back to opus.
    bin_dir = tmp_path / "bin"
    _make_stub_claude(bin_dir)
    (tmp_path / "ralph").mkdir()
    override = tmp_path / "ralph" / "next-iter-model.txt"
    override.write_text("codex\n")

    result = _run_wrapper(tmp_path, bin_dir, "some", "extra", "args")

    assert result.returncode == 0, result.stderr
    assert "--model opus" in result.stdout
    assert "opus:max" not in result.stdout
    assert "some extra args" in result.stdout
    # One-shot: file must be consumed.
    assert not override.exists(), "override file should have been deleted"


def test_opus_override_maps_to_opus(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    _make_stub_claude(bin_dir)
    (tmp_path / "ralph").mkdir()
    override = tmp_path / "ralph" / "next-iter-model.txt"
    override.write_text("opus")

    result = _run_wrapper(tmp_path, bin_dir)

    assert result.returncode == 0, result.stderr
    assert "--model opus" in result.stdout
    assert "opus:max" not in result.stdout
    assert not override.exists()


def test_no_override_passes_through(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    _make_stub_claude(bin_dir)

    # No ralph/next-iter-model.txt at all.
    result = _run_wrapper(tmp_path, bin_dir, "-p", "hello")

    assert result.returncode == 0, result.stderr
    assert "--model" not in result.stdout
    assert "-p hello" in result.stdout


def test_unknown_value_passes_through_as_model(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    _make_stub_claude(bin_dir)
    (tmp_path / "ralph").mkdir()
    override = tmp_path / "ralph" / "next-iter-model.txt"
    override.write_text("sonnet-4.5\n")

    result = _run_wrapper(tmp_path, bin_dir)

    assert result.returncode == 0, result.stderr
    assert "--model sonnet-4.5" in result.stdout
    assert not override.exists()
