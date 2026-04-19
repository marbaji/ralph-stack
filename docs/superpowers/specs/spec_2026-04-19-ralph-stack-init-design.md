# Ralph Stack `init` Subcommand Design

**Status:** Spec (not yet implemented)
**Date:** 2026-04-19
**Context:** First dogfood target for the ralph-stack autonomous coding loop (Phase 13 of `spec_2026-04-18-ralph-stack-design.md`). Small, bounded, low-stakes feature that gives ralph a clear checkbox plan to execute overnight.

---

## Goal

Add a `ralph-stack init [plan.md]` subcommand that prepares a project directory for a ralph run. Idempotent: safe to run multiple times; fills in missing pieces without destroying existing content.

This exists because today, `ralph-stack run` implicitly creates directories and writes `.ralphex/config` as a side effect of starting. Users have no pre-flight surface to review the setup before kicking off an overnight run. `init` provides that surface.

## Non-goals

- Authoring plan files (that's `/superpowers:writing-plans`)
- Installing dependencies or validating the ralphex binary (that's `install.sh`)
- Validating that a git repo exists (ralphex's `--worktree` handles that; not init's concern)
- Running ralphex or claude
- Any network calls

## Command surface

```
ralph-stack init [plan.md]
```

**Exit codes:**
- `0` — success (including "everything already present")
- `2` — validation failure (plan arg given but not a readable `.md` file, or filesystem error)

**Output format:** Compact per-path summary, then a next-step hint.

```
ralph-stack init

  created   ralph/
  created   tasks/lessons.md
  upserted  .ralphex/config (claude_command, use_worktree, task_model)
  created   .gitignore (+3 entries)
  ensured   ~/.ralph/guardrails.md

Ready. Next: caffeinate -dims ralph-stack run <plan.md>
```

When fully idempotent (nothing to do):

```
ralph-stack init

  skipped   ralph/                     (exists)
  skipped   tasks/lessons.md           (exists)
  skipped   .ralphex/config            (all keys present)
  skipped   .gitignore                 (all entries present)
  ensured   ~/.ralph/guardrails.md

Ready. Next: caffeinate -dims ralph-stack run <plan.md>
```

## File effects

All operations are idempotent.

| Path | If absent | If present |
|---|---|---|
| `ralph/` (dir) | Create | Skip |
| `tasks/lessons.md` | Create with header + two-tier convention reminder | Skip (file is append-only; never overwritten) |
| `.ralphex/config` | Create with seeded keys below | Upsert keys by name (`claude_command`, `use_worktree`, `task_model`, and `plans_dir` if plan arg given). Preserve other lines verbatim. |
| `.gitignore` | Create with 3 entries below | Merge: add `ralph/`, `.ralphex/*`, `!.ralphex/config` only if each is missing |
| `~/.ralph/guardrails.md` | Create via existing `ensure_global_guardrails()` | Skip |

**Seeded `.ralphex/config` keys:**

```
claude_command = <absolute path to scripts/claude-ralph-wrapper.sh>
use_worktree = true
task_model = opus
plans_dir = <dir of plan arg>    # only if plan arg given
```

The `claude_command` value must resolve to the wrapper script inside the ralph-stack package install, NOT inside the user's project directory. Current `runner._write_ralphex_config()` has a bug here: it uses `paths.root / "scripts" / "claude-ralph-wrapper.sh"`, which resolves to `<user_project>/scripts/...` — a path that won't exist in arbitrary user projects. Fixing this is in scope for the refactor below.

**Correct resolution** (used by both init and runner after the refactor):
```python
# config.py
WRAPPER_PATH = (Path(__file__).parent.parent.parent / "scripts" / "claude-ralph-wrapper.sh").resolve()
```

This points at `<ralph-stack install>/scripts/claude-ralph-wrapper.sh` regardless of the user's CWD. Works for pip editable installs because `__file__` always reflects the source location.

Rationale:
- `claude_command` and `use_worktree` are required for ralph-stack to work correctly — not preferences, requirements
- `task_model = opus` is the one product opinion we hold explicitly (per spec decision)
- `plans_dir` is useful only when a plan arg was passed
- `review_model` is intentionally NOT pinned — ralphex's default (`gpt-5.4`) is fine, and pinning prematurely blocks us from picking up upstream improvements

**Seeded `.gitignore` entries:**

```
ralph/
.ralphex/*
!.ralphex/config
```

Rationale: `ralph/` is entirely ralph-stack runtime state. `.ralphex/*` with negation for `config` is a future-proof allowlist — we don't know every runtime artifact ralphex will write (caches, sessions, progress logs), and an allowlist catches all of them while preserving the one file (`config`) that belongs in version control.

**Seeded `tasks/lessons.md`:**

```markdown
# Lessons

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
```

## Module layout

```
src/ralph_stack/
  config.py       NEW  — shared .ralphex/config upsert helpers
                         extracted from runner._upsert_config_key
  setup.py        NEW  — initialize(paths, plan_path=None) -> InitResult
  cli.py          MOD  — add cmd_init(); add "init" subparser
  runner.py       MOD  — replace _upsert_config_key with config.upsert_key,
                         replace hardcoded wrapper path with config.wrapper_path()

tests/
  test_config.py  NEW  — upsert helper edge cases
  test_setup.py   NEW  — init behavior
  test_cli.py     MOD  — cmd_init dispatch coverage
```

## Interfaces

### `config.wrapper_path() -> Path`

Returns the absolute path to `scripts/claude-ralph-wrapper.sh` inside the installed ralph-stack package. Computed once from `Path(__file__)` so it's install-location-agnostic. Both init and runner call this to ensure they write identical `claude_command` values.

### `config.upsert_key(path: Path, key: str, value: str) -> bool`

Upsert a `key = value` line in a `.ralphex/config`-style file. Returns `True` if the file was changed (key added or value changed), `False` if the key already had that value. Creates the file if absent. Preserves comments (`# ...` lines) and blank lines verbatim. Handles CRLF line endings.

### `config.upsert_keys(path: Path, pairs: dict[str, str]) -> list[str]`

Convenience wrapper. Returns the list of keys that were actually changed (for CLI reporting).

### `setup.initialize(paths: ProjectPaths, plan_path: Path | None = None) -> InitResult`

Orchestrates all file effects. Raises `ValueError` if `plan_path` is given but invalid (CLI translates to exit 2).

```python
@dataclass
class InitResult:
    created: list[str]                 # human-readable paths, e.g. ["ralph/", "tasks/lessons.md"]
    skipped: list[str]                 # paths that already existed and weren't touched
    upserted: dict[str, list[str]]     # path -> keys that actually changed, e.g. {".ralphex/config": ["claude_command"]}
    ensured: list[str]                 # paths ensured via external helpers (e.g., ~/.ralph/guardrails.md)
    next_step: str                     # hint printed under the summary
```

### `cli.cmd_init(plan: str | None) -> int`

Thin CLI wrapper: validates plan arg, calls `setup.initialize()`, renders `InitResult`, returns exit code.

## Error handling

| Scenario | Behavior |
|---|---|
| Plan arg given, file doesn't exist | Exit 2: `error: plan file not found: <path>` (stderr) |
| Plan arg given, not `.md` extension | Exit 2: `error: plan path must be a markdown file: <path>` (stderr) |
| `~/.ralph/` unwritable | Exit 2: surface the `OSError` message |
| Not in a git repo | Proceed normally. `.gitignore` creation/merge is independent of git state |
| `.ralphex/config` exists but malformed | Upsert still works (scans line-by-line). Unparseable lines preserved verbatim |
| Any file write fails mid-init | Print what succeeded so far, then the error, exit 2. No rollback — partial state is safe because re-running `init` finishes the job |

## Testing

Unit tests cover each module; one integration test at the CLI level.

**`test_config.py`:**
- `wrapper_path()` returns an absolute path ending in `scripts/claude-ralph-wrapper.sh`
- `wrapper_path()` is stable across calls and independent of CWD
- upsert on missing file (creates file with single key)
- upsert on empty file
- upsert adding new key (appends)
- upsert replacing existing value (in-place)
- upsert returning False when value already matches
- upsert preserving comment lines and blank lines
- upsert handling CRLF line endings
- `upsert_keys` multi-key call reports only changed keys

**`test_setup.py`:**
- fresh directory: all files created, InitResult populated correctly
- fully-initialized directory: everything skipped
- mixed state: some files exist, some don't — correct classification
- plan arg: non-existent file raises ValueError
- plan arg: non-`.md` extension raises ValueError
- plan arg valid: `plans_dir` upserted into config
- no plan arg: `plans_dir` not touched
- `tasks/lessons.md` with existing content is preserved byte-for-byte
- `.gitignore` merge: existing entries preserved, missing ones added
- `.gitignore` already has all three entries: no changes

**`test_cli.py` (additive):**
- `init` with no args: exit 0, output contains summary sections
- `init` with valid plan arg: exit 0, `plans_dir` line in config
- `init` with missing plan file: exit 2, error on stderr
- `init` with non-`.md` arg: exit 2, error on stderr

No integration with real ralphex — `init` is pure filesystem bootstrap, no subprocess calls.

**Target:** +24 tests (10 config + 10 setup + 4 cli), bringing suite from 40 → ~64.

## Success criteria

1. `ralph-stack init` on a fresh directory produces a state where `ralph-stack run <plan.md>` works without additional setup
2. `ralph-stack init` is safe to re-run any number of times
3. `ralph-stack init` never destroys user-authored content (especially `tasks/lessons.md`)
4. Runner and init write the same `.ralphex/config` format (shared helper prevents drift)
5. Test suite grows from 40 to ~51, all green

## Open questions

None. All architectural decisions captured above.

## References

- `spec_2026-04-18-ralph-stack-design.md` — parent spec
- `SPIKE-NOTES.md` — ralphex integration details and locked-in decisions
