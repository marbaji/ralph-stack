"""Every tracked test file in THIS repo is run by an unconditional pull-request job, or is
excluded here with a reason. See tests/ci_coverage.py. To wire a new suite: name its path in a
test step of .github/workflows/tests.yml (one command per step; pytest, vitest/jest, or
`bash tests/run-shell-suites.sh <dirs>`). To exclude one: add the path below with reason and date.
"""
from pathlib import Path

from tests import ci_coverage

REPO = Path(__file__).resolve().parents[1]

EXCLUSIONS: dict[str, str] = {
}


def test_premise_workflows_and_suites_exist():
    assert ci_coverage.workflow_files(REPO), "no workflow files under .github/workflows"
    files = ci_coverage.tracked_test_files(REPO)
    assert files, "git tracks no test files at all"
    assert any(f.endswith("tests/test_ci_covers_every_suite.py") for f in files), "this file is not tracked"
    assert ci_coverage.test_steps(REPO), "no creditable test step in an unconditional pull-request job"


def test_no_test_config_file_narrows_collection():
    """A pytest.ini / pyproject.toml / setup.cfg / tox.ini / conftest.py, at any tracked depth,
    can add -k or --ignore (addopts), skip directories (norecursedirs, collect_ignore[_glob]), or
    change which files count as tests (python_files, testpaths) behind the checker's back. A
    vitest.config.* / jest.config.* / package.json "jest" key can narrow JS collection the same
    way. See ci_coverage.config_problems() for the exact keys refused."""
    found = ci_coverage.config_problems(REPO)
    assert not found, f"config files narrow test collection behind the checker's back: {found}"


def test_workflows_have_no_fail_closed_problems():
    found = ci_coverage.problems(REPO)
    assert not found, f"test steps the checker cannot read with certainty (one command per step, no narrowing): {found}"


def test_every_tracked_test_file_is_run_by_ci():
    missing = ci_coverage.unwired(REPO, EXCLUSIONS)
    assert not missing, (
        "test files no unconditional pull-request step runs (name the path in a test step of "
        f".github/workflows/tests.yml, or add it to EXCLUSIONS with a reason): {missing}"
    )


def test_every_workflow_test_path_exists():
    gone = ci_coverage.missing_workflow_paths(REPO)
    assert not gone, f"workflow steps name paths that do not exist (a job running nothing): {gone}"


def test_every_exclusion_is_live_and_has_a_reason():
    stale = ci_coverage.stale_exclusions(REPO, EXCLUSIONS)
    assert not stale, f"EXCLUSIONS entries with no reason or matching no tracked test file: {stale}"
