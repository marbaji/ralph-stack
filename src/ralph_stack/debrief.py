"""Post-run debrief renderer — the deterministic half of `/ralph-review`.

Reads the artifacts the orchestrator wrote at exit (``post-run-report.md``,
``combined-guardrails.md``, ``stuck-state.json``, and the per-plan progress
log) and prints a four-section markdown summary:

1. Status — status line + checkbox count + iterations + branch, parsed from
   ``post-run-report.md``.
2. What happened — last ~40 lines of the progress log, included when the
   status is not ``COMPLETE`` so the reader sees why ralphex stopped.
3. Unverified guardrails — draft rules awaiting human promote/edit/delete.
4. Suspect flags — heuristic orchestrator-bug checks (e.g. ``0/0`` checkbox
   count with real task commits, branch mismatch between report and repo,
   unresolved escalation with a ``COMPLETE`` verdict, all plan boxes flipped
   but status ``INCOMPLETE``).

This module is read-only — it never rewrites ``post-run-report.md``. Agent
interpretation (which suspect flag to act on, drafting follow-up plans) lives
in the ``/ralph-review`` skill on top of this output.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from ralph_stack.paths import ProjectPaths


TASK_COMMIT_PATTERN = re.compile(r"\b(task|step|iter|fix|feat|chore)\b", re.I)


def parse_post_run_report(text: str) -> dict:
    """Extract status + progress fields from a ``post-run-report.md`` body.

    Returns a dict with keys: ``status`` (COMPLETE/INCOMPLETE/PAUSED/RUNNING),
    ``plan_basename``, ``date``, ``checkboxes_done``, ``checkboxes_total``,
    ``iterations``, ``branch``. Missing fields default to empty/zero rather
    than raising, so malformed reports still render something readable.
    """
    result = {
        "status": "",
        "plan_basename": "",
        "date": "",
        "checkboxes_done": 0,
        "checkboxes_total": 0,
        "iterations": 0,
        "branch": "",
    }

    m = re.search(r"^#\s+Ralph Run\s+—\s+(.+?)\s+—\s+(\S+)\s*$", text, re.M)
    if m:
        result["plan_basename"] = m.group(1).strip()
        result["date"] = m.group(2).strip()

    m = re.search(r"^##\s+Status:\s+(.+?)$", text, re.M)
    if m:
        line = m.group(1)
        if "COMPLETE" in line and "INCOMPLETE" not in line:
            result["status"] = "COMPLETE"
        elif "INCOMPLETE" in line:
            result["status"] = "INCOMPLETE"
        elif "PAUSED" in line:
            result["status"] = "PAUSED"
        else:
            result["status"] = "RUNNING"

    m = re.search(r"Plan checkboxes:\s+(\d+)/(\d+)", text)
    if m:
        result["checkboxes_done"] = int(m.group(1))
        result["checkboxes_total"] = int(m.group(2))

    m = re.search(r"^-\s+Iterations:\s+(\d+)", text, re.M)
    if m:
        result["iterations"] = int(m.group(1))

    m = re.search(r"branch:\s+([^\s)]+)", text)
    if m:
        result["branch"] = m.group(1).strip()

    return result


def find_unverified_drafts(guardrails_text: str) -> list[str]:
    """Return each ⚠️ Unverified draft block as a single joined string."""
    if "⚠️ Unverified" not in guardrails_text and "Draft" not in guardrails_text:
        return []
    blocks: list[str] = []
    current: list[str] = []
    in_block = False
    for line in guardrails_text.splitlines():
        if "⚠️ Unverified" in line or line.strip().startswith("## ⚠️"):
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            in_block = True
            current.append(line)
            continue
        if in_block:
            if line.startswith("## ") and "⚠️" not in line:
                blocks.append("\n".join(current).strip())
                current = []
                in_block = False
                continue
            current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [b for b in blocks if b]


def tail_progress_log(path: Path, lines: int = 40) -> str:
    """Return the last ``lines`` lines of a progress log, or '' if absent."""
    try:
        text = path.read_text()
    except OSError:
        return ""
    all_lines = text.splitlines()
    return "\n".join(all_lines[-lines:])


def _git_current_branch(cwd: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if out.returncode != 0:
        return None
    branch = out.stdout.strip()
    return branch or None


def _git_has_task_commits(cwd: Path) -> bool:
    try:
        out = subprocess.run(
            ["git", "-C", str(cwd), "log", "--oneline", "-20"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    if out.returncode != 0:
        return False
    return any(TASK_COMMIT_PATTERN.search(line) for line in out.stdout.splitlines())


def _all_boxes_flipped(plan_path: Path | None) -> bool | None:
    """True if plan has checkboxes and none remain unchecked; None if unknown."""
    if plan_path is None:
        return None
    candidates = [plan_path, plan_path.parent / "completed" / plan_path.name]
    for p in candidates:
        try:
            text = p.read_text()
        except OSError:
            continue
        unchecked = re.search(r"-\s\[\s\]", text)
        checked = re.search(r"-\s\[[xX]\]", text)
        if checked is None:
            return None
        return unchecked is None
    return None


def heuristic_flags(
    cwd: Path,
    report: dict,
    stuck_state: dict | None = None,
    plan_path: Path | None = None,
) -> list[str]:
    """Surface orchestrator-bug suspects. Pure structural checks, no LLM.

    Flags are strings ready to print. The ``/ralph-review`` skill layers
    interpretation (which flag matches which known bug, what to do) on top.
    """
    flags: list[str] = []

    if report.get("checkboxes_total", 0) == 0 and _git_has_task_commits(cwd):
        flags.append(
            "post-run-report shows 0/0 checkboxes but git log has task-flavored commits — "
            "suspect plan moved before count (see known Bug 6)."
        )

    reported_branch = report.get("branch", "")
    actual_branch = _git_current_branch(cwd)
    if reported_branch and actual_branch and reported_branch != actual_branch:
        flags.append(
            f"branch in report ({reported_branch!r}) does not match current git "
            f"branch ({actual_branch!r})."
        )

    if stuck_state and report.get("status") == "COMPLETE":
        last_esc = stuck_state.get("last_escalation_iter", 0) or 0
        if last_esc > 0:
            flags.append(
                f"stuck-state recorded an escalation at iter {last_esc} but report "
                f"says COMPLETE — verify the escalation actually resolved."
            )

    if report.get("status") == "INCOMPLETE":
        verdict = _all_boxes_flipped(plan_path)
        if verdict is True:
            flags.append(
                "report says INCOMPLETE but every box in the plan is flipped — "
                "suspect stale checkbox count."
            )

    return flags


def _load_stuck_state(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _find_progress_log(paths: ProjectPaths, plan_basename: str) -> Path | None:
    """Best-effort locate ``.ralphex/progress/progress-<plan_basename>.txt``.

    ralphex places progress logs under the *project root*'s ``.ralphex/``
    directory. If multiple exist and the basename isn't a direct match, return
    the most recently modified — matches what a human would check first.
    """
    progress_dir = paths.root / ".ralphex" / "progress"
    if not progress_dir.exists():
        return None
    exact = progress_dir / f"progress-{plan_basename}.txt"
    if exact.exists():
        return exact
    candidates = sorted(
        progress_dir.glob("progress-*.txt"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def render_debrief(paths: ProjectPaths) -> str:
    """Render the four-section debrief for the given project paths.

    Raises ``FileNotFoundError`` if ``ralph/post-run-report.md`` is absent —
    the orchestrator writes it at every run exit, so its absence means either
    a run is in progress (use ``ralph-stack status``) or nothing ran here.
    """
    if not paths.post_run_report.exists():
        raise FileNotFoundError(
            f"no completed run found at {paths.post_run_report}. "
            "If a run is in progress, try `ralph-stack status`."
        )

    report_text = paths.post_run_report.read_text()
    report = parse_post_run_report(report_text)

    stuck_state = _load_stuck_state(paths.state_file) if paths.state_file.exists() else None

    guardrails_path = paths.ralph_dir / "combined-guardrails.md"
    guardrails_text = guardrails_path.read_text() if guardrails_path.exists() else ""
    drafts = find_unverified_drafts(guardrails_text)

    progress_log = _find_progress_log(paths, report["plan_basename"])
    progress_tail = tail_progress_log(progress_log, lines=40) if progress_log else ""

    flags = heuristic_flags(paths.root, report, stuck_state=stuck_state, plan_path=None)

    lines: list[str] = []
    lines.append(f"# Ralph Debrief — {report['plan_basename']} — {report['date']}")
    lines.append("")

    lines.append("## 1. Status")
    status_icon = {"COMPLETE": "✅", "INCOMPLETE": "❌", "PAUSED": "⏸"}.get(
        report["status"], ""
    )
    lines.append(
        f"{status_icon} {report['status'] or 'UNKNOWN'} — "
        f"{report['checkboxes_done']}/{report['checkboxes_total']} checkboxes, "
        f"{report['iterations']} iterations"
        + (f", branch `{report['branch']}`" if report["branch"] else "")
    )
    lines.append("")

    lines.append("## 2. What happened")
    if report["status"] == "COMPLETE":
        lines.append("Run completed successfully.")
    elif progress_tail:
        lines.append("Last ~40 lines of the progress log:")
        lines.append("")
        lines.append("```")
        lines.append(progress_tail)
        lines.append("```")
    else:
        lines.append("No progress log found under `.ralphex/progress/`.")
    lines.append("")

    lines.append("## 3. Unverified guardrails")
    if not drafts:
        lines.append("No unverified drafts.")
    else:
        for draft in drafts:
            lines.append("")
            lines.append(draft)
    lines.append("")

    lines.append("## 4. Suspect flags")
    if not flags:
        lines.append("No orchestrator-bug suspects.")
    else:
        for f in flags:
            lines.append(f"- {f}")
    lines.append("")

    lines.append(
        "Invoke `/ralph-review` for agent-assisted bug triage and surgical "
        "follow-up-plan drafting."
    )
    lines.append("")

    return "\n".join(lines)
