from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RunSummary:
    plan_basename: str
    date: str
    status: str  # "RUNNING" | "PAUSED" | "COMPLETE" | "INCOMPLETE"
    paused_at_iter: int | None = None
    checkboxes_done: int = 0
    checkboxes_total: int = 0
    iterations: int = 0
    branch: str = ""
    codex_escalations_resolved: int = 0
    codex_escalations_unresolved: int = 0
    recent_commits: list[tuple[str, int, str]] = field(default_factory=list)
    unverified_rules: list[tuple[str, str, str]] = field(default_factory=list)


def _status_line(s: RunSummary) -> str:
    if s.status == "PAUSED":
        return f"⏸ PAUSED (HUMAN_REQUIRED at iter {s.paused_at_iter})"
    if s.status == "COMPLETE":
        return "✅ COMPLETE"
    if s.status == "INCOMPLETE":
        remaining = s.checkboxes_total - s.checkboxes_done
        return f"❌ INCOMPLETE ({remaining} checkboxes still unchecked)"
    return "RUNNING"


def _next_action(s: RunSummary) -> str:
    if s.status == "PAUSED":
        return "Review unverified rules above, then:\n  ralph-stack resume"
    if s.status == "COMPLETE":
        return "Nothing — run complete."
    if s.status == "INCOMPLETE":
        return (
            "ralphex exited but the plan has unchecked boxes. "
            "Investigate the last iter's transcript, fix the blocker, then:\n"
            "  ralph-stack run <plan_path>"
        )
    return "In progress. Check back later or run `ralph-stack status`."


def render_report(s: RunSummary) -> str:
    lines = [
        f"# Ralph Run — {s.plan_basename} — {s.date}",
        "",
        f"## Status: {_status_line(s)}",
        "",
    ]

    if s.unverified_rules:
        lines += [
            "## ⚠️ Unverified rules awaiting review",
            "(listed first — required reading before resume)",
            "",
        ]
        for i, (source, rule, context) in enumerate(s.unverified_rules, 1):
            lines += [
                f"{i}. **Draft ({source}):** {rule}",
                f"   *Context:* {context}",
                f"   → Promote / Edit / Delete",
                "",
            ]

    pct = int(100 * s.checkboxes_done / s.checkboxes_total) if s.checkboxes_total else 0
    lines += [
        "## Progress",
        f"- Plan checkboxes: {s.checkboxes_done}/{s.checkboxes_total} complete ({pct}%)",
        f"- Iterations: {s.iterations}",
        f"- Commits: {s.iterations} (branch: {s.branch})",
        f"- Escalations to Codex: {s.codex_escalations_resolved} resolved, "
        f"{s.codex_escalations_unresolved} unresolved",
        "",
    ]

    if s.recent_commits:
        lines += ["## Recent commits (last 10)"]
        for sha, iter_n, msg in s.recent_commits[-10:]:
            lines.append(f"- {sha}  iter {iter_n}  {msg}")
        lines.append("")

    lines += ["## Next action", _next_action(s), ""]
    return "\n".join(lines)
