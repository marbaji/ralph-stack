from pathlib import Path
from ralph_stack.paths import ProjectPaths


def test_project_paths(tmp_project: Path):
    p = ProjectPaths(root=tmp_project)
    assert p.state_file == tmp_project / "ralph" / "stuck-state.json"
    assert p.model_override == tmp_project / "ralph" / "next-iter-model.txt"
    assert p.post_run_report == tmp_project / "ralph" / "post-run-report.md"
    assert p.stuck_dump == tmp_project / "ralph" / "stuck-dump.md"
    assert p.per_project_guardrails == tmp_project / "tasks" / "lessons.md"


def test_paths_ensure_dirs(tmp_path: Path):
    p = ProjectPaths(root=tmp_path)
    p.ensure_dirs()
    assert (tmp_path / "ralph").is_dir()
