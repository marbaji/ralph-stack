from pathlib import Path

import pytest

from ralph_stack.orchestrator import (
    _encode_session_dir_name,
    _find_ralphex_transcript_dir,
    _write_complete_report,
    count_checkboxes,
)
from ralph_stack.paths import ProjectPaths


def test_encode_session_dir_name_matches_claude_code_convention():
    assert _encode_session_dir_name(Path("/Users/mo/Desktop/Claude Code")) == (
        "-Users-mo-Desktop-Claude-Code"
    )


def test_encode_session_dir_name_encodes_dots_as_dash():
    # Observed: /Users/mo/.claude-mem-observer → -Users-mo--claude-mem-observer
    assert _encode_session_dir_name(Path("/Users/mo/.claude-mem-observer")) == (
        "-Users-mo--claude-mem-observer"
    )


def test_encode_session_dir_name_preserves_existing_dashes():
    assert _encode_session_dir_name(Path("/a/ralph-stack/dogfood")) == (
        "-a-ralph-stack-dogfood"
    )


def test_find_ralphex_transcript_dir_uses_cwd_not_mtime(tmp_path, monkeypatch):
    # Simulate an unrelated session dir that has a newer mtime than the one
    # we actually want — this is exactly the bug the dogfood run hit.
    fake_home = tmp_path / "home"
    projects = fake_home / ".claude" / "projects"
    projects.mkdir(parents=True)

    unrelated = projects / "-Users-mo--claude-mem-observer-sessions"
    unrelated.mkdir()
    (unrelated / "decoy.jsonl").write_text("{}\n")

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.delenv("RALPH_STACK_TRANSCRIPT_DIR", raising=False)

    project_root = tmp_path / "my-project"
    project_root.mkdir()
    paths = ProjectPaths(root=project_root)

    result = _find_ralphex_transcript_dir(paths)
    expected_name = _encode_session_dir_name(project_root.resolve())
    assert result == projects / expected_name
    assert result != unrelated


def test_find_ralphex_transcript_dir_env_override_wins(tmp_path, monkeypatch):
    override = tmp_path / "custom-session-dir"
    monkeypatch.setenv("RALPH_STACK_TRANSCRIPT_DIR", str(override))
    paths = ProjectPaths(root=tmp_path / "project")
    assert _find_ralphex_transcript_dir(paths) == override


def test_count_checkboxes_mixed(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text(
        "# Plan\n\n"
        "- [x] done one\n"
        "- [ ] pending one\n"
        "  - [x] nested done\n"
        "  - [ ] nested pending\n"
        "- [X] capital-X counts\n"
    )
    assert count_checkboxes(plan) == (3, 5)


def test_count_checkboxes_missing_file_returns_zero(tmp_path):
    assert count_checkboxes(tmp_path / "does-not-exist.md") == (0, 0)


def test_write_complete_report_marks_incomplete_when_boxes_remain(tmp_path, monkeypatch):
    # Regression for the Run 1 dogfood crash: ralphex exited at iter 4 after
    # only 3 of 10 tasks landed, but the report said "✅ COMPLETE, 0/0".
    plan = tmp_path / "plan.md"
    plan.write_text("- [x] t1\n- [x] t2\n- [x] t3\n- [ ] t4\n- [ ] t5\n")
    project = tmp_path / "project"
    project.mkdir()
    paths = ProjectPaths(root=project)
    paths.ensure_dirs()
    monkeypatch.delenv("RALPH_STACK_PLAN_BASENAME", raising=False)

    _write_complete_report(paths, plan)

    report = paths.post_run_report.read_text()
    assert "❌ INCOMPLETE" in report
    assert "3/5" in report
    assert "2 checkboxes still unchecked" in report
    assert "✅ COMPLETE" not in report


def test_write_complete_report_marks_complete_when_all_boxes_done(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    plan.write_text("- [x] t1\n- [x] t2\n- [x] t3\n")
    project = tmp_path / "project"
    project.mkdir()
    paths = ProjectPaths(root=project)
    paths.ensure_dirs()
    monkeypatch.delenv("RALPH_STACK_PLAN_BASENAME", raising=False)

    _write_complete_report(paths, plan)

    report = paths.post_run_report.read_text()
    assert "✅ COMPLETE" in report
    assert "3/3" in report
    assert "INCOMPLETE" not in report


def test_write_complete_report_finds_plan_after_ralphex_moves_it(tmp_path, monkeypatch):
    # Regression for Bug 6: after ralphex finishes, it auto-moves the plan to
    # `completed/<basename>` and commits that move. `_write_complete_report`
    # runs *after* that move, so `count_checkboxes(original_path)` reads a
    # missing file and returns (0, 0) — the report then misreports the run
    # as ❌ INCOMPLETE with 0/0 even though every box was flipped.
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    original_plan = plans_dir / "plan.md"
    completed_dir = plans_dir / "completed"
    completed_dir.mkdir()
    moved_plan = completed_dir / "plan.md"
    moved_plan.write_text("- [x] t1\n- [x] t2\n- [x] t3\n")
    # Original path no longer exists — that's the bug's precondition.
    assert not original_plan.exists()

    project = tmp_path / "project"
    project.mkdir()
    paths = ProjectPaths(root=project)
    paths.ensure_dirs()
    monkeypatch.delenv("RALPH_STACK_PLAN_BASENAME", raising=False)

    _write_complete_report(paths, original_plan)

    report = paths.post_run_report.read_text()
    assert "✅ COMPLETE" in report
    assert "3/3" in report
    assert "0/0" not in report
    assert "INCOMPLETE" not in report


def test_find_ralphex_transcript_dir_returns_path_even_if_missing(tmp_path, monkeypatch):
    # The dir may not exist yet when ralph-stack starts — ralphex's first
    # session hasn't written a JSONL. ClaudeCodeStreamJsonSource.read_new()
    # tolerates missing dirs, so the orchestrator must not error here.
    fake_home = tmp_path / "home"
    (fake_home / ".claude" / "projects").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.delenv("RALPH_STACK_TRANSCRIPT_DIR", raising=False)

    paths = ProjectPaths(root=tmp_path / "brand-new-project")
    result = _find_ralphex_transcript_dir(paths)
    assert not result.exists()
    assert result.parent == fake_home / ".claude" / "projects"
