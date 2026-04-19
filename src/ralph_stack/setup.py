from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ralph_stack import config
from ralph_stack.paths import ProjectPaths, ensure_global_guardrails


@dataclass
class InitResult:
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    upserted: dict[str, list[str]] = field(default_factory=dict)
    ensured: list[str] = field(default_factory=list)
    next_step: str = ""


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
        if not plan_path.is_file():
            raise ValueError(f"plan path is not a file: {plan_path}")
        if plan_path.suffix != ".md":
            raise ValueError(f"plan path must be a markdown file: {plan_path}")

    result = InitResult(next_step="Ready. Next: caffeinate -dims ralph-stack run <plan.md>")

    ralph_dir = paths.root / "ralph"
    if ralph_dir.exists():
        if not ralph_dir.is_dir():
            raise ValueError(f"ralph/ exists but is not a directory: {ralph_dir}")
        result.skipped.append("ralph/")
    else:
        ralph_dir.mkdir(parents=True)
        result.created.append("ralph/")

    lessons = paths.per_project_guardrails
    if lessons.exists():
        if not lessons.is_file():
            raise ValueError(f"tasks/lessons.md exists but is not a regular file: {lessons}")
        result.skipped.append("tasks/lessons.md")
    else:
        lessons.parent.mkdir(parents=True, exist_ok=True)
        lessons.write_text(LESSONS_TEMPLATE)
        result.created.append("tasks/lessons.md")

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

    ensure_global_guardrails()
    result.ensured.append("~/.ralph/guardrails.md")

    return result
