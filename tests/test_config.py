from __future__ import annotations

from pathlib import Path

from ralph_stack import config


def test_wrapper_path_is_absolute():
    p = config.wrapper_path()
    assert p.is_absolute()


def test_wrapper_path_ends_with_wrapper_script():
    p = config.wrapper_path()
    assert p.name == "claude-ralph-wrapper.sh"
    assert p.parent.name == "scripts"


def test_wrapper_path_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p1 = config.wrapper_path()
    monkeypatch.chdir(tmp_path.parent)
    p2 = config.wrapper_path()
    assert p1 == p2


def test_wrapper_path_points_at_real_file():
    assert config.wrapper_path().exists()


def test_upsert_key_on_missing_file(tmp_path):
    p = tmp_path / "config"
    changed = config.upsert_key(p, "claude_command", "/foo/bar")
    assert changed is True
    assert p.read_text() == "claude_command = /foo/bar\n"


def test_upsert_key_on_empty_file(tmp_path):
    p = tmp_path / "config"
    p.write_text("")
    changed = config.upsert_key(p, "use_worktree", "true")
    assert changed is True
    assert p.read_text() == "use_worktree = true\n"


def test_upsert_key_appends_new_key(tmp_path):
    p = tmp_path / "config"
    p.write_text("existing = value\n")
    changed = config.upsert_key(p, "task_model", "opus")
    assert changed is True
    text = p.read_text()
    assert "existing = value" in text
    assert "task_model = opus" in text


def test_upsert_key_replaces_existing_value(tmp_path):
    p = tmp_path / "config"
    p.write_text("task_model = sonnet\nother = x\n")
    changed = config.upsert_key(p, "task_model", "opus")
    assert changed is True
    text = p.read_text()
    assert "task_model = opus" in text
    assert "task_model = sonnet" not in text
    assert "other = x" in text


def test_upsert_key_returns_false_when_value_matches(tmp_path):
    p = tmp_path / "config"
    p.write_text("task_model = opus\n")
    changed = config.upsert_key(p, "task_model", "opus")
    assert changed is False
    assert p.read_text() == "task_model = opus\n"


def test_upsert_key_preserves_comments_and_blank_lines(tmp_path):
    p = tmp_path / "config"
    p.write_text("# a comment\n\ntask_model = sonnet\n# another\n")
    config.upsert_key(p, "task_model", "opus")
    text = p.read_text()
    assert "# a comment" in text
    assert "# another" in text
    assert "task_model = opus" in text


def test_upsert_key_handles_crlf(tmp_path):
    p = tmp_path / "config"
    p.write_bytes(b"task_model = sonnet\r\nother = x\r\n")
    config.upsert_key(p, "task_model", "opus")
    text = p.read_text()
    assert "task_model = opus" in text
    assert "other = x" in text


def test_upsert_keys_reports_only_changed(tmp_path):
    p = tmp_path / "config"
    p.write_text("task_model = opus\n")
    changed = config.upsert_keys(p, {
        "task_model": "opus",       # unchanged
        "claude_command": "/x",      # new
        "use_worktree": "true",      # new
    })
    assert "task_model" not in changed
    assert "claude_command" in changed
    assert "use_worktree" in changed
    assert len(changed) == 2
