from __future__ import annotations

import os
import re
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from ralph_stack.escalation import draft_guardrail_rules, write_stuck_dump
from ralph_stack.guardrails import append_draft_rules
from ralph_stack.paths import ProjectPaths
from ralph_stack.report import RunSummary, render_report
from ralph_stack.runner import RalphexRunner, compute_branch_name
from ralph_stack.state import StuckState
from ralph_stack.transcript_source import ClaudeCodeStreamJsonSource


def _encode_session_dir_name(cwd: Path) -> str:
    """Encode an absolute cwd into Claude Code's session dir name.

    Claude Code stores each session's JSONL under
    ``~/.claude/projects/<encoded>/`` where ``<encoded>`` is the absolute
    cwd with every non-alphanumeric character (except ``-``) replaced by
    ``-``. Examples observed on disk:
      /Users/mo/Desktop/Claude Code  →  -Users-mo-Desktop-Claude-Code
      /Users/mo/.claude-mem-observer →  -Users-mo--claude-mem-observer
    """
    return re.sub(r"[^A-Za-z0-9-]", "-", str(cwd))


def _find_ralphex_transcript_dir(paths: ProjectPaths) -> Path:
    """Return the directory ralphex's Claude sessions write into.

    Each ralphex iteration is a fresh Claude Code session that writes one
    JSONL file into ``~/.claude/projects/<encoded-cwd>/``. Per Spike
    Deviation A, we track the DIRECTORY and let
    :class:`ClaudeCodeStreamJsonSource` emit one ``Iteration`` per new file.

    Deterministic by design: we encode ``paths.root`` (the cwd ralphex runs
    in) and return the matching session dir, whether or not it exists yet.
    Overridable via ``RALPH_STACK_TRANSCRIPT_DIR``. The dogfood run that
    motivated this function silently latched onto an unrelated newest-mtime
    subdir and misread 106 "iterations" from a different session.
    """
    env = os.environ.get("RALPH_STACK_TRANSCRIPT_DIR")
    if env:
        return Path(env)
    base = Path.home() / ".claude" / "projects"
    return base / _encode_session_dir_name(paths.root.resolve())


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def count_checkboxes(plan_path: Path) -> tuple[int, int]:
    """Return (checked, total) for a plan file's GFM task-list checkboxes.

    Matches ``- [ ]`` and ``- [x]`` (case-insensitive x) at any indentation.
    Missing/unreadable plans return (0, 0) so callers can render a degraded
    but non-crashing report.
    """
    try:
        text = plan_path.read_text()
    except OSError:
        return (0, 0)
    checked = len(re.findall(r"-\s\[[xX]\]", text))
    unchecked = len(re.findall(r"-\s\[\s\]", text))
    return (checked, checked + unchecked)


def _on_human_required(
    paths: ProjectPaths, state: StuckState, all_iters, plan_path: Path | None = None
) -> None:
    write_stuck_dump(paths.stuck_dump, all_iters, paused_at=state.current_iteration)
    existing = ""
    if paths.per_project_guardrails.exists():
        existing = paths.per_project_guardrails.read_text()
    rules = draft_guardrail_rules(paths.stuck_dump, existing)
    if rules:
        append_draft_rules(paths.per_project_guardrails, date=_today(), rules=rules)
    _write_paused_report(paths, state, unverified=rules, plan_path=plan_path)


def _write_paused_report(
    paths: ProjectPaths,
    state: StuckState,
    unverified: list,
    plan_path: Path | None = None,
) -> None:
    done, total = count_checkboxes(plan_path) if plan_path else (0, 0)
    summary = RunSummary(
        plan_basename=os.environ.get("RALPH_STACK_PLAN_BASENAME", "unknown"),
        date=_today(),
        status="PAUSED",
        paused_at_iter=state.current_iteration,
        checkboxes_done=done,
        checkboxes_total=total,
        iterations=state.current_iteration,
        unverified_rules=unverified or [],
    )
    paths.post_run_report.write_text(render_report(summary))


def run_until_done(paths: ProjectPaths, plan_path: Path) -> int:
    paths.ensure_dirs()

    # Deviation B: ralphex owns the worktree (via its `--worktree` flag);
    # ralph-stack no longer does `git checkout -B` here.

    os.environ["RALPH_STACK_PLAN_BASENAME"] = plan_path.stem

    transcript_dir = _find_ralphex_transcript_dir(paths)
    source = ClaudeCodeStreamJsonSource(transcript_dir)

    runner = RalphexRunner(
        paths=paths,
        plan_path=plan_path,
        transcript_source=source.read_new,
        on_human_required=lambda state, iters: _on_human_required(
            paths, state, iters, plan_path=plan_path
        ),
    )
    runner.start()

    try:
        while True:
            time.sleep(5)
            status = runner.tick(tests_now={})
            if status == "paused":
                print(
                    f"PAUSED at iter {StuckState.load(paths.state_file).current_iteration}. "
                    f"See {paths.post_run_report}"
                )
                return 0
            if runner.proc and runner.proc.poll() is not None:
                # ralphex exited on its own → run complete
                _write_complete_report(paths, plan_path)
                return 0
    except KeyboardInterrupt:
        runner.stop()
        return 130


def _resolve_plan_path(plan_path: Path) -> Path:
    """Return the plan's current on-disk location.

    On successful completion ralphex commits a move of the plan into a
    ``completed/`` sibling directory. The orchestrator's exit-report path is
    still the *original* path, so if the file has moved we follow it there
    rather than read a missing file and misreport the run as 0/0 INCOMPLETE.
    """
    if plan_path.exists():
        return plan_path
    moved = plan_path.parent / "completed" / plan_path.name
    if moved.exists():
        return moved
    return plan_path


def _write_complete_report(paths: ProjectPaths, plan_path: Path) -> None:
    state = StuckState.load(paths.state_file) if paths.state_file.exists() else StuckState()
    done, total = count_checkboxes(_resolve_plan_path(plan_path))
    # ralphex exited; the plan's own checkbox state is the only truth about
    # whether the run actually finished. Any remaining `- [ ]` means the
    # process died early (crash, detector escalation → wrapper reject, etc.).
    status = "COMPLETE" if total > 0 and done == total else "INCOMPLETE"
    summary = RunSummary(
        plan_basename=plan_path.stem,
        date=_today(),
        status=status,
        checkboxes_done=done,
        checkboxes_total=total,
        iterations=state.current_iteration,
        branch=compute_branch_name(plan_path, _today()),
    )
    paths.post_run_report.write_text(render_report(summary))


def resume_run(paths: ProjectPaths) -> int:
    # Resume = relaunch ralphex; it reads the plan fresh and flips remaining checkboxes.
    # The state file persists the detector's understanding so signals carry over.
    plan_env = os.environ.get("RALPH_STACK_PLAN_PATH")
    if not plan_env:
        print("error: set RALPH_STACK_PLAN_PATH to the plan you were running.", file=sys.stderr)
        return 2
    return run_until_done(paths, Path(plan_env))


def stop_run(paths: ProjectPaths) -> int:
    pid_file = paths.ralph_dir / "ralphex.pid"
    if not pid_file.exists():
        print("no running ralphex process tracked.")
        return 0
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
    except (ValueError, ProcessLookupError):
        pass
    return 0
