from __future__ import annotations

import subprocess
from pathlib import Path
from ralph_stack.transcript import Iteration


def write_stuck_dump(path: Path, iterations: list[Iteration], paused_at: int) -> None:
    last_10 = iterations[-10:]
    lines = [f"# Stuck Dump — Paused at iter {paused_at}", ""]
    for it in last_10:
        lines.append(f"## iter-{it.number}")
        if it.files_written:
            lines.append(f"- Files written: {', '.join(it.files_written)}")
        if it.errors:
            lines.append("- Errors:")
            for e in it.errors:
                lines.append(f"  - {e}")
        lines.append(f"- Checkboxes flipped: {it.checkboxes_flipped}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def draft_guardrail_rules(
    stuck_dump_path: Path,
    existing_guardrails: str,
    claude_cmd: list[str] | None = None,
) -> list[tuple[str, str, str]]:
    """Spawn a fresh Claude (Opus) session to propose 1-3 candidate rules.

    Returns a list of (source_iter_label, rule_text, context_excerpt).
    Fresh session is intentional — the session that just got stuck has polluted context.
    """
    claude_cmd = claude_cmd or ["claude", "--model", "claude-opus-4-6", "-p"]
    prompt = _build_draft_prompt(stuck_dump_path.read_text(), existing_guardrails)
    try:
        result = subprocess.run(
            claude_cmd + [prompt],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return []
    return _parse_draft_output(result.stdout)


def _build_draft_prompt(stuck_dump: str, existing: str) -> str:
    return f"""You are drafting guardrail rules for an autonomous coding loop that just got stuck.

Read the stuck-dump below. Propose 1-3 GENERALIZABLE rules (not "never use foo.ts on Tuesday") that would have prevented this specific failure AND similar failures in the future.

Output format, one rule per block, exactly:
SOURCE: iter <N>
RULE: <one-sentence rule>
CONTEXT: <one-sentence evidence from the stuck-dump>
---

Existing guardrails (don't duplicate):
{existing}

Stuck-dump:
{stuck_dump}
"""


def _parse_draft_output(text: str) -> list[tuple[str, str, str]]:
    rules = []
    for block in text.split("---"):
        source = rule = context = ""
        for line in block.strip().splitlines():
            line = line.strip()
            if line.startswith("SOURCE:"):
                source = line.removeprefix("SOURCE:").strip()
            elif line.startswith("RULE:"):
                rule = line.removeprefix("RULE:").strip()
            elif line.startswith("CONTEXT:"):
                context = line.removeprefix("CONTEXT:").strip()
        if source and rule:
            rules.append((source, rule, context))
    return rules[:3]
