from pathlib import Path
from ralph_stack.report import RunSummary, render_report


def test_render_paused_report():
    summary = RunSummary(
        plan_basename="refactor-renewal-v3",
        date="2026-04-19",
        status="PAUSED",
        paused_at_iter=72,
        checkboxes_done=23,
        checkboxes_total=41,
        iterations=72,
        branch="ralph/refactor-renewal-v3-2026-04-18",
        codex_escalations_resolved=2,
        codex_escalations_unresolved=1,
        recent_commits=[("a3f21b", 72, "fix: down migration for users table")],
        unverified_rules=[("iter 71", "check down migration alongside up", "iter 68-72 kept breaking down")],
    )
    out = render_report(summary)
    assert "# Ralph Run — refactor-renewal-v3 — 2026-04-19" in out
    assert "⏸ PAUSED (HUMAN_REQUIRED at iter 72)" in out
    assert "⚠️ Unverified rules awaiting review" in out
    assert "check down migration alongside up" in out
    assert "23/41" in out
    assert "ralph-stack resume" in out


def test_render_complete_report():
    summary = RunSummary(
        plan_basename="small-plan",
        date="2026-04-19",
        status="COMPLETE",
        checkboxes_done=5,
        checkboxes_total=5,
        iterations=12,
        branch="ralph/small-plan-2026-04-19",
    )
    out = render_report(summary)
    assert "✅ COMPLETE" in out
    assert "Nothing — run complete" in out


def test_render_incomplete_report_shows_remaining_boxes():
    # Regression: Run 1 of the dogfood crashed at iter 4 with 15/47 boxes
    # flipped; the report wrote "✅ COMPLETE, 0/0" because orchestrator
    # treated any ralphex exit as success and never populated checkbox counts.
    summary = RunSummary(
        plan_basename="plan_2026-04-19-ralph-stack-init",
        date="2026-04-19",
        status="INCOMPLETE",
        checkboxes_done=15,
        checkboxes_total=47,
        iterations=4,
        branch="feat/ralph-stack-dogfood",
    )
    out = render_report(summary)
    assert "❌ INCOMPLETE" in out
    assert "32 checkboxes still unchecked" in out
    assert "15/47" in out
    assert "ralph-stack run" in out
    assert "✅ COMPLETE" not in out
