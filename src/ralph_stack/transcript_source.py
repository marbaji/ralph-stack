from __future__ import annotations

import json
from pathlib import Path

from ralph_stack.transcript import Iteration, parse_iterations


class TailingTranscriptSource:
    """Stateful: returns only iterations seen since last call.

    Consumes the synthetic schema parsed by ``parse_iterations`` (explicit
    ``iteration_start``/``iteration_end`` events). Primarily used by unit tests
    and the dry-run fixture; production paths use
    :class:`ClaudeCodeStreamJsonSource` instead.
    """

    def __init__(self, path: Path):
        self.path = path
        self._last_iter_number = 0

    def read_new(self) -> list[Iteration]:
        if not self.path.exists():
            return []
        fresh: list[Iteration] = []
        for it in parse_iterations(self.path):
            if it.number > self._last_iter_number:
                fresh.append(it)
        if fresh:
            self._last_iter_number = fresh[-1].number
        return fresh


# Tool names whose invocations count as "files_written".
_WRITE_TOOLS = {"Write", "Edit", "MultiEdit"}


def _iter_assistant_content_blocks(path: Path):
    """Yield each ``content`` block from ``assistant`` messages in a stream-json JSONL.

    Malformed JSON lines and non-assistant events are silently skipped.
    """
    try:
        f = path.open()
    except OSError:
        return
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "assistant":
                continue
            message = event.get("message") or {}
            for block in message.get("content") or []:
                yield block


def _iter_user_content_blocks(path: Path):
    """Yield each ``content`` block from ``user`` messages (where tool_result lives)."""
    try:
        f = path.open()
    except OSError:
        return
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "user":
                continue
            message = event.get("message") or {}
            # user.message.content may be a string or a list of blocks
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    yield block


def _extract_iteration_from_stream_json(path: Path, number: int) -> Iteration:
    """Parse a single Claude Code stream-json JSONL file into one Iteration.

    Heuristics:
      * files_written — input.file_path of any Write/Edit/MultiEdit tool_use
      * errors — result text of any tool_result block with is_error True
      * checkboxes_flipped — count of literal "[x]" substrings appearing in
        input.new_string of Edit/MultiEdit calls that target a .md plan file.
        This is a known approximation: it does not diff against old_string,
        so a new_string that simply preserves existing checkboxes will be
        over-counted. Acceptable because the detector only uses it as a
        progress signal; false positives delay stuck-detection slightly.
    """
    files_written: list[str] = []
    errors: list[str] = []
    checkboxes_flipped = 0

    for block in _iter_assistant_content_blocks(path):
        btype = block.get("type")
        if btype == "tool_use":
            tool_name = block.get("name", "")
            tool_input = block.get("input") or {}
            if tool_name in _WRITE_TOOLS:
                fp = tool_input.get("file_path")
                if fp:
                    files_written.append(fp)
                # Count [x] tokens in new_string, scoped to markdown targets.
                if tool_name in {"Edit", "MultiEdit"} and isinstance(fp, str) and fp.endswith(".md"):
                    if tool_name == "Edit":
                        ns = tool_input.get("new_string", "") or ""
                        if isinstance(ns, str):
                            checkboxes_flipped += ns.count("[x]")
                    else:  # MultiEdit: edits is a list of {old_string,new_string}
                        for edit in tool_input.get("edits") or []:
                            ns = edit.get("new_string", "") or ""
                            if isinstance(ns, str):
                                checkboxes_flipped += ns.count("[x]")
        elif btype == "tool_result":
            # Some formats nest tool_result in assistant messages; handle both.
            if block.get("is_error"):
                text = _stringify_tool_result(block.get("content"))
                if text:
                    errors.append(text)

    for block in _iter_user_content_blocks(path):
        if block.get("type") == "tool_result" and block.get("is_error"):
            text = _stringify_tool_result(block.get("content"))
            if text:
                errors.append(text)

    return Iteration(
        number=number,
        files_written=files_written,
        errors=errors,
        checkboxes_flipped=checkboxes_flipped,
    )


def _stringify_tool_result(content) -> str:
    """Normalize a tool_result content to a string message."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                t = b.get("text") or b.get("content") or ""
                if isinstance(t, str):
                    parts.append(t)
            elif isinstance(b, str):
                parts.append(b)
        return " ".join(p for p in parts if p)
    return str(content)


class ClaudeCodeStreamJsonSource:
    """Adapter for ralphex's real transcript layout.

    Ralphex spawns a fresh Claude Code session per iteration, so each JSONL
    file under ``~/.claude/projects/<hashed-cwd>/`` IS one iteration. On each
    ``read_new()`` call we glob the directory, sort by mtime, and emit an
    :class:`Iteration` for any file we haven't consumed yet. The iteration
    ``number`` is a monotonic counter maintained on the instance (not derived
    from file contents).
    """

    def __init__(self, directory: Path):
        self.directory = directory
        self._seen: set[Path] = set()
        self._counter = 0

    def read_new(self) -> list[Iteration]:
        if not self.directory.exists():
            return []
        files = sorted(self.directory.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        out: list[Iteration] = []
        for fp in files:
            if fp in self._seen:
                continue
            self._seen.add(fp)
            self._counter += 1
            out.append(_extract_iteration_from_stream_json(fp, self._counter))
        return out
