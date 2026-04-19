from __future__ import annotations

from dataclasses import dataclass
from ralph_stack.state import StuckState
from ralph_stack.transcript import Iteration
from ralph_stack.errors import error_hash


COOLDOWN_ITERS = 3
NO_PROGRESS_THRESHOLD = 3
FILE_THRASH_COUNT = 4
FILE_THRASH_WINDOW = 3
ERROR_LOOP_STREAK = 3
CODEX_STUCK_THRESHOLD = 2
CODEX_HANDBACK_CLEAN_ITERS = 2


@dataclass
class Decision:
    action: str  # "continue" | "escalate" | "handback" | "human_required"
    next_model: str  # "opus" | "codex"
    reason: str


def _has_test_regression(baseline: dict[str, str], now: dict[str, str]) -> bool:
    for name, status in baseline.items():
        if status == "pass" and now.get(name) == "fail":
            return True
    return False


def _file_thrash(window: list[str], new_files: list[str]) -> str | None:
    combined = (window + new_files)[-(FILE_THRASH_WINDOW + 1):]
    for fp in set(combined):
        if combined.count(fp) >= FILE_THRASH_COUNT:
            return fp
    return None


def decide(
    state: StuckState,
    it: Iteration,
    tests_now: dict[str, str],
    override_error_hash: str | None = None,
) -> Decision:
    """Pure function: given prior state and a new iteration, return next action."""

    # --- If currently on Codex, check handback or codex-also-stuck ---
    if state.current_model == "codex":
        iters_since_takeover = it.number - state.codex_takeover_iter
        codex_made_progress = it.checkboxes_flipped > 0
        codex_clean = not it.errors

        if codex_made_progress:
            return Decision("handback", "opus", "codex_made_progress")
        if codex_clean and iters_since_takeover >= CODEX_HANDBACK_CLEAN_ITERS:
            return Decision("handback", "opus", "codex_clean_iterations")

        new_stuck_streak = state.codex_stuck_streak + (1 if not codex_clean else 0)
        if new_stuck_streak >= CODEX_STUCK_THRESHOLD:
            return Decision("human_required", "opus", "codex_also_stuck")

        return Decision("continue", "codex", "codex_working")

    # --- On Opus: compute signals ---
    in_cooldown = it.number < state.escalation_cooldown_until

    # 1. Test regression
    if _has_test_regression(state.test_baseline, tests_now):
        if in_cooldown:
            return Decision("human_required", "opus", "test_regression_during_cooldown")
        return Decision("escalate", "codex", "test_regression")

    # 2. File thrash
    thrashed = _file_thrash(state.file_access_window, it.files_written)
    if thrashed:
        if in_cooldown:
            return Decision("human_required", "opus", f"file_thrash_during_cooldown:{thrashed}")
        return Decision("escalate", "codex", f"file_thrash:{thrashed}")

    # 3. Error loop
    if it.errors:
        eh = override_error_hash or error_hash(it.errors[0])
        if eh == state.last_error_hash and state.error_streak + 1 >= ERROR_LOOP_STREAK:
            if in_cooldown:
                return Decision("human_required", "opus", "error_loop_during_cooldown")
            return Decision("escalate", "codex", "error_loop")

    # 4. No progress (patient)
    new_iters_since = state.iterations_since_checkbox + (1 if it.checkboxes_flipped == 0 else 0)
    if it.checkboxes_flipped == 0 and new_iters_since >= NO_PROGRESS_THRESHOLD:
        if in_cooldown:
            return Decision("human_required", "opus", "no_progress_during_cooldown")
        return Decision("escalate", "codex", "no_progress")

    return Decision("continue", "opus", "ok")


def update_state(
    state: StuckState,
    it: Iteration,
    decision: Decision,
    tests_now: dict[str, str],
) -> StuckState:
    """Apply an iteration + decision to state, returning the new state."""
    new = StuckState(**vars(state))
    new.current_iteration = it.number

    # file window
    new.file_access_window = (state.file_access_window + it.files_written)[-FILE_THRASH_WINDOW:]

    # error streak
    if it.errors:
        eh = error_hash(it.errors[0])
        if eh == state.last_error_hash:
            new.error_streak = state.error_streak + 1
        else:
            new.last_error_hash = eh
            new.error_streak = 1
    else:
        new.error_streak = 0

    # checkbox tracking
    if it.checkboxes_flipped > 0:
        new.iterations_since_checkbox = 0
    else:
        new.iterations_since_checkbox = state.iterations_since_checkbox + 1

    # test baseline: overlay passes from this iter (monotonic — failures stay failures in baseline only if they were passing before)
    if tests_now:
        merged = dict(state.test_baseline)
        for name, status in tests_now.items():
            if name not in merged and status == "pass":
                merged[name] = "pass"
        new.test_baseline = merged

    # model + escalation bookkeeping
    if decision.action == "escalate":
        new.current_model = "codex"
        new.codex_takeover_iter = it.number + 1
        new.codex_stuck_streak = 0
        new.last_escalation_iter = it.number
        new.escalation_cooldown_until = it.number + COOLDOWN_ITERS
    elif decision.action == "handback":
        new.current_model = "opus"
        new.codex_takeover_iter = -1
        new.codex_stuck_streak = 0
    elif decision.action == "continue" and state.current_model == "codex":
        new.codex_stuck_streak = state.codex_stuck_streak + (1 if it.errors else 0)

    return new
