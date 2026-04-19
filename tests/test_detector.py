from ralph_stack.state import StuckState
from ralph_stack.transcript import Iteration
from ralph_stack.detector import decide, Decision


def _iter(n: int, **kw) -> Iteration:
    return Iteration(number=n, **kw)


def test_ok_when_progress_made():
    state = StuckState(current_iteration=5, current_model="opus")
    it = _iter(6, checkboxes_flipped=1)
    d = decide(state, it, tests_now={})
    assert d.action == "continue"
    assert d.next_model == "opus"


def test_file_thrash_escalates():
    state = StuckState(
        current_iteration=3,
        current_model="opus",
        file_access_window=["src/foo.ts", "src/foo.ts", "src/foo.ts"],
    )
    it = _iter(4, files_written=["src/foo.ts"])  # 4th write in 4-iter window
    d = decide(state, it, tests_now={})
    assert d.action == "escalate"
    assert d.next_model == "codex"
    assert "file_thrash" in d.reason


def test_error_loop_escalates():
    state = StuckState(
        current_iteration=3,
        current_model="opus",
        last_error_hash="abc",
        error_streak=2,
    )
    it = _iter(4, errors=["some error"])
    d = decide(state, it, tests_now={}, override_error_hash="abc")
    assert d.action == "escalate"
    assert "error_loop" in d.reason


def test_test_regression_escalates():
    state = StuckState(
        current_iteration=5,
        current_model="opus",
        test_baseline={"t_a": "pass", "t_b": "pass"},
    )
    it = _iter(6)
    d = decide(state, it, tests_now={"t_a": "fail", "t_b": "pass"})
    assert d.action == "escalate"
    assert "test_regression" in d.reason


def test_no_progress_escalates_at_threshold():
    state = StuckState(
        current_iteration=5,
        current_model="opus",
        iterations_since_checkbox=2,  # will become 3 after this iter
    )
    it = _iter(6, checkboxes_flipped=0)
    d = decide(state, it, tests_now={})
    assert d.action == "escalate"
    assert "no_progress" in d.reason


def test_cooldown_blocks_escalation():
    state = StuckState(
        current_iteration=32,
        current_model="opus",
        last_escalation_iter=31,
        escalation_cooldown_until=34,
        iterations_since_checkbox=2,
    )
    it = _iter(33, checkboxes_flipped=0)
    d = decide(state, it, tests_now={})
    # cooldown active AND stuck on opus → HUMAN_REQUIRED
    assert d.action == "human_required"


def test_codex_handback_on_checkbox():
    state = StuckState(
        current_iteration=48,
        current_model="codex",
        codex_takeover_iter=48,
    )
    it = _iter(49, checkboxes_flipped=1)
    d = decide(state, it, tests_now={})
    assert d.action == "handback"
    assert d.next_model == "opus"


def test_codex_handback_on_clean_iterations():
    state = StuckState(
        current_iteration=49,
        current_model="codex",
        codex_takeover_iter=48,
        codex_stuck_streak=0,
    )
    it = _iter(50, checkboxes_flipped=0)
    d = decide(state, it, tests_now={})
    assert d.action == "handback"


def test_codex_also_stuck_triggers_human_required():
    state = StuckState(
        current_iteration=49,
        current_model="codex",
        codex_takeover_iter=48,
        codex_stuck_streak=1,  # will become 2
    )
    it = _iter(50, checkboxes_flipped=0, errors=["still broken"])
    d = decide(state, it, tests_now={})
    assert d.action == "human_required"
    assert "codex_also_stuck" in d.reason
