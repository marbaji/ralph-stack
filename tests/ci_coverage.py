"""CI coverage checker: every test FILE git tracks must be run by a step in an unconditional
pull-request job, or be excluded with a reason.

Credit comes only from three step shapes, each exactly one command:
  python3 -m pytest <paths...> [--ignore=P] [--ignore-glob=G] [other flags]
  npx vitest run <paths...>  |  npx jest <paths...>  |  vitest run ... | jest ...
  bash tests/run-shell-suites.sh <suite-dirs...>
Anything that cannot be read with certainty (shell operators, several commands, narrowing
flags, node ids, PYTEST_ADDOPTS, a `shell:` other than bash at any of the three levels,
filtered pull_request triggers, conditional jobs or needs) is reported by problems() and
credits nothing. Parsed with PyYAML.
"""
import fnmatch
import json
import posixpath
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SUITE_RUNNER = "tests/run-shell-suites.sh"
PY_TEST = re.compile(r"(^|/)(test_[^/]*\.py|[^/]*_test\.py)$")
SH_TEST = re.compile(r"(^|/)(test_[^/]*\.sh|test-[^/]*\.sh)$")
JS_TEST = re.compile(r"(^|/)[^/]*\.(test|spec)\.(js|jsx|ts|tsx|mjs|cjs|mts|cts)$")
KIND_OF = {"pytest": PY_TEST, "suite-runner": SH_TEST, "js": JS_TEST}
NARROWING_EXACT = {"--deselect", "--collect-only", "--last-failed", "--lf", "--sw", "--stepwise", "--co"}
NARROWING_PREFIX = ("-k", "-m")  # pytest allows a glued value: -kfast, -mslow
# Options a test step may carry. Anything else is a problem (fail closed): -h, --version,
# --override-ini, -c, --rootdir and every unknown flag would otherwise credit paths silently.
ALLOWED = {
    "pytest": {"-q", "-v", "-vv", "-x", "-s", "-rs", "-ra", "-rA", "-rf", "--no-header", "--strict-markers", "-W", "--tb", "--maxfail", "--durations", "-p"},
    "js": {"--reporter", "--silent", "--run"},  # --passWithNoTests is refused: it lets a step exit 0 running nothing
    "suite-runner": set(),
}
TAKES_VALUE = {"-p", "-W", "--tb", "--maxfail", "--durations", "--reporter"}
OPERATORS = re.compile(r"(&&|\|\||;|\||`|\$\()")
GLOB_CHARS = set("*?[")
# Config files, anywhere git tracks them, that can narrow which files pytest collects behind
# the checker's back. Only the listed keys are refused -- a conftest.py that does nothing but
# sys.path.insert must still pass.
PY_CONFIG_NAMES = {"pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "conftest.py"}
PY_CONFIG_KEYS = ("addopts", "norecursedirs", "python_files", "python_classes", "python_functions",
                   "testpaths", "collect_ignore", "collect_ignore_glob")
# A conftest.py narrows collection through code as well as through assignments: any of these
# hooks can drop a file, a directory or a whole subtree, and `pytest_plugins` pulls in a module
# that can define them elsewhere. Refused wherever a tracked conftest.py defines one.
COLLECTION_HOOKS = {"pytest_ignore_collect", "pytest_collect_file", "pytest_collect_directory",
                    "pytest_collection_modifyitems", "pytest_pycollect_makemodule",
                    "pytest_pycollect_makeitem", "pytest_collection", "pytest_load_initial_conftests"}
# pytest's default `norecursedirs`: it never recurses into a directory whose name matches one of
# these, so a test file below such a segment is NOT run by a step that merely names an ancestor
# directory. Credit is withheld for those files (fail closed); naming the file itself still
# credits it, because pytest collects a path given explicitly on the command line.
NORECURSEDIRS = ("*.egg", ".*", "_darcs", "build", "CVS", "dist", "node_modules", "venv", "{arch}")
# Same idea for JS: a vitest.config.*/jest.config.* or package.json "jest" key can narrow
# collection the same way pytest's addopts/testpaths can.
JS_CONFIG_KEYS = ("include", "exclude", "testMatch", "testPathIgnorePatterns", "testRegex", "roots")


@dataclass
class Step:
    workflow: str
    job: str
    runner: str
    paths: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    ignored_glob: list[str] = field(default_factory=list)  # --ignore-glob: fnmatch over the full path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def file_kind(path: str):
    for kind, rx in KIND_OF.items():
        if rx.search(path):
            return kind
    return None


def tracked_test_files(repo: Path) -> list[str]:
    files = [p for p in _git(repo, "ls-files", "-z").split("\0") if p]
    return sorted(p for p in files if file_kind(p))


def workflow_files(repo: Path) -> list[Path]:
    wf = repo / ".github" / "workflows"
    return sorted(wf.glob("*.yml")) + sorted(wf.glob("*.yaml")) if wf.is_dir() else []


def _pr_trigger_problem(doc: dict):
    """None when the workflow has an UNFILTERED pull_request trigger; else the reason."""
    on = doc.get("on", doc.get(True))  # PyYAML reads a bare `on:` key as the boolean True
    if isinstance(on, str):
        return None if on == "pull_request" else "no pull_request trigger"
    if isinstance(on, list):
        return None if "pull_request" in on else "no pull_request trigger"
    if isinstance(on, dict):
        if "pull_request" not in on:
            return "no pull_request trigger"
        pr = on["pull_request"] or {}
        bad = [k for k in ("paths", "paths-ignore", "branches", "branches-ignore", "types") if k in pr]
        return f"pull_request trigger is filtered by {bad}" if bad else None
    return "no pull_request trigger"


def _norm(p: str, cwd) -> str:
    if p.startswith("./"):
        p = p[2:]
    if cwd:
        p = posixpath.join(cwd, p)
    p = posixpath.normpath(p)
    return "" if p.startswith("..") else p


def _split_one_command(script: str):
    """The single argv of a test step, or None (with a reason) when it is not exactly one command."""
    lines = [l for l in script.splitlines() if l.strip() and not l.strip().startswith("#")]
    if len(lines) != 1 or OPERATORS.search(lines[0]):
        return None, "a test step must be exactly one command"
    try:
        return shlex.split(lines[0]), None
    except ValueError:
        return None, "unparseable quoting in test step"


def _classify(argv: list[str]):
    """(runner, paths_start) or (None, reason)."""
    head = posixpath.basename(argv[0])
    if head in ("python", "python3") and argv[1:3] == ["-m", "pytest"]:
        return "pytest", 3
    if head == "pytest":
        return "pytest", 1
    if head == "npx" and argv[1:2] in (["vitest"], ["jest"]):
        return "js", 3 if argv[2:3] == ["run"] else 2
    if head in ("vitest", "jest"):
        return "js", 2 if argv[1:2] == ["run"] else 1
    if head in ("bash", "sh"):
        if argv[1:2] != [SUITE_RUNNER]:
            return None, f"bash may only invoke {SUITE_RUNNER}"
        return "suite-runner", 2
    return None, None  # not a test command at all; ignored, not a problem


def _parse_args(args: list[str], cwd, st: Step, problems: list[str], tag: str):
    i = 0
    while i < len(args):
        a = args[i]
        opt = a.split("=", 1)[0]
        if opt in ("--ignore", "--ignore-glob"):
            val = a.split("=", 1)[1] if "=" in a else (args[i + 1] if i + 1 < len(args) else "")
            target = st.ignored_glob if opt == "--ignore-glob" else st.ignored
            target.append(_norm(val, cwd)); i += 0 if "=" in a else 1
        elif opt in NARROWING_EXACT or any(a.startswith(n) for n in NARROWING_PREFIX):
            problems.append(f"{tag}: narrowing flag {a}")
            if a in ("-k", "-m", "--deselect") and i + 1 < len(args):
                i += 1
        elif a.startswith("-") or a.startswith("$"):
            if opt not in ALLOWED[st.runner]:
                problems.append(f"{tag}: unsupported option {a}")
            if opt in TAKES_VALUE and "=" not in a and i + 1 < len(args):
                i += 1
        elif "::" in a:
            problems.append(f"{tag}: node id selects part of a file: {a}")
        else:
            st.paths.append(_norm(a, cwd))
        i += 1


def _analyse(repo: Path):
    steps: list[Step] = []
    problems: list[str] = []
    for wf in workflow_files(repo):
        doc = yaml.safe_load(wf.read_text()) or {}
        if "PYTEST_ADDOPTS" in (doc.get("env") or {}):
            problems.append(f"{wf.name}: PYTEST_ADDOPTS is set in the workflow")
            continue
        pr_problem = _pr_trigger_problem(doc)
        jobs = doc.get("jobs") or {}
        wf_defaults = ((doc.get("defaults") or {}).get("run") or {})
        wf_cwd = wf_defaults.get("working-directory")
        wf_shell = wf_defaults.get("shell")
        conditional = {n for n, j in jobs.items() if not isinstance(j, dict) or "if" in j or j.get("continue-on-error")}
        # transitive: a job that needs a job that needs a conditional job is skipped by GitHub too
        changed = True
        while changed:
            changed = False
            for n, j in jobs.items():
                if n in conditional or not isinstance(j, dict):
                    continue
                needs = j.get("needs") or []
                needs = [needs] if isinstance(needs, str) else list(needs)
                if any(x in conditional for x in needs):
                    conditional.add(n); changed = True
        for job_name, job in jobs.items():
            if job_name in conditional:
                continue
            if "PYTEST_ADDOPTS" in (job.get("env") or {}):
                problems.append(f"{wf.name}/{job_name}: PYTEST_ADDOPTS is set on the job"); continue
            job_defaults = ((job.get("defaults") or {}).get("run") or {})
            job_cwd = job_defaults.get("working-directory") or wf_cwd
            # A `shell:` replaces the default bash invocation, and a template like "echo {0}"
            # turns a credited `run:` into a no-op. The step's own key wins over the job's
            # defaults, which win over the workflow's.
            if job_defaults.get("shell") is not None:
                job_shell, job_shell_level = job_defaults["shell"], "job defaults.run"
            else:
                job_shell, job_shell_level = wf_shell, "workflow defaults.run"
            for step in job.get("steps") or []:
                if not isinstance(step, dict) or "run" not in step or "if" in step or step.get("continue-on-error"):
                    continue
                if "PYTEST_ADDOPTS" in (step.get("env") or {}):
                    problems.append(f"{wf.name}/{job_name}: PYTEST_ADDOPTS is set on a step"); continue
                tag = f"{wf.name}/{job_name}"
                script = str(step["run"])
                argv, why = _split_one_command(script)
                if argv is None:
                    if re.search(r"\b(pytest|vitest|jest|run-shell-suites)\b", script):
                        problems.append(f"{tag}: {why}")
                    continue
                runner, start = _classify(argv)
                if runner is None:
                    if start:
                        problems.append(f"{tag}: {start}")
                    continue
                shell, level = (step["shell"], "step") if "shell" in step else (job_shell, job_shell_level)
                if shell is not None and str(shell) != "bash":
                    problems.append(f"{tag}: {level} shell is {str(shell)!r}, not bash; the step's run: may not execute as written")
                    continue
                if pr_problem:
                    problems.append(f"{tag}: {pr_problem}")
                    continue
                n = len(problems)
                st = Step(workflow=wf.name, job=job_name, runner=runner)
                cwd = step.get("working-directory") or job_cwd
                _parse_args(argv[start:], cwd, st, problems, tag)
                if len(problems) == n:
                    steps.append(st)
    return steps, sorted(set(problems))


def test_steps(repo: Path) -> list[Step]:
    return _analyse(repo)[0]


def problems(repo: Path) -> list[str]:
    return _analyse(repo)[1]


def _segment_match(path: str, pattern: str) -> bool:
    """fnmatch per path segment, so `*` never crosses a `/`."""
    ps, ws = path.split("/"), pattern.split("/")
    return len(ps) == len(ws) and all(fnmatch.fnmatchcase(a, b) for a, b in zip(ps, ws))


def _unreachable_by_recursion(f: str, under: str) -> bool:
    """True when a directory segment strictly below `under`, on the way down to f, is one pytest
    never recurses into. `under` is "." for the whole tree. The file's own basename is not a
    directory and is never tested."""
    rel = f if under == "." else f[len(under) + 1:]
    return any(fnmatch.fnmatchcase(seg, pat) for seg in rel.split("/")[:-1] for pat in NORECURSEDIRS)


def _expand(p: str, files: list[str], *, pytest_recursion: bool = False) -> list[str]:
    """The files a positional argument names. `pytest_recursion` applies pytest's default
    norecursedirs to what a DIRECTORY argument reaches; it is off for --ignore, for exclusions
    and for the shell-suite runner, which walk their targets themselves."""
    if not p:
        return []
    if GLOB_CHARS & set(p):
        return [f for f in files if _segment_match(f, p)]
    if p == ".":
        return [f for f in files if not (pytest_recursion and _unreachable_by_recursion(f, "."))]
    return [f for f in files
            if f == p or (f.startswith(p + "/") and not (pytest_recursion and _unreachable_by_recursion(f, p)))]


def _glob_hits(p: str, path: str) -> bool:
    """pytest's own --ignore-glob semantics: fnmatch over the WHOLE path, so `*` crosses `/`
    (unlike a positional glob or --ignore, which stay segment-bounded via _expand/_segment_match).
    pytest matches the pattern against every collected path, DIRECTORIES included, so a pattern
    matching an ancestor directory excludes everything below it."""
    parts = path.split("/")
    return any(fnmatch.fnmatchcase("/".join(parts[:i]), p) for i in range(1, len(parts) + 1))


def _expand_ignore_glob(p: str, files: list[str]) -> list[str]:
    if not p:
        return []
    return [f for f in files if _glob_hits(p, f)]


def covered_files(repo: Path) -> set[str]:
    files = tracked_test_files(repo)
    cov: set[str] = set()
    for st in test_steps(repo):
        kind_files = [f for f in files if file_kind(f) == st.runner]
        named: set[str] = set()
        for p in st.paths:
            named |= set(_expand(p, kind_files, pytest_recursion=st.runner == "pytest"))
        for p in st.ignored:
            named -= set(_expand(p, kind_files))
        for p in st.ignored_glob:
            named -= set(_expand_ignore_glob(p, kind_files))
        cov |= named
    return cov


def unwired(repo: Path, exclusions: dict) -> list[str]:
    files = tracked_test_files(repo)
    cov = covered_files(repo)
    excluded: set[str] = set()
    for p in exclusions:
        excluded |= set(_expand(p, files))
    return sorted(f for f in files if f not in cov and f not in excluded)


def missing_workflow_paths(repo: Path) -> list[str]:
    missing = set()
    all_files = None
    for st in test_steps(repo):
        for p in st.paths + st.ignored:
            if GLOB_CHARS & set(p):
                all_files = all_files if all_files is not None else _git(repo, "ls-files").splitlines()
                if not any(_segment_match(f, p) for f in all_files):
                    missing.add(p)
            elif not (repo / p).exists():
                missing.add(p)
        for p in st.ignored_glob:
            all_files = all_files if all_files is not None else _git(repo, "ls-files").splitlines()
            if not any(_glob_hits(p, f) for f in all_files):
                missing.add(p)
    return sorted(missing)


def stale_exclusions(repo: Path, exclusions: dict) -> list[str]:
    files = tracked_test_files(repo)
    return sorted(p for p, reason in exclusions.items() if not str(reason).strip() or not _expand(p, files))


def config_problems(repo: Path) -> list[str]:
    """Tracked config files, at ANY depth, that can narrow test collection behind the checker's
    back: a pytest.ini / pyproject.toml / setup.cfg / tox.ini / conftest.py setting addopts,
    norecursedirs, python_files/classes/functions, testpaths, collect_ignore or
    collect_ignore_glob; a conftest.py defining a collection hook (COLLECTION_HOOKS) or
    assigning pytest_plugins, which narrows collection through code rather than through a key;
    or a vitest.config.* / jest.config.* / package.json "jest" key setting include, exclude,
    testMatch, testPathIgnorePatterns, testRegex or roots. Only those are refused -- a
    conftest.py that does nothing but sys.path.insert passes clean."""
    problems: list[str] = []
    py_key_rx = re.compile(rf"^\s*({'|'.join(PY_CONFIG_KEYS)})\s*=", re.M)
    hook_rx = re.compile(r"^\s*(?:async\s+)?def\s+(pytest_\w+)\s*\(", re.M)
    plugins_rx = re.compile(r"^\s*pytest_plugins\s*(?::[^=\n]+)?=", re.M)
    js_key_rx = re.compile(rf"\b({'|'.join(JS_CONFIG_KEYS)})\b\s*[:=]")
    for rel in _git(repo, "ls-files").splitlines():
        if not rel:
            continue
        name = posixpath.basename(rel)
        path = repo / rel
        if name in PY_CONFIG_NAMES:
            text = path.read_text()
            hit = py_key_rx.search(text)
            if hit:
                problems.append(f"{rel} sets {hit.group(1)}; collection must be driven by the workflow's named paths only")
            if name == "conftest.py":
                for hook in sorted({m.group(1) for m in hook_rx.finditer(text)} & COLLECTION_HOOKS):
                    problems.append(f"{rel} defines {hook}; collection must be driven by the workflow's named paths only")
                if plugins_rx.search(text):
                    problems.append(f"{rel} sets pytest_plugins; collection must be driven by the workflow's named paths only")
        elif name.startswith("vitest.config.") or name.startswith("jest.config."):
            hit = js_key_rx.search(path.read_text())
            if hit:
                problems.append(f"{rel} sets {hit.group(1)}; JS collection must be driven by the workflow's named paths only")
        elif name == "package.json":
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                data = {}
            jest_cfg = data.get("jest") if isinstance(data, dict) else None
            if isinstance(jest_cfg, dict):
                bad = [k for k in JS_CONFIG_KEYS if k in jest_cfg]
                if bad:
                    problems.append(f"{rel} 'jest' key sets {bad}; JS collection must be driven by the workflow's named paths only")
    return sorted(problems)
