from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class Iteration:
    number: int
    files_written: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    checkboxes_flipped: int = 0


def parse_iterations(path: Path) -> Iterator[Iteration]:
    current: Iteration | None = None
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            etype = event.get("type")
            if etype == "iteration_start":
                if current is not None:
                    yield current
                current = Iteration(number=event["iteration"])
            elif current is None:
                continue
            elif etype == "tool_use":
                tool = event.get("tool_name", "")
                if tool in ("Write", "Edit", "MultiEdit"):
                    fp = event.get("tool_input", {}).get("file_path")
                    if fp:
                        current.files_written.append(fp)
            elif etype == "tool_result":
                if event.get("is_error"):
                    err = event.get("error", "unknown error")
                    current.errors.append(err)
            elif etype == "iteration_end":
                current.checkboxes_flipped = event.get("checkboxes_flipped", 0)
                yield current
                current = None
    if current is not None:
        yield current
