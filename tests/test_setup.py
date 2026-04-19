from __future__ import annotations

from pathlib import Path

import pytest

from ralph_stack import setup as setup_mod
from ralph_stack.paths import ProjectPaths


def test_initresult_fields():
    r = setup_mod.InitResult(
        created=["ralph/"],
        skipped=[],
        upserted={},
        ensured=[],
        next_step="Ready.",
    )
    assert r.created == ["ralph/"]
    assert r.skipped == []
    assert r.upserted == {}
    assert r.ensured == []
    assert r.next_step == "Ready."


def test_initialize_fresh_directory(tmp_path, monkeypatch):
    # Redirect ~/.ralph/ to a tmp location so the test doesn't touch the real HOME
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    paths = ProjectPaths(root=tmp_path / "project")
    paths.root.mkdir()

    result = setup_mod.initialize(paths)

    # Directory effects
    assert (paths.root / "ralph").is_dir()
    assert (paths.root / "tasks" / "lessons.md").is_file()
    assert (paths.root / ".ralphex" / "config").is_file()
    assert (paths.root / ".gitignore").is_file()
    assert (fake_home / ".ralph" / "guardrails.md").is_file()

    # .ralphex/config seeded keys
    cfg = (paths.root / ".ralphex" / "config").read_text()
    assert "claude_command = " in cfg
    assert "use_worktree = true" in cfg
    assert "task_model = opus" in cfg
    assert "plans_dir" not in cfg  # no plan arg given

    # .gitignore seeded entries
    gi = (paths.root / ".gitignore").read_text()
    assert "ralph/" in gi
    assert ".ralphex/*" in gi
    assert "!.ralphex/config" in gi

    # tasks/lessons.md content
    lessons = (paths.root / "tasks" / "lessons.md").read_text()
    assert "# Lessons" in lessons
    assert "Two-tier system" in lessons
    assert "~/.ralph/guardrails.md" in lessons

    # InitResult populated
    assert "ralph/" in result.created
    assert "tasks/lessons.md" in result.created
    assert "ralph-stack run" in result.next_step


def test_initialize_fully_idempotent(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    paths = ProjectPaths(root=tmp_path / "project")
    paths.root.mkdir()

    # First run
    setup_mod.initialize(paths)

    # Second run — everything should be skipped, nothing upserted
    result = setup_mod.initialize(paths)

    assert "ralph/" in result.skipped
    assert "tasks/lessons.md" in result.skipped
    assert ".ralphex/config" in result.skipped
    assert ".gitignore" in result.skipped
    assert result.upserted == {}
    assert result.created == []
    assert "~/.ralph/guardrails.md" in result.ensured


def test_initialize_preserves_existing_lessons_byte_for_byte(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    paths = ProjectPaths(root=tmp_path / "project")
    paths.root.mkdir()
    (paths.root / "tasks").mkdir()
    custom_content = "# My custom lessons\n\n- rule 1\n- rule 2\n"
    (paths.root / "tasks" / "lessons.md").write_text(custom_content)

    setup_mod.initialize(paths)

    assert (paths.root / "tasks" / "lessons.md").read_text() == custom_content


def test_initialize_gitignore_merge(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    paths = ProjectPaths(root=tmp_path / "project")
    paths.root.mkdir()
    # Existing .gitignore with one of our entries already present
    (paths.root / ".gitignore").write_text("node_modules/\nralph/\n")

    result = setup_mod.initialize(paths)

    gi = (paths.root / ".gitignore").read_text()
    assert "node_modules/" in gi
    assert "ralph/" in gi
    assert ".ralphex/*" in gi
    assert "!.ralphex/config" in gi
    # ralph/ should appear only once
    assert gi.count("ralph/") == 1
    assert ".gitignore" in result.upserted
    assert ".ralphex/*" in result.upserted[".gitignore"]
    assert "ralph/" not in result.upserted[".gitignore"]


def test_initialize_plan_path_missing_raises(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    paths = ProjectPaths(root=tmp_path / "project")
    paths.root.mkdir()

    with pytest.raises(ValueError, match="plan file not found"):
        setup_mod.initialize(paths, plan_path=tmp_path / "nope.md")


def test_initialize_plan_path_directory_raises(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    paths = ProjectPaths(root=tmp_path / "project")
    paths.root.mkdir()
    plan_dir = tmp_path / "fake.md"
    plan_dir.mkdir()

    with pytest.raises(ValueError, match="not a file"):
        setup_mod.initialize(paths, plan_path=plan_dir)


def test_initialize_plan_path_wrong_extension_raises(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    paths = ProjectPaths(root=tmp_path / "project")
    paths.root.mkdir()
    bad_plan = tmp_path / "plan.txt"
    bad_plan.write_text("not markdown")

    with pytest.raises(ValueError, match="markdown file"):
        setup_mod.initialize(paths, plan_path=bad_plan)


def test_initialize_with_valid_plan_upserts_plans_dir(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    paths = ProjectPaths(root=tmp_path / "project")
    paths.root.mkdir()
    plans = tmp_path / "my-plans"
    plans.mkdir()
    plan_file = plans / "myplan.md"
    plan_file.write_text("# plan")

    setup_mod.initialize(paths, plan_path=plan_file)

    cfg = (paths.root / ".ralphex" / "config").read_text()
    assert f"plans_dir = {plans.resolve()}" in cfg


def test_initialize_without_plan_does_not_set_plans_dir(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    paths = ProjectPaths(root=tmp_path / "project")
    paths.root.mkdir()

    setup_mod.initialize(paths)

    cfg = (paths.root / ".ralphex" / "config").read_text()
    assert "plans_dir" not in cfg
