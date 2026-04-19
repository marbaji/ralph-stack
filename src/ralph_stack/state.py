from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class StuckState:
    current_iteration: int = 0
    current_model: str = "opus"
    last_error_hash: str = ""
    error_streak: int = 0
    file_access_window: list[str] = field(default_factory=list)
    iterations_since_checkbox: int = 0
    last_escalation_iter: int = -1
    escalation_cooldown_until: int = -1
    test_baseline: dict[str, str] = field(default_factory=dict)
    codex_takeover_iter: int = -1
    codex_stuck_streak: int = 0

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path) -> "StuckState":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        return cls(**data)
