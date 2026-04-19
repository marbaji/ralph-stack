from pathlib import Path
from ralph_stack.runner import compute_branch_name


def test_branch_name_from_plan():
    assert compute_branch_name(Path("docs/plans/refactor-renewal-v3.md"), "2026-04-18") \
        == "ralph/refactor-renewal-v3-2026-04-18"


def test_branch_name_strips_extension():
    assert compute_branch_name(Path("my-plan.md"), "2026-04-19") \
        == "ralph/my-plan-2026-04-19"


from ralph_stack.transcript import Iteration
from ralph_stack.runner import RalphexRunner
from ralph_stack.paths import ProjectPaths


def test_tick_escalates_and_writes_override(tmp_project: Path):
    paths = ProjectPaths(root=tmp_project)
    paths.ensure_dirs()

    # Simulate 4 iterations that thrash the same file
    queue = [
        [Iteration(number=1, files_written=["src/foo.ts"])],
        [Iteration(number=2, files_written=["src/foo.ts"])],
        [Iteration(number=3, files_written=["src/foo.ts"])],
        [Iteration(number=4, files_written=["src/foo.ts"])],
    ]

    def source():
        return queue.pop(0) if queue else []

    def on_hr(state, iters):
        pass

    r = RalphexRunner(paths, Path("plan.md"), source, on_hr)
    # Can't actually start ralphex in test, so skip start() and just tick.

    for _ in range(4):
        r.tick(tests_now={})

    # After 4 writes of the same file in 4-iter window, escalation should fire
    assert paths.model_override.exists()
    assert paths.model_override.read_text().strip() == "codex"


def test_tick_human_required_calls_callback(tmp_project: Path):
    paths = ProjectPaths(root=tmp_project)
    paths.ensure_dirs()

    # Force the HUMAN_REQUIRED path by pre-seeding a codex-stuck state
    from ralph_stack.state import StuckState
    StuckState(
        current_iteration=10,
        current_model="codex",
        codex_takeover_iter=9,
        codex_stuck_streak=1,
    ).save(paths.state_file)

    queue = [[Iteration(number=11, errors=["still broken"])]]

    def source():
        return queue.pop(0) if queue else []

    called = {}

    def on_hr(state, iters):
        called["yes"] = True

    r = RalphexRunner(paths, Path("plan.md"), source, on_hr)
    status = r.tick(tests_now={})
    assert status == "paused"
    assert called.get("yes") is True
