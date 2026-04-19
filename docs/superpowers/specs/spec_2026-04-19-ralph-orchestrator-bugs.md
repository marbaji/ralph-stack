# Spec: ralph-stack orchestrator bug followups from 2026-04-19 dogfood

**Source:** Run 1 of `plan_2026-04-19-ralph-stack-init.md` crashed at iter 4; post-mortem surfaced multiple orchestrator bugs beyond the wrapper `opus:max` fix already landed in `6fdc2d5`.

**Status:** Not yet implemented. This is a spec for a followup plan.

---

## Bug 1: Wrapper `codex` mapping references nonexistent CLI alias

**Severity:** High (killed Run 1 at iter 4).

**Symptom:** `scripts/claude-ralph-wrapper.sh` mapped `codex` override to `--model opus:max`. Claude Code has no such alias and exits with "It may not exist or you may not have access to it." The iter-4 session wrote 17 jsonl lines, 1 second wall-clock, zero work.

**Temp mitigation:** `6fdc2d5` (already landed) remaps `codex` to `opus` so escalations no longer hard-crash.

**Proper fix:** Either (a) surface a real Claude CLI max-effort alias if one exists and wire it through, or (b) handoff codex-marked escalations to a separate `codex` binary via the `claude_command` mechanism rather than the same Claude wrapper. Option (b) matches the original ralphex intent where "codex" meant a different model family, not a different effort setting.

**Acceptance:** Escalation at stuck-detector fire produces a real second-opinion pass, not a claude-rejection crash. Test that exercises `codex` override → non-Opus execution path.

---

## Bug 2: False `COMPLETE` status when ralphex exits mid-plan

**Severity:** High (masked the Run 1 crash as success).

**Symptom:** `orchestrator.run_until_done` writes `_write_complete_report()` on any `runner.proc.poll() is not None` — i.e., whenever ralphex exits, regardless of reason. Combined with the renderer's always-zero checkbox counter, the morning report showed `✅ COMPLETE, 0/0 checkboxes, 4 iterations` while 32 boxes remained unchecked.

**Root cause:** Two stacked defects:
1. `orchestrator.py:110-113` treats any ralphex exit as success.
2. `report.py` never populates `checkboxes_done` / `checkboxes_total` — defaults to 0/0, and the rendered "0/0 complete (0%)" line is the sole checkbox fact in the morning report.

**Proper fix:**
1. On ralphex exit, parse the plan file: count `- [ ]` vs `- [x]`. If any `- [ ]` remain, write `INCOMPLETE` status with the checkbox tally, not `COMPLETE`.
2. Plumb checkbox counts into `RunSummary` (the renderer already accepts them; the orchestrator never populates them).
3. Distinguish ralphex-exit-success (exit 0, no remaining boxes) from ralphex-exit-crash (exit nonzero, or remaining boxes) in the status field.

**Acceptance:** A run that crashes with remaining boxes produces `INCOMPLETE (3/10 tasks, 15/47 boxes)` in the report, not `COMPLETE`. Unit test covers both paths.

---

## Bug 3: Detector `iterations_since_checkbox` miscounts

**Severity:** Medium (directly caused the iter-4 false escalation that triggered Bug 1).

**Symptom:** After Run 1, `stuck-state.json` showed `iterations_since_checkbox: 4` despite iters 1, 2, 3 each flipping a checkbox (15 of 47 boxes flipped across 3 iterations). The detector counted zero flips, concluded "3 iters without progress," fired `escalate_to_codex` at iter 3 (`last_escalation_iter: 3`), and triggered the codex takeover at iter 4 that crashed via Bug 1.

**Hypotheses to check:**
- Detector counts task-level completion (a whole `## Task N` going from any-unchecked to all-checked), not step-level checkbox flips. Ralph runs work one step at a time, so a Task's 5 step-commits read as "5 iterations without a Task flip."
- Detector reads the plan file path differently from the writer (stale path, wrong parent, etc.).
- Detector compares checkbox-count-after vs checkbox-count-before, but the "before" snapshot is taken at wrong moment (e.g., at iter start rather than at previous iter's end).

**Proper fix:** Instrument the detector to log the before/after box counts it sees per iter, reproduce against the Run 1 transcript, identify which branch of the logic misfires, fix, add a regression test that exercises "3 iters, 3 checkbox flips, detector must not escalate."

**Acceptance:** Detector treats step-checkbox flips as progress. Test covers a 3-iter sequence with box deltas +1, +1, +1 → no escalation triggered.

---

## Bug 4: Morning-report checkbox counter always zero

**Severity:** Medium (couples with Bug 2 to produce false-green reports).

**Symptom:** `ralph/morning-report.md` always renders `Plan checkboxes: 0/0 complete (0%)` regardless of actual progress.

**Root cause:** `RunSummary` has `checkboxes_done` / `checkboxes_total` fields, but `_write_complete_report` and `_write_paused_report` never pass them.

**Proper fix:** Add a `count_checkboxes(plan_path: Path) -> tuple[int, int]` helper in `orchestrator.py` (or `report.py`), call it from both report-writer functions, pass to `RunSummary`.

**Acceptance:** Fresh run on any plan produces correct `X/Y complete (Z%)` in the report. Unit test against a synthetic plan with known box counts.

---

## Bug 5: Branch name in report never created

**Severity:** Low (cosmetic, but confusing during post-mortem).

**Symptom:** Run 1 morning report referenced branch `ralph/plan_2026-04-19-ralph-stack-init-2026-04-19`. That branch was never created; commits actually landed on `feat/ralph-stack-dogfood` (the branch ralphex was launched from).

**Root cause:** `compute_branch_name(plan_path, today)` in `runner.py` computes an expected branch name from the plan, but nothing in the ralph-stack / ralphex chain actually creates that branch. Per Deviation B in the orchestrator, ralphex owns the worktree and ralph-stack no longer does `git checkout -B`. So the "branch name" field in the report is aspirational, not observed.

**Proper fix:** Either (a) drop the `branch` field from `RunSummary` and remove the line from the report template (matches reality: ralph commits to whatever branch the worktree is on), or (b) actually create the branch at `runner.start()` via `git checkout -B <computed-name>` and commit to it. Option (a) is simpler and matches the Deviation B decision.

**Acceptance:** Report's branch reference matches the branch commits actually land on, or the reference is removed.

---

## Bug 6: Morning-report reads missing plan after ralphex auto-moves it

**Severity:** High (every successful run misreports as ❌ INCOMPLETE, 0/0).

**Status:** **FIXED** in this commit.

**Symptom:** Run 2 finished successfully (56m45s, 16 iterations, all review gates clean, progress log ends `all phases completed successfully`), yet the morning-report wrote `❌ INCOMPLETE (0 checkboxes still unchecked), 0/0 complete (0%)`.

**Root cause:** On successful completion ralphex commits a move of the plan file into a `completed/` sibling directory (commit `aebbe25 move completed plan: …` in Run 2). `orchestrator._write_complete_report` runs *after* that move and calls `count_checkboxes(plan_path)` with the *original* path. The file no longer exists there, `count_checkboxes` swallows the `OSError` and returns `(0, 0)`, so the report writer concludes `total == 0` → `status = "INCOMPLETE"`.

**Fix:** New helper `_resolve_plan_path(plan_path)` returns the original path if present, else `plan_path.parent / "completed" / plan_path.name` if present, else the original (degrading to `0/0` if neither exists, matching prior behaviour for unrelated failures). `_write_complete_report` now counts checkboxes against the resolved path.

**Acceptance:** Regression test `test_write_complete_report_finds_plan_after_ralphex_moves_it` in `tests/test_orchestrator.py` simulates the move and asserts the report says ✅ COMPLETE with the correct count. Full suite: 78 passed.

---

## Execution order recommendation

1. Bug 4 (easy, unblocks Bug 2 testing).
2. Bug 2 (depends on Bug 4; removes the most dangerous false signal).
3. Bug 3 (requires detector instrumentation; reproducible against Run 1 transcript at `~/.claude/projects/-Users-mohannadarbaji-Desktop-Claude-Code-ralph-stack-ralph-stack-dogfood-worktree/`).
4. Bug 5 (cosmetic; pair with next branch-name touch).
5. Bug 1 proper fix (largest scope; separate codex handoff path).

Bugs 2 through 5 are ralph-stack orchestrator bugs and can be batched as a single followup plan. Bug 1's proper fix (real codex path) is a distinct design question and warrants its own spec.
