from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProjectPaths:
    root: Path

    @property
    def ralph_dir(self) -> Path:
        return self.root / "ralph"

    @property
    def state_file(self) -> Path:
        return self.ralph_dir / "stuck-state.json"

    @property
    def model_override(self) -> Path:
        return self.ralph_dir / "next-iter-model.txt"

    @property
    def morning_report(self) -> Path:
        return self.ralph_dir / "morning-report.md"

    @property
    def stuck_dump(self) -> Path:
        return self.ralph_dir / "stuck-dump.md"

    @property
    def per_project_guardrails(self) -> Path:
        return self.root / "tasks" / "lessons.md"

    def ensure_dirs(self) -> None:
        self.ralph_dir.mkdir(parents=True, exist_ok=True)


def global_guardrails_path() -> Path:
    return Path.home() / ".ralph" / "guardrails.md"


def ensure_global_guardrails() -> None:
    p = global_guardrails_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text("# Ralph Global Guardrails\n\nAppend-only rules that apply across all projects.\n")
