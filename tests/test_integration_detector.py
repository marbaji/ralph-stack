from pathlib import Path
from ralph_stack.state import StuckState
from ralph_stack.transcript import parse_iterations
from ralph_stack.detector import decide, update_state


def test_full_run_triggers_escalation_and_handback(fixtures_dir: Path):
    state = StuckState()
    decisions = []
    for it in parse_iterations(fixtures_dir / "transcript_full_run.jsonl"):
        d = decide(state, it, tests_now={})
        decisions.append((it.number, d.action, d.next_model))
        state = update_state(state, it, d, tests_now={})

    actions = [a for (_, a, _) in decisions]
    models = [m for (_, _, m) in decisions]
    assert "escalate" in actions
    assert "handback" in actions
    # Final state should be back on opus after handback
    assert models[-1] == "opus"
