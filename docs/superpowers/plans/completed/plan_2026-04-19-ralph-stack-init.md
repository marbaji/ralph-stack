# Ralph Stack `init` Subcommand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `ralph-stack init [plan.md]` subcommand that idempotently bootstraps a project directory for an overnight ralph run — creating `ralph/`, `tasks/lessons.md`, `.ralphex/config`, and `.gitignore`, while fixing the runner's wrapper-path resolution bug along the way.

**Architecture:** Extract config-file upsert helpers and wrapper-path resolution from `runner.py` into a new `config.py` module. Add a new `setup.py` module that orchestrates all file effects via an `initialize()` function returning an `InitResult` dataclass for CLI reporting. Wire a new `init` subparser into `cli.py`. Refactor `runner._write_ralphex_config` to use the shared helpers, which also fixes the wrapper-path bug (where `paths.root / "scripts/..."` resolves to the user's project CWD instead of the ralph-stack install dir).

**Tech Stack:** Python 3.11+, pytest, stdlib only (pathlib, dataclasses, argparse).

**Package root:** `/Users/mohannadarbaji/.claude/plugins/marketplaces/marbaji-claude-ralph-stack-wt/ralph-stack/` — all paths below are relative to this root.

**Spec:** `docs/superpowers/specs/spec_2026-04-19-ralph-stack-init-design.md`

---

## File Structure

**New files:**
- `src/ralph_stack/config.py` — wrapper-path resolver + `.ralphex/config` upsert helpers
- `src/ralph_stack/setup.py` — `initialize()` + `InitResult` dataclass
- `tests/test_config.py` — 10 tests for config helpers
- `tests/test_setup.py` — 10 tests for initialize behavior

**Modified files:**
- `src/ralph_stack/cli.py` — add `cmd_init()` + `init` subparser
- `src/ralph_stack/runner.py` — replace `_upsert_config_key` with shared `config.upsert_key`; replace hardcoded wrapper path with `config.wrapper_path()`
- `tests/test_cli.py` — 4 new tests for `init` dispatch
- `tests/test_runner.py` — update any tests that referenced `_upsert_config_key` directly (if any)

---

## Task 1: `config.wrapper_path()` — install-location-agnostic wrapper resolution

**Files:**
- Create: `src/ralph_stack/config.py`
- Test: `tests/test_config.py`

- [x] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
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
    # The wrapper script ships with the package.
    assert config.wrapper_path().exists()
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/mohannadarbaji/.claude/plugins/marketplaces/marbaji-claude-ralph-stack-wt/ralph-stack && .venv/bin/pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ralph_stack.config'`

- [x] **Step 3: Write minimal implementation**

Create `src/ralph_stack/config.py`:

```python
from __future__ import annotations

from pathlib import Path


def wrapper_path() -> Path:
    """Return the absolute path to scripts/claude-ralph-wrapper.sh inside the
    installed ralph-stack package.

    Computed from __file__ so it works regardless of the user's CWD or whether
    ralph-stack was installed via pip editable or standard install.
    """
    return (Path(__file__).parent.parent.parent / "scripts" / "claude-ralph-wrapper.sh").resolve()
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS (4 tests)

- [x] **Step 5: Commit**

```bash
git add src/ralph_stack/config.py tests/test_config.py
git commit -m "feat(config): install-location-agnostic wrapper_path resolver"
```

---

## Task 2: `config.upsert_key()` — extracted and strengthened upsert helper

**Files:**
- Modify: `src/ralph_stack/config.py`
- Test: `tests/test_config.py`

- [x] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
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
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL with `AttributeError: module 'ralph_stack.config' has no attribute 'upsert_key'`

- [x] **Step 3: Write minimal implementation**

Append to `src/ralph_stack/config.py`:

```python
def upsert_key(path: Path, key: str, value: str) -> bool:
    """Upsert a `key = value` line in a `.ralphex/config`-style file.

    Returns True if the file was changed (key added or value changed), False if
    the key already had that value. Creates the file if absent. Preserves
    comments (# ...) and blank lines verbatim. Handles CRLF line endings.
    """
    existing = path.read_text() if path.exists() else ""
    new_line = f"{key} = {value}"
    lines = existing.splitlines() if existing else []
    out: list[str] = []
    found = False
    changed = False
    for line in lines:
        stripped = line.lstrip()
        if not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k == key:
                found = True
                if line.rstrip("\r") == new_line:
                    out.append(line)
                else:
                    out.append(new_line)
                    changed = True
                continue
        out.append(line)
    if not found:
        if out and out[-1].strip() != "":
            out.append("")
        out.append(new_line)
        changed = True
    if not changed:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n")
    return True
```

- [x] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS (11 tests)

- [x] **Step 5: Commit**

```bash
git add src/ralph_stack/config.py tests/test_config.py
git commit -m "feat(config): upsert_key helper preserving comments and CRLF"
```

---

## Task 3: `config.upsert_keys()` — multi-key convenience wrapper

**Files:**
- Modify: `src/ralph_stack/config.py`
- Test: `tests/test_config.py`

- [x] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
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
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py::test_upsert_keys_reports_only_changed -v`
Expected: FAIL with `AttributeError: module 'ralph_stack.config' has no attribute 'upsert_keys'`

- [x] **Step 3: Write minimal implementation**

Append to `src/ralph_stack/config.py`:

```python
def upsert_keys(path: Path, pairs: dict[str, str]) -> list[str]:
    """Upsert multiple key/value pairs. Returns list of keys that changed."""
    changed: list[str] = []
    for key, value in pairs.items():
        if upsert_key(path, key, value):
            changed.append(key)
    return changed
```

- [x] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS (12 tests)

- [x] **Step 5: Commit**

```bash
git add src/ralph_stack/config.py tests/test_config.py
git commit -m "feat(config): upsert_keys multi-key wrapper"
```

---

## Task 4: Refactor `runner.py` to use shared helpers (fixes wrapper-path bug)

**Files:**
- Modify: `src/ralph_stack/runner.py:38-64` (delete `_upsert_config_key`)
- Modify: `src/ralph_stack/runner.py:107-122` (rewrite `_write_ralphex_config`)
- Test: existing `tests/test_runner.py` must still pass

- [x] **Step 1: Read existing runner test coverage**

Run: `.venv/bin/pytest tests/test_runner.py -v`
Expected: All existing runner tests PASS. Note the count for comparison after refactor.

- [x] **Step 2: Delete the old `_upsert_config_key` function**

In `src/ralph_stack/runner.py`, remove lines 38-64 (the entire `_upsert_config_key` function and its docstring).

- [x] **Step 3: Rewrite `_write_ralphex_config` to use `config` module**

In `src/ralph_stack/runner.py`, replace the existing `_write_ralphex_config` method body (lines 107-122) with:

```python
    def _write_ralphex_config(self) -> None:
        """Upsert `claude_command = <wrapper>` into .ralphex/config.

        Preserves any pre-existing config content. Uses config.wrapper_path()
        so the wrapper resolves to the ralph-stack install dir regardless of
        the user's CWD.
        """
        from ralph_stack import config
        config_path = self.paths.root / ".ralphex" / "config"
        config.upsert_key(config_path, "claude_command", str(config.wrapper_path()))
```

- [x] **Step 4: Run the full test suite to confirm no regressions**

Run: `.venv/bin/pytest tests/ -v`
Expected: PASS (all existing tests still green; count = previous runner tests + 12 config tests)

- [x] **Step 5: Commit**

```bash
git add src/ralph_stack/runner.py
git commit -m "refactor(runner): use config.wrapper_path and config.upsert_key

Fixes wrapper-path bug: previously resolved scripts/claude-ralph-wrapper.sh
relative to the user's project CWD. Now resolves to the ralph-stack install
dir via Path(__file__) navigation."
```

---

## Task 5: `setup.InitResult` dataclass

**Files:**
- Create: `src/ralph_stack/setup.py`
- Test: `tests/test_setup.py`

- [x] **Step 1: Write the failing test**

Create `tests/test_setup.py`:

```python
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
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_setup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ralph_stack.setup'`

- [x] **Step 3: Write minimal implementation**

Create `src/ralph_stack/setup.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InitResult:
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    upserted: dict[str, list[str]] = field(default_factory=dict)
    ensured: list[str] = field(default_factory=list)
    next_step: str = ""
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_setup.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/ralph_stack/setup.py tests/test_setup.py
git commit -m "feat(setup): InitResult dataclass"
```

---

## Task 6: `setup.initialize()` — fresh directory behavior

**Files:**
- Modify: `src/ralph_stack/setup.py`
- Test: `tests/test_setup.py`

- [x] **Step 1: Write the failing test**

Append to `tests/test_setup.py`:

```python
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
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_setup.py::test_initialize_fresh_directory -v`
Expected: FAIL with `AttributeError: module 'ralph_stack.setup' has no attribute 'initialize'`

- [x] **Step 3: Write minimal implementation**

Append to `src/ralph_stack/setup.py`:

```python
from pathlib import Path

from ralph_stack import config
from ralph_stack.paths import (
    ProjectPaths,
    ensure_global_guardrails,
)


LESSONS_TEMPLATE = """# Lessons

<!--
This file holds rules specific to this project. Ralph pre-prepends it
to every iteration's prompt so the agent sees it as live context.

Two-tier system:
- This file: project-specific rules (e.g., "use pnpm not npm in this repo")
- ~/.ralph/guardrails.md: universal rules that apply to every project

When ralph gets stuck overnight, it drafts proposed rules here as:

    ## ⚠️ Unverified (YYYY-MM-DD)
    - rule text
    - rule text

Unverified drafts block `ralph-stack resume` after 24 hours. Promote
them (move into the main list and delete the ⚠️ block) or delete the
⚠️ block outright before resuming. For rules that generalize across
projects, copy them into ~/.ralph/guardrails.md instead.
-->
"""

GITIGNORE_ENTRIES = ["ralph/", ".ralphex/*", "!.ralphex/config"]


def initialize(paths: ProjectPaths, plan_path: Path | None = None) -> InitResult:
    """Orchestrate idempotent bootstrap of a ralph-stack project directory."""
    if plan_path is not None:
        if not plan_path.exists():
            raise ValueError(f"plan file not found: {plan_path}")
        if plan_path.suffix != ".md":
            raise ValueError(f"plan path must be a markdown file: {plan_path}")

    result = InitResult(next_step="Ready. Next: caffeinate -dims ralph-stack run <plan.md>")

    # ralph/ directory
    ralph_dir = paths.root / "ralph"
    if ralph_dir.exists():
        result.skipped.append("ralph/")
    else:
        ralph_dir.mkdir(parents=True)
        result.created.append("ralph/")

    # tasks/lessons.md
    lessons = paths.per_project_guardrails
    if lessons.exists():
        result.skipped.append("tasks/lessons.md")
    else:
        lessons.parent.mkdir(parents=True, exist_ok=True)
        lessons.write_text(LESSONS_TEMPLATE)
        result.created.append("tasks/lessons.md")

    # .ralphex/config
    cfg_path = paths.root / ".ralphex" / "config"
    cfg_pairs = {
        "claude_command": str(config.wrapper_path()),
        "use_worktree": "true",
        "task_model": "opus",
    }
    if plan_path is not None:
        cfg_pairs["plans_dir"] = str(plan_path.parent.resolve())
    changed_keys = config.upsert_keys(cfg_path, cfg_pairs)
    if changed_keys:
        result.upserted[".ralphex/config"] = changed_keys
    else:
        result.skipped.append(".ralphex/config")

    # .gitignore
    gi_path = paths.root / ".gitignore"
    existing_gi = gi_path.read_text() if gi_path.exists() else ""
    existing_lines = [l.strip() for l in existing_gi.splitlines()]
    to_add = [e for e in GITIGNORE_ENTRIES if e not in existing_lines]
    if to_add:
        new_gi = existing_gi
        if new_gi and not new_gi.endswith("\n"):
            new_gi += "\n"
        new_gi += "\n".join(to_add) + "\n"
        gi_path.write_text(new_gi)
        if existing_gi:
            result.upserted[".gitignore"] = to_add
        else:
            result.created.append(".gitignore")
    else:
        result.skipped.append(".gitignore")

    # Global guardrails
    ensure_global_guardrails()
    result.ensured.append("~/.ralph/guardrails.md")

    return result
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_setup.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/ralph_stack/setup.py tests/test_setup.py
git commit -m "feat(setup): initialize fresh directory with seeded files"
```

---

## Task 7: `setup.initialize()` — idempotency on fully-initialized directory

**Files:**
- Test: `tests/test_setup.py`

- [x] **Step 1: Write the failing test**

Append to `tests/test_setup.py`:

```python
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
```

- [x] **Step 2: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_setup.py -v`
Expected: PASS (no code changes needed; the existing `initialize` should already handle these cases)

If any test fails, debug the existing `initialize()` implementation before moving on.

- [x] **Step 3: Commit**

```bash
git add tests/test_setup.py
git commit -m "test(setup): idempotency, lessons preservation, gitignore merge"
```

---

## Task 8: `setup.initialize()` — plan_path validation

**Files:**
- Test: `tests/test_setup.py`

- [x] **Step 1: Write the failing test**

Append to `tests/test_setup.py`:

```python
def test_initialize_plan_path_missing_raises(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    paths = ProjectPaths(root=tmp_path / "project")
    paths.root.mkdir()

    with pytest.raises(ValueError, match="plan file not found"):
        setup_mod.initialize(paths, plan_path=tmp_path / "nope.md")


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
```

- [x] **Step 2: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_setup.py -v`
Expected: PASS (validation logic was added in Task 6; these are coverage tests)

- [x] **Step 3: Commit**

```bash
git add tests/test_setup.py
git commit -m "test(setup): plan_path validation and plans_dir upsert"
```

---

## Task 9: `cli.cmd_init()` and `init` subparser

**Files:**
- Modify: `src/ralph_stack/cli.py`
- Test: `tests/test_cli.py`

- [x] **Step 1: Write the failing tests**

Append to `tests/test_cli.py` (or create if working from scratch — check existing file first):

```python
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
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL — argparse complains about unknown `init` subcommand.

- [x] **Step 3: Add `cmd_init` function and `init` subparser**

In `src/ralph_stack/cli.py`, add the following function after `cmd_stop`:

```python
def cmd_init(plan: str | None) -> int:
    from ralph_stack import setup as setup_mod
    paths = _project_paths()
    plan_path = Path(plan) if plan else None
    try:
        result = setup_mod.initialize(paths, plan_path=plan_path)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            print(f"error: plan file {msg}", file=sys.stderr)
        else:
            print(f"error: {msg}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print("ralph-stack init\n")
    for path in result.created:
        print(f"  created   {path}")
    for path, keys in result.upserted.items():
        keys_str = ", ".join(keys)
        print(f"  upserted  {path} ({keys_str})")
    for path in result.skipped:
        print(f"  skipped   {path}")
    for path in result.ensured:
        print(f"  ensured   {path}")
    print()
    print(result.next_step)
    return 0
```

In the same file, modify the `main()` function — add an `init` subparser and dispatch. Replace the existing subparser setup (lines ~88-106) with:

```python
    p_run = sub.add_parser("run")
    p_run.add_argument("plan")

    p_init = sub.add_parser("init")
    p_init.add_argument("plan", nargs="?", default=None)

    sub.add_parser("resume")
    sub.add_parser("status")
    sub.add_parser("report")
    sub.add_parser("stop")

    args = parser.parse_args(argv)
    if args.cmd == "run":
        return cmd_run(args.plan)
    if args.cmd == "init":
        return cmd_init(args.plan)
    if args.cmd == "resume":
        return cmd_resume()
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "report":
        return cmd_report()
    if args.cmd == "stop":
        return cmd_stop()
    return 1
```

- [x] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS (4 new tests + existing tests still green)

- [x] **Step 5: Commit**

```bash
git add src/ralph_stack/cli.py tests/test_cli.py
git commit -m "feat(cli): add init subcommand with plan arg validation"
```

---

## Task 10: Final full-suite verification

**Files:**
- No new files

- [x] **Step 1: Run the full test suite**

Run: `.venv/bin/pytest tests/ -v --tb=short`
Expected: PASS — total count should be ~64 (previous ~40 + 12 config + 10 setup + 4 cli, minus any runner tests that were made redundant by the refactor).

- [x] **Step 2: Smoke test the CLI on a fresh temp directory**

```bash
TMPDIR=$(mktemp -d)
cd "$TMPDIR"
ralph-stack init
ls -la
cat .ralphex/config
cat .gitignore
cat tasks/lessons.md | head -20
```

Expected:
- `ralph/`, `tasks/`, `.ralphex/`, `.gitignore` all present
- `.ralphex/config` contains `claude_command`, `use_worktree = true`, `task_model = opus`
- `claude_command` points to the wrapper script inside the ralph-stack install (not inside `$TMPDIR/scripts/...`)
- `.gitignore` contains `ralph/`, `.ralphex/*`, `!.ralphex/config`
- `tasks/lessons.md` has the two-tier documentation header

- [x] **Step 3: Smoke test idempotency**

```bash
ralph-stack init
```

Expected: output shows all paths as `skipped` or `ensured`, no `created` or `upserted` entries.

- [x] **Step 4: Smoke test with a plan arg**

```bash
echo "# test plan" > /tmp/test-plan.md
ralph-stack init /tmp/test-plan.md
grep plans_dir .ralphex/config
```

Expected: `plans_dir = /tmp` line present.

- [x] **Step 5: Smoke test error paths**

```bash
ralph-stack init /nonexistent.md
echo "exit: $?"
ralph-stack init /tmp/not-markdown.txt
echo "exit: $?"
```

Expected: both exit 2 with appropriate stderr messages.

- [x] **Step 6: Commit any final cleanup (if needed)**

If the smoke tests revealed any polish items, fix them and commit. Otherwise skip.

```bash
git status
# If no changes, skip this step
```

---

## Success Criteria

1. `.venv/bin/pytest tests/` reports ~64 passing tests, 0 failures
2. `ralph-stack init` on a fresh directory creates all 4 local paths + ensures `~/.ralph/guardrails.md`
3. Re-running `ralph-stack init` on the same directory makes zero changes (all paths `skipped`)
4. `.ralphex/config` `claude_command` points to the ralph-stack install's wrapper, not the user's CWD
5. Existing `ralph-stack run <plan>` still works end-to-end (no regressions from the runner refactor)
6. Plan-arg validation: exit 2 on missing or non-`.md` paths with clear stderr messages

---

## Execution Notes

**All commands assume CWD:** `/Users/mohannadarbaji/.claude/plugins/marketplaces/marbaji-claude-ralph-stack-wt/ralph-stack/`

**Venv pytest:** Always use `.venv/bin/pytest` (not bare `pytest`) so tests run against the pip-editable install.

**Task ordering matters:** Tasks 1-3 must complete before Task 4 (runner refactor depends on `config` module). Tasks 5-8 must complete before Task 9 (CLI depends on `setup.initialize`). Task 10 is the final gate.
