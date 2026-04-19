from pathlib import Path

from ralph_stack.cli import main


def test_status_no_state(tmp_project: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_project)
    rc = main(["status"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "no run in progress" in captured.out.lower()


def test_resume_blocks_on_stale_unverified(tmp_project: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_project)
    # Seed stale unverified rules
    lessons = tmp_project / "tasks" / "lessons.md"
    lessons.parent.mkdir()
    lessons.write_text("# Lessons\n\n## ⚠️ Unverified (2026-04-01)\n- stale draft\n")
    rc = main(["resume"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "unverified" in captured.err.lower()


def test_cli_init_fresh_directory(tmp_path, monkeypatch, capsys):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.chdir(tmp_path)

    from ralph_stack.cli import main
    rc = main(["init"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ralph/" in out
    assert "Ready" in out


def test_cli_init_with_valid_plan(tmp_path, monkeypatch, capsys):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.chdir(tmp_path)
    plan = tmp_path / "plan.md"
    plan.write_text("# plan")

    from ralph_stack.cli import main
    rc = main(["init", str(plan)])
    assert rc == 0
    cfg = (tmp_path / ".ralphex" / "config").read_text()
    assert "plans_dir = " in cfg


def test_cli_init_missing_plan_file(tmp_path, monkeypatch, capsys):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.chdir(tmp_path)

    from ralph_stack.cli import main
    rc = main(["init", str(tmp_path / "nope.md")])
    assert rc == 2
    err = capsys.readouterr().err
    assert "not found" in err


def test_debrief_no_morning_report(tmp_project: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_project)
    rc = main(["debrief"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "no completed run" in captured.err.lower()


def test_debrief_prints_complete_report(tmp_project: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_project)
    (tmp_project / "ralph" / "morning-report.md").write_text(
        "# Ralph Run — plan_demo — 2026-04-19\n"
        "\n"
        "## Status: ✅ COMPLETE\n"
        "\n"
        "## Progress\n"
        "- Plan checkboxes: 5/5 complete (100%)\n"
        "- Iterations: 3\n"
        "- Commits: 3 (branch: main)\n"
    )
    rc = main(["debrief"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "✅ COMPLETE" in captured.out
    assert "plan_demo" in captured.out


def test_cli_init_non_markdown_plan(tmp_path, monkeypatch, capsys):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "plan.txt"
    bad.write_text("x")

    from ralph_stack.cli import main
    rc = main(["init", str(bad)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "markdown" in err
