from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ralph_stack.debrief import render_debrief
from ralph_stack.guardrails import has_stale_unverified
from ralph_stack.paths import ProjectPaths
from ralph_stack.state import StuckState


def _project_paths() -> ProjectPaths:
    return ProjectPaths(root=Path.cwd())


def cmd_run(plan: str) -> int:
    paths = _project_paths()
    plan_path = Path(plan)
    if not plan_path.exists():
        print(f"error: plan file not found: {plan}", file=sys.stderr)
        return 2
    if has_stale_unverified(paths.per_project_guardrails):
        print("warning: stale ⚠️ Unverified rules in tasks/lessons.md (>24h old). "
              "Continuing anyway — review when you can.",
              file=sys.stderr)

    # Delegate to an orchestration entrypoint. Kept thin so cli remains testable.
    from ralph_stack.orchestrator import run_until_done
    return run_until_done(paths, plan_path)


def cmd_resume() -> int:
    paths = _project_paths()
    if has_stale_unverified(paths.per_project_guardrails):
        print("warning: stale ⚠️ Unverified rules in tasks/lessons.md (>24h old). "
              "Resuming anyway.",
              file=sys.stderr)
    if not paths.state_file.exists():
        print("error: no prior run to resume (no stuck-state.json).", file=sys.stderr)
        return 2
    from ralph_stack.orchestrator import resume_run
    return resume_run(paths)


def cmd_status() -> int:
    paths = _project_paths()
    if not paths.state_file.exists():
        print("no run in progress (no stuck-state.json).")
        return 0
    state = StuckState.load(paths.state_file)
    print(f"iteration: {state.current_iteration}")
    print(f"model: {state.current_model}")
    print(f"iterations_since_checkbox: {state.iterations_since_checkbox}")
    print(f"last_escalation_iter: {state.last_escalation_iter}")
    return 0


def cmd_debrief() -> int:
    paths = _project_paths()
    try:
        print(render_debrief(paths))
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


def cmd_stop() -> int:
    from ralph_stack.orchestrator import stop_run
    return stop_run(_project_paths())


def cmd_init(plan: str | None) -> int:
    from ralph_stack import setup as setup_mod
    paths = _project_paths()
    plan_path = Path(plan) if plan else None
    try:
        result = setup_mod.initialize(paths, plan_path=plan_path)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print("ralph-stack init\n")
    for path in result.created:
        print(f"  created   {path}")
    for path, keys in result.upserted.items():
        keys_str = ", ".join(keys)
        print(f"  upserted  {path} ({keys_str})")
    for path in result.skipped:
        print(f"  skipped   {path}")
    for path in result.ensured:
        print(f"  ensured   {path}")
    print()
    print(result.next_step)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ralph-stack")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run")
    p_run.add_argument("plan")

    p_init = sub.add_parser("init")
    p_init.add_argument("plan", nargs="?", default=None)

    sub.add_parser("resume")
    sub.add_parser("status")
    sub.add_parser("debrief")
    sub.add_parser("stop")

    args = parser.parse_args(argv)
    if args.cmd == "run":
        return cmd_run(args.plan)
    if args.cmd == "init":
        return cmd_init(args.plan)
    if args.cmd == "resume":
        return cmd_resume()
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "debrief":
        return cmd_debrief()
    if args.cmd == "stop":
        return cmd_stop()
    return 1


if __name__ == "__main__":
    sys.exit(main())
