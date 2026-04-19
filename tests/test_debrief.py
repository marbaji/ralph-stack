from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ralph_stack.debrief import (
    find_unverified_drafts,
    heuristic_flags,
    parse_morning_report,
    render_debrief,
    tail_progress_log,
)
from ralph_stack.paths import ProjectPaths


# ---- parse_morning_report ---------------------------------------------------


def test_parse_morning_report_complete():
    text = (
        "# Ralph Run — plan_2026-04-19-init — 2026-04-19\n"
        "\n"
        "## Status: ✅ COMPLETE\n"
        "\n"
        "## Progress\n"
        "- Plan checkboxes: 47/47 complete (100%)\n"
        "- Iterations: 16\n"
        "- Commits: 16 (branch: feat/ralph-stack-dogfood)\n"
    )
    parsed = parse_morning_report(text)
    assert parsed["status"] == "COMPLETE"
    assert parsed["plan_basename"] == "plan_2026-04-19-init"
    assert parsed["date"] == "2026-04-19"
    assert parsed["checkboxes_done"] == 47
    assert parsed["checkboxes_total"] == 47
    assert parsed["iterations"] == 16
    assert parsed["branch"] == "feat/ralph-stack-dogfood"


def test_parse_morning_report_incomplete():
    text = (
        "# Ralph Run — plan_demo — 2026-04-19\n"
        "\n"
        "## Status: ❌ INCOMPLETE (2 checkboxes still unchecked)\n"
        "\n"
        "## Progress\n"
        "- Plan checkboxes: 3/5 complete (60%)\n"
        "- Iterations: 4\n"
        "- Commits: 4 (branch: feat/demo)\n"
    )
    parsed = parse_morning_report(text)
    assert parsed["status"] == "INCOMPLETE"
    assert parsed["checkboxes_done"] == 3
    assert parsed["checkboxes_total"] == 5


def test_parse_morning_report_paused():
    text = (
        "# Ralph Run — plan_demo — 2026-04-19\n"
        "\n"
        "## Status: ⏸ PAUSED (HUMAN_REQUIRED at iter 7)\n"
        "\n"
        "## Progress\n"
        "- Plan checkboxes: 5/10 complete (50%)\n"
        "- Iterations: 7\n"
        "- Commits: 7 (branch: feat/demo)\n"
    )
    parsed = parse_morning_report(text)
    assert parsed["status"] == "PAUSED"


# ---- find_unverified_drafts -------------------------------------------------


def test_find_unverified_drafts_empty():
    assert find_unverified_drafts("# Guardrails\n\nNo drafts.\n") == []


def test_find_unverified_drafts_one():
    text = (
        "# Combined Guardrails\n\n"
        "## ⚠️ Unverified (iter 71)\n"
        "- **Draft (iter 71):** Don't mock the DB in integration tests.\n"
        "   *Context:* prior run mocked and prod migration broke.\n"
        "   → Promote / Edit / Delete\n"
    )
    drafts = find_unverified_drafts(text)
    assert len(drafts) == 1
    assert "iter 71" in drafts[0]
    assert "mock" in drafts[0].lower()


# ---- tail_progress_log ------------------------------------------------------


def test_tail_progress_log_missing_returns_empty(tmp_path):
    assert tail_progress_log(tmp_path / "nope.txt", lines=5) == ""


def test_tail_progress_log_returns_last_n_lines(tmp_path):
    log = tmp_path / "progress.txt"
    log.write_text("\n".join(f"line {i}" for i in range(20)) + "\n")
    out = tail_progress_log(log, lines=3)
    assert out.strip().splitlines() == ["line 17", "line 18", "line 19"]


# ---- heuristic_flags --------------------------------------------------------


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
             "HOME": str(cwd), "PATH": __import__("os").environ.get("PATH", "")},
    )


def _init_repo_with_commit(tmp_path: Path, msg: str) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "f.txt").write_text("hi")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", msg)


def test_heuristic_flags_zero_checkboxes_with_task_commits(tmp_path):
    _init_repo_with_commit(tmp_path, "task 3: add foo")
    report = {
        "status": "INCOMPLETE",
        "plan_basename": "plan_x",
        "date": "2026-04-19",
        "checkboxes_done": 0,
        "checkboxes_total": 0,
        "iterations": 0,
        "branch": "main",
    }
    flags = heuristic_flags(tmp_path, report, stuck_state=None, plan_path=None)
    assert any("0/0" in f and "commits" in f.lower() for f in flags)


def test_heuristic_flags_branch_mismatch(tmp_path):
    _init_repo_with_commit(tmp_path, "c1")
    report = {
        "status": "COMPLETE",
        "plan_basename": "plan_x",
        "date": "2026-04-19",
        "checkboxes_done": 5,
        "checkboxes_total": 5,
        "iterations": 5,
        "branch": "feat/does-not-exist",
    }
    flags = heuristic_flags(tmp_path, report, stuck_state=None, plan_path=None)
    assert any("branch" in f.lower() and "main" in f for f in flags)


def test_heuristic_flags_escalation_with_complete(tmp_path):
    _init_repo_with_commit(tmp_path, "c1")
    report = {
        "status": "COMPLETE",
        "plan_basename": "plan_x",
        "date": "2026-04-19",
        "checkboxes_done": 5,
        "checkboxes_total": 5,
        "iterations": 5,
        "branch": "main",
    }
    stuck = {"last_escalation_iter": 3, "current_iteration": 5}
    flags = heuristic_flags(tmp_path, report, stuck_state=stuck, plan_path=None)
    assert any("escalat" in f.lower() for f in flags)


def test_heuristic_flags_all_boxes_flipped_but_incomplete(tmp_path):
    _init_repo_with_commit(tmp_path, "c1")
    plan = tmp_path / "plan.md"
    plan.write_text("- [x] a\n- [x] b\n- [x] c\n")
    report = {
        "status": "INCOMPLETE",
        "plan_basename": "plan",
        "date": "2026-04-19",
        "checkboxes_done": 2,
        "checkboxes_total": 3,
        "iterations": 5,
        "branch": "main",
    }
    flags = heuristic_flags(tmp_path, report, stuck_state=None, plan_path=plan)
    assert any("flipped" in f.lower() for f in flags)


def test_heuristic_flags_none_for_clean_complete(tmp_path):
    _init_repo_with_commit(tmp_path, "c1")
    report = {
        "status": "COMPLETE",
        "plan_basename": "plan_x",
        "date": "2026-04-19",
        "checkboxes_done": 5,
        "checkboxes_total": 5,
        "iterations": 5,
        "branch": "main",
    }
    assert heuristic_flags(tmp_path, report, stuck_state=None, plan_path=None) == []


# ---- render_debrief ---------------------------------------------------------


def test_render_debrief_missing_morning_report(tmp_path):
    paths = ProjectPaths(root=tmp_path)
    paths.ensure_dirs()
    with pytest.raises(FileNotFoundError):
        render_debrief(paths)


def test_render_debrief_complete_run(tmp_path):
    _init_repo_with_commit(tmp_path, "c1")
    paths = ProjectPaths(root=tmp_path)
    paths.ensure_dirs()
    paths.morning_report.write_text(
        "# Ralph Run — plan_demo — 2026-04-19\n"
        "\n"
        "## Status: ✅ COMPLETE\n"
        "\n"
        "## Progress\n"
        "- Plan checkboxes: 10/10 complete (100%)\n"
        "- Iterations: 5\n"
        "- Commits: 5 (branch: main)\n"
    )
    out = render_debrief(paths)
    assert "✅ COMPLETE" in out
    assert "plan_demo" in out
    assert "10/10" in out
    assert "## 1. Status" in out
    assert "## 3. Unverified guardrails" in out


def test_render_debrief_incomplete_tails_progress_log(tmp_path):
    _init_repo_with_commit(tmp_path, "c1")
    paths = ProjectPaths(root=tmp_path)
    paths.ensure_dirs()
    paths.morning_report.write_text(
        "# Ralph Run — plan_demo — 2026-04-19\n"
        "\n"
        "## Status: ❌ INCOMPLETE (2 checkboxes still unchecked)\n"
        "\n"
        "## Progress\n"
        "- Plan checkboxes: 3/5 complete (60%)\n"
        "- Iterations: 4\n"
        "- Commits: 4 (branch: main)\n"
    )
    progress = tmp_path / ".ralphex" / "progress" / "progress-plan_demo.txt"
    progress.parent.mkdir(parents=True)
    progress.write_text(
        "iter 1: started\n"
        "iter 4: hit a wall, detector fired, ralphex exited\n"
    )
    out = render_debrief(paths)
    assert "❌ INCOMPLETE" in out
    assert "hit a wall" in out


def test_render_debrief_surfaces_unverified_drafts(tmp_path):
    _init_repo_with_commit(tmp_path, "c1")
    paths = ProjectPaths(root=tmp_path)
    paths.ensure_dirs()
    paths.morning_report.write_text(
        "# Ralph Run — plan_demo — 2026-04-19\n"
        "\n"
        "## Status: ✅ COMPLETE\n"
        "\n"
        "## Progress\n"
        "- Plan checkboxes: 5/5 complete (100%)\n"
        "- Iterations: 5\n"
        "- Commits: 5 (branch: main)\n"
    )
    guardrails = paths.ralph_dir / "combined-guardrails.md"
    guardrails.write_text(
        "## ⚠️ Unverified (iter 4)\n"
        "- **Draft (iter 4):** Skip the foo step when bar is empty.\n"
    )
    out = render_debrief(paths)
    assert "iter 4" in out
    assert "Skip the foo step" in out
