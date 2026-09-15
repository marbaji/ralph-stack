"""Should-fail proof for the CI coverage checker. Builds throwaway git repos and proves each
rule can go red: an unwired FILE is reported; a named file does not credit its siblings; runner
kinds must match; --ignore subtracts, and so does an --ignore-glob matching an ancestor
directory; globs do not cross '/'; a directory argument does not reach a test file below one of
pytest's default norecursedirs; a conftest.py collection hook is reported; filtered PR triggers,
conditional jobs, conditional needs, continue-on-error steps, commented-out lines, shell
operators, a `shell:` other than bash, narrowing flags, node ids and PYTEST_ADDOPTS all refuse
credit; and the real repo-facing test exits non-zero in a subprocess on an unwired repo and zero
on a wired one.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests import ci_coverage

HERE = Path(__file__).resolve().parent
PY = "def test_x():\n    assert True\n"
SH = "#!/bin/bash\nexit 0\n"
TS = "import { it } from 'vitest'\nit('x', () => {})\n"


def _repo(tmp_path: Path, workflow_yaml: str, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)          # callers pass tmp_path / "2" etc.; the parent may not exist
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    wf = repo / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "tests.yml").write_text(workflow_yaml)
    for rel, body in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    _add_all(repo)
    return repo


def _add_all(repo: Path) -> None:
    """-f so the fixture is what this file says it is: the machine's global excludesfile (or any
    other ambient ignore rule) must not decide which fixture files end up tracked -- a fixture
    naming a directory like venv/ or node_modules/ would otherwise be silently empty here and
    fully tracked on the next machine."""
    subprocess.run(["git", "-C", str(repo), "add", "-A", "-f"], check=True)


def _wf(run: str, *, on: str = "[pull_request, push]", job_extra: str = "", step_extra: str = "", env: str = "") -> str:
    return (
        f"name: t\non: {on}\n{env}jobs:\n  t:\n    runs-on: ubuntu-latest\n{job_extra}"
        f"    steps:\n      - uses: actions/checkout@v4\n      - run: {run}\n{step_extra}"
    )


def _ok(repo):
    """A positive fixture must be clean on every axis, not just unwired()."""
    assert ci_coverage.problems(repo) == []
    assert ci_coverage.missing_workflow_paths(repo) == []
    return ci_coverage.unwired(repo, {})


def test_unwired_file_is_reported(tmp_path):
    repo = _repo(tmp_path, _wf("python3 -m pytest tests/a -q"), {"tests/a/test_a.py": PY, "tests/b/test_b.py": PY})
    assert _ok(repo) == ["tests/b/test_b.py"]


def test_wired_repo_reports_nothing(tmp_path):
    repo = _repo(tmp_path, _wf("python3 -m pytest tests -q"), {"tests/a/test_a.py": PY, "tests/b/deep/test_b.py": PY})
    assert _ok(repo) == []


def test_bare_directory_arguments_count(tmp_path):
    repo = _repo(tmp_path, _wf("python3 -m pytest skills tests -q"), {"skills/x/test_x.py": PY, "tests/test_t.py": PY})
    assert _ok(repo) == []


def test_named_file_does_not_credit_its_siblings(tmp_path):
    repo = _repo(tmp_path, _wf("python3 -m pytest tests/a/test_one.py -q"),
                 {"tests/a/test_one.py": PY, "tests/a/test_two.py": PY, "tests/a/sub/test_three.py": PY})
    assert _ok(repo) == ["tests/a/sub/test_three.py", "tests/a/test_two.py"]


def test_runner_kind_must_match_file_kind(tmp_path):
    repo = _repo(tmp_path, _wf("python3 -m pytest hooks/tests -q"), {"hooks/tests/test_h.sh": SH})
    assert _ok(repo) == ["hooks/tests/test_h.sh"]


def test_only_the_designated_runner_credits_shell_files(tmp_path):
    files = {"tests/run-shell-suites.sh": SH, "tests/other.sh": SH, "hooks/tests/test_h.sh": SH, "af/tests/deep/test-d.sh": SH}
    repo = _repo(tmp_path, _wf("bash tests/run-shell-suites.sh hooks/tests af/tests"), files)
    assert _ok(repo) == []
    repo2 = _repo(tmp_path / "2", _wf("bash tests/other.sh hooks/tests af/tests"), files)
    assert ci_coverage.unwired(repo2, {}) == ["af/tests/deep/test-d.sh", "hooks/tests/test_h.sh"]
    assert ci_coverage.problems(repo2) == ["tests.yml/t: bash may only invoke tests/run-shell-suites.sh"]


def test_direct_bash_of_a_test_file_is_refused(tmp_path):
    repo = _repo(tmp_path, _wf("bash hooks/tests/test_*.sh"), {"hooks/tests/test_h.sh": SH})
    assert ci_coverage.problems(repo) == ["tests.yml/t: bash may only invoke tests/run-shell-suites.sh"]


def test_js_runner_credits_ts_and_js_and_skips_the_run_word(tmp_path):
    repo = _repo(tmp_path, _wf("npx vitest run src"), {"src/a.test.ts": TS, "src/b.spec.js": TS, "src/test_c.py": PY})
    assert _ok(repo) == ["src/test_c.py"]


def test_ignore_and_ignore_glob_subtract(tmp_path):
    repo = _repo(tmp_path, _wf("python3 -m pytest tests --ignore=tests/slow --ignore-glob=tests/*_smoke.py -q"),
                 {"tests/test_a.py": PY, "tests/slow/test_s.py": PY, "tests/test_x_smoke.py": PY})
    assert _ok(repo) == ["tests/slow/test_s.py", "tests/test_x_smoke.py"]


def test_ignore_glob_crosses_directories_like_pytest_does(tmp_path):
    """pytest's --ignore-glob is fnmatch over the whole path: '*' crosses '/'. Unlike a
    positional glob (test_glob_does_not_cross_directories, just below), --ignore-glob must match
    the same way pytest itself does, or the checker under-subtracts and keeps crediting a file
    pytest actually skips."""
    repo = _repo(tmp_path, _wf("python3 -m pytest tests a --ignore-glob=*/slow/* -q"),
                 {"tests/test_a.py": PY, "a/b/slow/test_x.py": PY})
    assert _ok(repo) == ["a/b/slow/test_x.py"]


def test_ignore_glob_matching_a_directory_subtracts_everything_below(tmp_path):
    """pytest matches --ignore-glob against every collected path, DIRECTORIES included, so
    `--ignore-glob=tests/slow` skips the whole directory. A checker that only matched the glob
    against test FILE paths would keep crediting tests/slow/test_hidden.py, which no step runs."""
    hidden = ["tests/slow/deep/test_deeper.py", "tests/slow/test_hidden.py"]
    repo = _repo(tmp_path, _wf("python3 -m pytest tests --ignore-glob=tests/slow -q"),
                 {"tests/test_a.py": PY, "tests/slow/test_hidden.py": PY, "tests/slow/deep/test_deeper.py": PY})
    # The credit claim first, on its own: _ok() also asserts the other axes are clean, and its
    # missing_workflow_paths() check would otherwise fire first and hide a still-credited file.
    assert ci_coverage.unwired(repo, {}) == hidden
    assert _ok(repo) == hidden
    # --ignore names a path rather than a glob, and must subtract that path and everything below it.
    repo2 = _repo(tmp_path / "2", _wf("python3 -m pytest tests --ignore=tests/slow -q"),
                  {"tests/test_a.py": PY, "tests/slow/test_hidden.py": PY, "tests/slow/deep/test_deeper.py": PY})
    assert _ok(repo2) == hidden


def test_pytest_default_norecursedirs_are_not_credited_by_a_directory_argument(tmp_path):
    """pytest never recurses into a directory matching its default norecursedirs, so a step
    naming an ancestor directory does not run a test file below one. Each name here IS the claim
    (they are pytest's documented defaults), so they are spelled out rather than read back from
    the checker's own constant."""
    for seg in ("build", "dist", "venv", "node_modules", "CVS", "_darcs", ".hidden", "pkg.egg"):
        hidden = f"tests/{seg}/test_hidden.py"
        repo = _repo(tmp_path / seg, _wf("python3 -m pytest tests -q"), {"tests/test_a.py": PY, hidden: PY})
        assert _ok(repo) == [hidden], seg
    # Naming the file explicitly credits it: pytest collects a path given on the command line.
    repo = _repo(tmp_path / "explicit", _wf("python3 -m pytest tests tests/build/test_hidden.py -q"),
                 {"tests/test_a.py": PY, "tests/build/test_hidden.py": PY})
    assert _ok(repo) == []
    # So does naming the un-recursed directory itself: nothing strictly below it is skipped.
    repo2 = _repo(tmp_path / "named-dir", _wf("python3 -m pytest tests tests/build -q"),
                  {"tests/test_a.py": PY, "tests/build/deep/test_hidden.py": PY})
    assert _ok(repo2) == []
    # `.` as the argument walks the whole tree, and skips the same segments.
    repo3 = _repo(tmp_path / "dot", _wf("python3 -m pytest . -q"), {"tests/test_a.py": PY, "dist/test_hidden.py": PY})
    assert _ok(repo3) == ["dist/test_hidden.py"]


def test_shell_suite_runner_walks_its_own_directories(tmp_path):
    """The norecursedirs rule is pytest's, not the shell runner's: tests/run-shell-suites.sh
    walks `git ls-files` under each directory it is given, so a suite below such a segment is
    genuinely run and must stay credited."""
    files = {"tests/run-shell-suites.sh": SH, "hooks/tests/build/test_h.sh": SH}
    repo = _repo(tmp_path, _wf("bash tests/run-shell-suites.sh hooks/tests"), files)
    assert _ok(repo) == []


def test_glob_does_not_cross_directories(tmp_path):
    repo = _repo(tmp_path, _wf("python3 -m pytest tests/*.py -q"), {"tests/test_a.py": PY, "tests/deep/test_b.py": PY})
    assert _ok(repo) == ["tests/deep/test_b.py"]


def test_working_directory_at_every_level(tmp_path):
    step = "        working-directory: pkg\n"
    repo = _repo(tmp_path, _wf("python3 -m pytest tests -q", step_extra=step), {"pkg/tests/test_p.py": PY})
    assert _ok(repo) == []
    job = "    defaults:\n      run:\n        working-directory: pkg\n"
    repo2 = _repo(tmp_path / "2", _wf("python3 -m pytest ../top tests -q", job_extra=job), {"pkg/tests/test_p.py": PY, "top/test_t.py": PY})
    assert _ok(repo2) == []


def test_dot_slash_is_normalised_but_node_ids_are_refused(tmp_path):
    repo = _repo(tmp_path, _wf("python3 -m pytest ./tests/test_a.py -q"), {"tests/test_a.py": PY})
    assert _ok(repo) == []
    repo2 = _repo(tmp_path / "2", _wf("python3 -m pytest tests/test_a.py::test_x -q"), {"tests/test_a.py": PY})
    assert ci_coverage.problems(repo2) == ["tests.yml/t: node id selects part of a file: tests/test_a.py::test_x"]


def test_absolute_interpreter_path_is_fine(tmp_path):
    repo = _repo(tmp_path, _wf("/usr/bin/python3 -m pytest tests -q"), {"tests/test_a.py": PY})
    assert _ok(repo) == []


def test_filtered_or_missing_pull_request_trigger_credits_nothing(tmp_path):
    for on in ("{schedule: [{cron: '0 0 * * *'}]}", "{pull_request: {paths: ['docs/**']}, push: {branches: [main]}}", "{pull_request: {branches: [main]}}"):
        repo = _repo(tmp_path / on.replace("/", "_").replace(" ", "")[:20], _wf("python3 -m pytest tests -q", on=on), {"tests/test_a.py": PY})
        assert ci_coverage.unwired(repo, {}) == ["tests/test_a.py"], on


def test_conditional_job_needs_and_step_credit_nothing(tmp_path):
    repo = _repo(tmp_path, _wf("python3 -m pytest tests -q", job_extra="    if: false\n"), {"tests/test_a.py": PY})
    assert ci_coverage.unwired(repo, {}) == ["tests/test_a.py"]
    yaml = ("name: t\non: [pull_request, push]\njobs:\n  gate:\n    runs-on: ubuntu-latest\n    if: false\n    steps: [{run: 'true'}]\n"
            "  t:\n    runs-on: ubuntu-latest\n    needs: gate\n    steps:\n      - run: python3 -m pytest tests -q\n")
    repo2 = _repo(tmp_path / "2", yaml, {"tests/test_a.py": PY})
    assert ci_coverage.unwired(repo2, {}) == ["tests/test_a.py"]
    repo3 = _repo(tmp_path / "3", _wf("python3 -m pytest tests -q", step_extra="        continue-on-error: true\n"), {"tests/test_a.py": PY})
    assert ci_coverage.unwired(repo3, {}) == ["tests/test_a.py"]


def test_commented_out_run_line_credits_nothing(tmp_path):
    yaml = _wf("echo nothing") + "      # - run: python3 -m pytest tests -q\n"
    repo = _repo(tmp_path, yaml, {"tests/test_a.py": PY})
    assert ci_coverage.unwired(repo, {}) == ["tests/test_a.py"]


def test_shell_operators_and_multiline_fail_closed(tmp_path):
    for run in ("true || python3 -m pytest tests", "python3 -m pytest tests || true", "exit 0; python3 -m pytest tests",
                "|\n          echo hi\n          python3 -m pytest tests"):
        repo = _repo(tmp_path / str(abs(hash(run))), _wf(run), {"tests/test_a.py": PY})
        assert ci_coverage.problems(repo) == ["tests.yml/t: a test step must be exactly one command"], run
        assert ci_coverage.unwired(repo, {}) == ["tests/test_a.py"], run


def test_narrowing_flags_and_addopts_fail_closed(tmp_path):
    for run in ("python3 -m pytest tests -k fast", "python3 -m pytest tests -kfast", "python3 -m pytest tests --deselect=tests/test_a.py::x",
                "python3 -m pytest tests --collect-only", "python3 -m pytest tests -m slow"):
        repo = _repo(tmp_path / str(abs(hash(run))), _wf(run), {"tests/test_a.py": PY})
        assert ci_coverage.problems(repo), run
    repo = _repo(tmp_path / "env", _wf("python3 -m pytest tests -q", env="env:\n  PYTEST_ADDOPTS: '-k x'\n"), {"tests/test_a.py": PY})
    assert ci_coverage.problems(repo) == ["tests.yml: PYTEST_ADDOPTS is set in the workflow"]


def test_unknown_options_fail_closed(tmp_path):
    """Only an allowlist of options is accepted; -h, --version, --override-ini and anything unknown is a problem."""
    for run in ("python3 -m pytest skills tests -h", "python3 -m pytest tests --version", "python3 -m pytest tests --override-ini=norecursedirs=slow",
                "python3 -m pytest tests -c other.ini", "python3 -m pytest tests --rootdir=x", "npx vitest run src --config other.ts"):
        repo = _repo(tmp_path / str(abs(hash(run))), _wf(run), {"tests/test_a.py": PY, "src/a.test.ts": TS})
        assert any("unsupported option" in p for p in ci_coverage.problems(repo)), run
        assert ci_coverage.unwired(repo, {}), run
    repo = _repo(tmp_path / "ok", _wf("python3 -m pytest tests -q -rs -x -p no:cacheprovider --tb=short --maxfail=3"), {"tests/test_a.py": PY})
    assert _ok(repo) == []


def test_pass_with_no_tests_is_refused(tmp_path):
    """--passWithNoTests lets a jest/vitest step exit 0 while running nothing at all; it must be
    an unsupported option like any other, not a silently allowed one."""
    repo = _repo(tmp_path, _wf("npx jest --passWithNoTests src"), {"src/a.test.js": TS})
    assert any("unsupported option" in p for p in ci_coverage.problems(repo))
    assert ci_coverage.unwired(repo, {}) == ["src/a.test.js"]


def test_a_shell_other_than_bash_credits_nothing(tmp_path):
    """`shell:` replaces the default bash invocation of a `run:`; a template like "echo {0}"
    runs echo on the script file, so the step passes while running no tests at all. It can be set
    on the step, on the job's defaults or on the workflow's defaults, and all three must fail
    closed on anything but bash."""
    step = _wf("python3 -m pytest tests -q", step_extra='        shell: "echo {0}"\n')
    job = _wf("python3 -m pytest tests -q", job_extra="    defaults:\n      run:\n        shell: pwsh\n")
    workflow = ("name: t\non: [pull_request, push]\ndefaults:\n  run:\n    shell: sh\njobs:\n  t:\n"
                "    runs-on: ubuntu-latest\n    steps:\n      - run: python3 -m pytest tests -q\n")
    for level, yaml in (("step", step), ("job defaults.run", job), ("workflow defaults.run", workflow)):
        repo = _repo(tmp_path / level.replace(" ", "_").replace(".", "_"), yaml, {"tests/test_a.py": PY})
        assert any(f"{level} shell is " in p for p in ci_coverage.problems(repo)), (level, ci_coverage.problems(repo))
        assert ci_coverage.unwired(repo, {}) == ["tests/test_a.py"], level
    # bash is the one accepted value, at every level: it is what a `run:` uses by default anyway.
    ok_step = _wf("python3 -m pytest tests -q", step_extra="        shell: bash\n")
    ok_job = _wf("python3 -m pytest tests -q", job_extra="    defaults:\n      run:\n        shell: bash\n")
    for name, yaml in (("step", ok_step), ("job", ok_job)):
        repo = _repo(tmp_path / f"ok-{name}", yaml, {"tests/test_a.py": PY})
        assert _ok(repo) == [], name
    # A step's own shell wins over a job default: bash on the step is credited despite pwsh above it.
    repo = _repo(tmp_path / "step-overrides-job",
                 _wf("python3 -m pytest tests -q", job_extra="    defaults:\n      run:\n        shell: pwsh\n",
                     step_extra="        shell: bash\n"), {"tests/test_a.py": PY})
    assert _ok(repo) == []


def test_conditional_needs_are_transitive(tmp_path):
    yaml = ("name: t\non: [pull_request, push]\njobs:\n  gate:\n    runs-on: ubuntu-latest\n    if: false\n    steps: [{run: 'true'}]\n"
            "  middle:\n    runs-on: ubuntu-latest\n    needs: gate\n    steps: [{run: 'true'}]\n"
            "  suite:\n    runs-on: ubuntu-latest\n    needs: middle\n    steps:\n      - run: python3 -m pytest tests -q\n")
    repo = _repo(tmp_path, yaml, {"tests/test_a.py": PY})
    assert ci_coverage.unwired(repo, {}) == ["tests/test_a.py"]


def test_missing_workflow_path_is_reported(tmp_path):
    repo = _repo(tmp_path, _wf("python3 -m pytest tests/a tests/gone -q"), {"tests/a/test_a.py": PY})
    assert ci_coverage.missing_workflow_paths(repo) == ["tests/gone"]


def test_exclusion_needs_a_reason_and_a_real_target(tmp_path):
    repo = _repo(tmp_path, _wf("python3 -m pytest tests/a -q"), {"tests/a/test_a.py": PY, "tests/b/test_b.py": PY, "docs/README.md": "x"})
    assert ci_coverage.unwired(repo, {"tests/b": "retired 2026-09-14"}) == []
    assert ci_coverage.stale_exclusions(repo, {"tests/b": "", "docs": "no tests here", "tests/vanished": "why"}) == ["docs", "tests/b", "tests/vanished"]


def test_untracked_test_file_is_invisible_by_design(tmp_path):
    repo = _repo(tmp_path, _wf("python3 -m pytest tests/a -q"), {"tests/a/test_a.py": PY})
    (repo / "tests" / "c").mkdir()
    (repo / "tests" / "c" / "test_c.py").write_text(PY)   # not git-added
    assert ci_coverage.unwired(repo, {}) == []


def test_nested_conftest_narrowing_key_is_flagged_at_any_depth(tmp_path):
    """A conftest.py need not sit at the repo root to narrow collection behind the checker's
    back; config_problems() must walk every tracked file, not just the root."""
    repo = _repo(tmp_path, _wf("python3 -m pytest tests -q"),
                 {"tests/test_a.py": PY, "tests/sub/deep/conftest.py": "collect_ignore_glob = ['test_*.py']\n"})
    found = ci_coverage.config_problems(repo)
    assert any("collect_ignore_glob" in p and "tests/sub/deep/conftest.py" in p for p in found), found


def test_conftest_collection_hook_or_pytest_plugins_is_flagged(tmp_path):
    """A conftest.py narrows collection through code as well as through an assignment: each hook
    below can drop a file, a directory or a whole subtree, and pytest_plugins pulls in a module
    that can define them elsewhere. The hook names ARE the claim (they are pytest's), so they are
    spelled out here rather than read back from the checker's own COLLECTION_HOOKS set, which
    would delete its own cases if someone narrowed that set."""
    bodies = {
        "pytest_ignore_collect": "def pytest_ignore_collect(collection_path, config):\n    return True\n",
        "pytest_collect_file": "def pytest_collect_file(file_path, parent):\n    return None\n",
        "pytest_collect_directory": "def pytest_collect_directory(path, parent):\n    return None\n",
        "pytest_collection_modifyitems": "def pytest_collection_modifyitems(config, items):\n    items[:] = []\n",
        "pytest_pycollect_makemodule": "def pytest_pycollect_makemodule(module_path, parent):\n    return None\n",
        "pytest_collection": "def pytest_collection(session):\n    return True\n",
        "pytest_load_initial_conftests": "def pytest_load_initial_conftests(early_config, parser, args):\n    args[:] = []\n",
        "pytest_plugins": "pytest_plugins = ['my_collection_plugin']\n",
    }
    for name, body in bodies.items():
        repo = _repo(tmp_path / name, _wf("python3 -m pytest tests -q"),
                     {"tests/test_a.py": PY, "tests/sub/conftest.py": body, "tests/sub/test_b.py": PY})
        found = ci_coverage.config_problems(repo)
        assert any(name in p and "tests/sub/conftest.py" in p for p in found), (name, found)
        # Without the guard the subtree is credited and nothing else reports it: unwired() is
        # empty here by design, so config_problems() is the only thing keeping the file honest.
        assert ci_coverage.unwired(repo, {}) == [], name
    # The repo-facing test is what a person sees go red, and it must name the file and the hook.
    repo = _repo(tmp_path / "repo-facing", _wf("python3 -m pytest tests -q"),
                 {"tests/test_a.py": PY, "tests/sub/conftest.py": bodies["pytest_ignore_collect"]})
    r = _run_repo_facing_test(repo)
    assert r.returncode != 0
    assert "tests/sub/conftest.py" in r.stdout and "pytest_ignore_collect" in r.stdout


def test_conftest_with_only_sys_path_insert_is_fine(tmp_path):
    """Only the listed keys are refused -- a conftest.py that does nothing but sys.path.insert
    (the shape a tracked conftest.py may use) must pass clean."""
    repo = _repo(tmp_path, _wf("python3 -m pytest tests -q"),
                 {"tests/test_a.py": PY, "tests/conftest.py": "import sys\nsys.path.insert(0, '.')\n"})
    assert ci_coverage.config_problems(repo) == []


def test_vitest_config_include_exclude_is_flagged(tmp_path):
    repo = _repo(tmp_path, _wf("npx vitest run src"),
                 {"src/a.test.ts": TS, "vitest.config.ts": "export default { test: { include: ['src/**/*.test.ts'] } }\n"})
    assert any("vitest.config.ts" in p for p in ci_coverage.config_problems(repo))


def test_package_json_jest_key_test_match_is_flagged(tmp_path):
    repo = _repo(tmp_path, _wf("npx jest src"),
                 {"src/a.test.js": TS, "package.json": '{"jest": {"testMatch": ["**/*.test.js"]}}'})
    found = ci_coverage.config_problems(repo)
    assert any("package.json" in p and "testMatch" in p for p in found), found


def _neutralize_exclusions(src: str, exclusions_src: str) -> str:
    """Replace the real EXCLUSIONS stanza with `exclusions_src`, so this proof does not depend on
    what the repo's own EXCLUSIONS dict currently holds. re.subn (not re.sub) so a reformatted stanza
    that stops matching is a loud failure here, not a silent no-op that runs the proof against
    the real dict."""
    new_src, n = re.subn(r"EXCLUSIONS: dict\[str, str\] = \{.*?\n\}", exclusions_src, src, count=1, flags=re.S)
    assert n == 1, "EXCLUSIONS stanza not found -- the proof would run against the real dict"
    return new_src


def test_exclusions_neutralization_fails_loudly_if_stanza_is_gone():
    """If the real stanza's text ever stops matching (a reformat, a rename), this must raise --
    not silently return the unmodified source and let the proof run against the real dict."""
    with pytest.raises(AssertionError, match="EXCLUSIONS stanza not found"):
        _neutralize_exclusions("no such stanza in this source", "EXCLUSIONS: dict[str, str] = {}")


def _run_repo_facing_test(repo: Path, exclusions_src: str = "EXCLUSIONS: dict[str, str] = {}") -> subprocess.CompletedProcess:
    """Copy the real checker + repo-facing test into the temp repo, with EXCLUSIONS replaced so
    this proof does not depend on what the repo's own EXCLUSIONS dict currently holds."""
    dst = repo / "tests"
    dst.mkdir(exist_ok=True)
    shutil.copy(HERE / "__init__.py", dst / "__init__.py")
    shutil.copy(HERE / "ci_coverage.py", dst / "ci_coverage.py")
    src = (HERE / "test_ci_covers_every_suite.py").read_text()
    src = _neutralize_exclusions(src, exclusions_src)
    (dst / "test_ci_covers_every_suite.py").write_text(src)
    _add_all(repo)
    return subprocess.run([sys.executable, "-m", "pytest", "tests/test_ci_covers_every_suite.py", "-q", "-p", "no:cacheprovider"],
                          cwd=repo, capture_output=True, text=True)


def test_repo_facing_test_goes_red_on_an_unwired_repo(tmp_path):
    repo = _repo(tmp_path, _wf("python3 -m pytest tests -q"), {"skills/x/test_x.py": PY})
    r = _run_repo_facing_test(repo)
    assert r.returncode != 0
    assert "skills/x/test_x.py" in r.stdout


def test_repo_facing_test_goes_green_on_a_wired_repo(tmp_path):
    repo = _repo(tmp_path, _wf("python3 -m pytest skills tests -q"), {"skills/x/test_x.py": PY})
    r = _run_repo_facing_test(repo)
    assert r.returncode == 0, r.stdout + r.stderr
