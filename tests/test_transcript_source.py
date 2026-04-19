import json
from pathlib import Path

from ralph_stack.transcript_source import (
    ClaudeCodeStreamJsonSource,
    TailingTranscriptSource,
)


def test_tail_returns_only_new_iterations(tmp_path: Path):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("")
    src = TailingTranscriptSource(transcript)

    # Write iter 1
    transcript.write_text(
        '{"type": "iteration_start", "iteration": 1}\n'
        '{"type": "iteration_end", "iteration": 1, "checkboxes_flipped": 1}\n'
    )
    iters = src.read_new()
    assert len(iters) == 1
    assert iters[0].number == 1

    # Next call returns nothing
    assert src.read_new() == []

    # Append iter 2
    with transcript.open("a") as f:
        f.write('{"type": "iteration_start", "iteration": 2}\n')
        f.write('{"type": "iteration_end", "iteration": 2, "checkboxes_flipped": 0}\n')

    iters = src.read_new()
    assert len(iters) == 1
    assert iters[0].number == 2


def _write_stream_json(path: Path, *, file_path: str, error_text: str | None, checkbox_new_string: str | None) -> None:
    """Write a minimal Claude Code stream-json JSONL file.

    Each file represents ONE ralphex iteration (fresh Claude session).
    """
    content_blocks = [
        {
            "type": "tool_use",
            "id": "tu_1",
            "name": "Edit",
            "input": {
                "file_path": file_path,
                "old_string": "foo",
                "new_string": checkbox_new_string or "bar",
            },
        },
    ]
    events = [
        {
            "type": "assistant",
            "message": {"content": content_blocks},
        },
    ]
    if error_text is not None:
        events.append(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tu_1",
                            "is_error": True,
                            "content": error_text,
                        }
                    ]
                },
            }
        )
    # Also an assistant-embedded tool_result variant to exercise both code paths
    # (real Claude Code puts tool_result in user messages, but some formats put
    # them in assistant messages — our adapter scans assistants only, so we
    # keep this file's tool_result in a user event).
    with path.open("w") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
        # malformed line — should be skipped silently
        f.write("not-json\n")


def test_claude_stream_json_source_returns_one_iteration_per_file(tmp_path: Path):
    # Two "iteration" JSONL files under a project dir
    proj_dir = tmp_path / "-tmp-smoke"
    proj_dir.mkdir()

    file_a = proj_dir / "session-aaa.jsonl"
    _write_stream_json(
        file_a,
        file_path="/plan.md",
        error_text=None,
        checkbox_new_string="- [x] step one\n- [x] step two\n",
    )

    file_b = proj_dir / "session-bbb.jsonl"
    _write_stream_json(
        file_b,
        file_path="/src/code.py",
        error_text="boom: file not found",
        checkbox_new_string="no checkbox here",
    )

    # Stagger mtimes so ordering is deterministic
    import os
    os.utime(file_a, (1_000_000, 1_000_000))
    os.utime(file_b, (1_000_001, 1_000_001))

    src = ClaudeCodeStreamJsonSource(proj_dir)
    iters = src.read_new()
    assert len(iters) == 2

    first, second = iters
    assert first.number == 1
    assert "/plan.md" in first.files_written
    assert first.errors == []
    # Two `[x]` tokens added in Edit.new_string for a .md file
    assert first.checkboxes_flipped == 2

    assert second.number == 2
    assert "/src/code.py" in second.files_written
    assert any("boom" in e for e in second.errors)
    # Not a markdown plan edit → checkboxes_flipped stays 0
    assert second.checkboxes_flipped == 0

    # Second call: no new files
    assert src.read_new() == []

    # New file arrives → iteration 3
    file_c = proj_dir / "session-ccc.jsonl"
    _write_stream_json(file_c, file_path="/plan.md", error_text=None, checkbox_new_string="- [x] done")
    os.utime(file_c, (1_000_002, 1_000_002))

    iters = src.read_new()
    assert len(iters) == 1
    assert iters[0].number == 3
