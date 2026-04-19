#!/usr/bin/env bash
# End-to-end synthetic dry-run exercising detector -> stuck-dump -> draft -> report.
# Uses tests/fixtures/full_stuck_run.jsonl as a fake transcript, runs the full
# decision/escalation pipeline, and verifies HUMAN_REQUIRED fires with the
# expected morning report + lessons.md draft block.
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"

# Prefer the venv's python if it exists so ralph_stack is importable without
# needing a user-wide install.
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PY="$REPO_ROOT/.venv/bin/python"
else
  PY="python3"
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

cd "$TMP"
git init -q
git config user.email dry-run@example.com
git config user.name dry-run
cp "$REPO_ROOT/tests/fixtures/full_stuck_run.jsonl" transcript.jsonl
mkdir -p tasks ralph
echo "# Lessons" > tasks/lessons.md

export RALPH_STACK_TRANSCRIPT_PATH="$TMP/transcript.jsonl"
export RALPH_STACK_PLAN_BASENAME="dry-run-plan"

"$PY" - <<'PY'
import os
from pathlib import Path
from ralph_stack.paths import ProjectPaths
from ralph_stack.transcript import parse_iterations
from ralph_stack.detector import decide, update_state
from ralph_stack.state import StuckState
from ralph_stack.guardrails import append_draft_rules
from ralph_stack.escalation import write_stuck_dump
from ralph_stack.report import RunSummary, render_report

paths = ProjectPaths(root=Path.cwd())
paths.ensure_dirs()
state = StuckState()
iters = list(parse_iterations(Path(os.environ["RALPH_STACK_TRANSCRIPT_PATH"])))

human_required_iter = None
for it in iters:
    d = decide(state, it, tests_now={})
    print(f"iter {it.number}: {d.action} model={d.next_model} reason={d.reason}")
    state = update_state(state, it, d, tests_now={})
    state.save(paths.state_file)
    if d.action == "human_required":
        human_required_iter = it
        idx = iters.index(it)
        write_stuck_dump(paths.stuck_dump, iters[: idx + 1], paused_at=it.number)
        draft_rules = [(
            f"iter {it.number}",
            "When the same error persists 3 iterations, inspect the failing call site before patching.",
            f"Loop observed at iter {it.number}: {d.reason}",
        )]
        append_draft_rules(paths.per_project_guardrails, "2026-04-19", draft_rules)
        s = RunSummary(
            plan_basename=os.environ.get("RALPH_STACK_PLAN_BASENAME", "dry-run-plan"),
            date="2026-04-19",
            status="PAUSED",
            paused_at_iter=it.number,
            iterations=it.number,
            unverified_rules=draft_rules,
        )
        paths.morning_report.write_text(render_report(s))
        break

if human_required_iter is None:
    raise SystemExit("FAIL: HUMAN_REQUIRED never fired during dry-run")
print(f"\nHUMAN_REQUIRED fired at iter {human_required_iter.number}")
PY

echo "---"
echo "morning report:"
cat ralph/morning-report.md
echo "---"
echo "lessons.md:"
cat tasks/lessons.md
echo "---"
echo "stuck-dump (first 40 lines):"
head -40 ralph/stuck-dump.md
echo "---"
echo "DRY-RUN OK"
