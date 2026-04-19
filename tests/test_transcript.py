from pathlib import Path
from ralph_stack.transcript import parse_iterations, Iteration


def test_parse_two_iterations(fixtures_dir: Path):
    iters = list(parse_iterations(fixtures_dir / "transcript_two_iterations.jsonl"))
    assert len(iters) == 2
    assert iters[0].number == 1
    assert iters[0].files_written == ["src/foo.ts"]
    assert iters[0].errors == []
    assert iters[0].checkboxes_flipped == 1
    assert iters[1].number == 2
    assert iters[1].files_written == ["src/bar.ts"]
    assert iters[1].errors == ["TypeError: x is not defined"]
    assert iters[1].checkboxes_flipped == 0
