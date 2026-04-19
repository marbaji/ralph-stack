from pathlib import Path
from ralph_stack.transcript import Iteration
from ralph_stack.escalation import write_stuck_dump, _parse_draft_output


def test_write_stuck_dump(tmp_path: Path):
    iters = [
        Iteration(number=i, files_written=[f"f{i}.ts"], errors=[] if i < 10 else ["boom"])
        for i in range(1, 13)
    ]
    dump = tmp_path / "stuck-dump.md"
    write_stuck_dump(dump, iters, paused_at=12)
    content = dump.read_text()
    assert "Paused at iter 12" in content
    assert "iter-3" in content  # last 10 = iters 3..12
    assert "iter-12" in content
    assert "iter-2" not in content


def test_parse_draft_output():
    text = """SOURCE: iter 71
RULE: Always check down migrations alongside up.
CONTEXT: iter 68-72 kept breaking the down migration.
---
SOURCE: iter 58
RULE: Prefer invalidateQueries over manual refetch.
CONTEXT: iter 55-58 flapped on stale cache.
---
"""
    rules = _parse_draft_output(text)
    assert len(rules) == 2
    assert rules[0][0] == "iter 71"
    assert "down migrations" in rules[0][1]
    assert rules[1][0] == "iter 58"
