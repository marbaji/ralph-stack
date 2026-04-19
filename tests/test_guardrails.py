from datetime import datetime, timedelta
from pathlib import Path
from ralph_stack.guardrails import (
    BASELINE_RULES,
    concat_guardrails,
    has_stale_unverified,
    append_draft_rules,
)


def test_concat_both_files(tmp_path: Path):
    g = tmp_path / "global.md"
    p = tmp_path / "project.md"
    g.write_text("# Global\n- rule A\n")
    p.write_text("# Project\n- rule B\n")
    out = concat_guardrails(g, p)
    assert BASELINE_RULES in out
    assert "rule A" in out
    assert "rule B" in out
    assert out.index(BASELINE_RULES) < out.index("rule A")
    assert out.index("rule A") < out.index("rule B")


def test_concat_missing_files_returns_baseline_only(tmp_path: Path):
    out = concat_guardrails(tmp_path / "nope.md", tmp_path / "also_nope.md")
    assert out == BASELINE_RULES


def test_has_stale_unverified_true(tmp_path: Path):
    p = tmp_path / "lessons.md"
    old = (datetime.now() - timedelta(hours=25)).strftime("%Y-%m-%d")
    p.write_text(f"# Lessons\n\n## ⚠️ Unverified ({old})\n- draft rule\n")
    assert has_stale_unverified(p, max_age_hours=24) is True


def test_has_stale_unverified_false_recent(tmp_path: Path):
    p = tmp_path / "lessons.md"
    today = datetime.now().strftime("%Y-%m-%d")
    p.write_text(f"# Lessons\n\n## ⚠️ Unverified ({today})\n- draft rule\n")
    assert has_stale_unverified(p, max_age_hours=24) is False


def test_has_stale_unverified_false_no_unverified(tmp_path: Path):
    p = tmp_path / "lessons.md"
    p.write_text("# Lessons\n\n## 2026-04-15\n- promoted rule\n")
    assert has_stale_unverified(p, max_age_hours=24) is False


def test_append_draft_rules(tmp_path: Path):
    p = tmp_path / "lessons.md"
    p.write_text("# Lessons\n")
    append_draft_rules(p, date="2026-04-19", rules=[
        ("iter 71", "When editing migrations, check down alongside up.", "iter 68-72 kept breaking down migration"),
    ])
    content = p.read_text()
    assert "## ⚠️ Unverified (2026-04-19)" in content
    assert "When editing migrations" in content
    assert "iter 68-72 kept breaking" in content
