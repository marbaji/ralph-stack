from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path


_UNVERIFIED_HEADING_RE = re.compile(r"^## ⚠️ Unverified \((\d{4}-\d{2}-\d{2})\)", re.MULTILINE)


# Baseline rules prepended to every iteration's combined-guardrails.md.
# These patch Ralph-pattern amnesia: because each iteration is a fresh Claude
# session with no memory of the previous iteration's tool errors, the model
# cannot learn within-conversation that e.g. "Bash" is a tool, not a skill.
# Keeping these terse and namespace-focused.
BASELINE_RULES = """# Ralph baseline rules (always applied)

- Built-in tools (Bash, Read, Edit, Write, Glob, Grep, TodoWrite, WebFetch) are TOOLS, not skills. Call them directly. Never invoke them via the Skill tool; "Unknown skill: bash" means you tried Skill(bash) instead of the Bash tool.
- Slash-command shortcuts like `/commit` are for interactive users, not agents. To commit, call the Bash tool with `git commit -m "..."` directly.
- If a tool call returns an error, read the error message and switch to the correct tool or approach. Do NOT retry an identical failing call.
- Your job is to flip checkboxes in the plan. Read the plan, pick the next unchecked `- [ ]` item, execute its steps, mark it `- [x]`, commit, stop. One iteration = one task step, not the whole plan."""


def concat_guardrails(global_path: Path, project_path: Path) -> str:
    """Return baseline rules + global guardrails + project guardrails. Missing files → empty."""
    parts = [BASELINE_RULES]
    for p in (global_path, project_path):
        if p.exists():
            parts.append(p.read_text().rstrip())
    return "\n\n".join(parts)


def has_stale_unverified(lessons_path: Path, max_age_hours: int = 24) -> bool:
    """True if lessons.md contains any ## ⚠️ Unverified heading older than max_age_hours."""
    if not lessons_path.exists():
        return False
    content = lessons_path.read_text()
    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    for m in _UNVERIFIED_HEADING_RE.finditer(content):
        try:
            dt = datetime.strptime(m.group(1), "%Y-%m-%d")
        except ValueError:
            continue
        if dt < cutoff:
            return True
    return False


def append_draft_rules(
    lessons_path: Path,
    date: str,
    rules: list[tuple[str, str, str]],
) -> None:
    """Append a draft-rules block. Each rule = (source_iter_label, rule_text, context_excerpt)."""
    block = [f"\n## ⚠️ Unverified ({date})\n"]
    for source, rule, context in rules:
        block.append(f"- **Draft ({source}):** {rule}")
        block.append(f"  *Context:* {context}")
        block.append(f"  → Promote / Edit / Delete\n")
    content = "\n".join(block) + "\n"
    if lessons_path.exists():
        with lessons_path.open("a") as f:
            f.write(content)
    else:
        lessons_path.parent.mkdir(parents=True, exist_ok=True)
        lessons_path.write_text("# Lessons\n" + content)
