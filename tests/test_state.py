import json
from pathlib import Path
from ralph_stack.state import StuckState


def test_state_round_trip(tmp_path: Path):
    state = StuckState(
        current_iteration=47,
        current_model="opus",
        last_error_hash="a4f21b",
        error_streak=2,
        file_access_window=["src/foo.ts", "src/foo.ts", "src/bar.ts", "src/foo.ts"],
        iterations_since_checkbox=1,
        last_escalation_iter=31,
        escalation_cooldown_until=34,
        test_baseline={"test_a": "pass", "test_b": "pass"},
    )
    path = tmp_path / "stuck-state.json"
    state.save(path)
    loaded = StuckState.load(path)
    assert loaded == state


def test_state_default_when_missing(tmp_path: Path):
    path = tmp_path / "nonexistent.json"
    state = StuckState.load(path)
    assert state.current_iteration == 0
    assert state.current_model == "opus"
    assert state.file_access_window == []
    assert state.test_baseline == {}
