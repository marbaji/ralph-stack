# Phase 0 Spike Notes — ralphex 0.27.2

**Date:** 2026-04-18
**Ralphex version:** `v0.27.2-9fd2f40-20260416T233117`
**Install:** `brew install umputun/apps/ralphex` → `/opt/homebrew/bin/ralphex`
**Codex CLI:** `codex-cli 0.118.0` at `/opt/homebrew/bin/codex` (pre-existing)

---

## Invocation

Actual CLI shape (differs from plan assumption):

```
ralphex [OPTIONS] [plan-file]
```

NO `run` subcommand. The plan must be passed as a positional arg. Plans are discovered by default from `docs/plans/` (configurable via `plans_dir`).

**Plan impact:** `src/ralph_stack/runner.py::start()` must invoke `ralphex [plan-file]`, not `ralphex run [plan-file]`.

## Model Selection

Models are passed via `--task-model=opus:high` (not `--model=opus`). Effort levels: `low | medium | high | xhigh | max`. Also configurable in `.ralphex/config` via `task_model =` and `review_model =`.

## Claude Code Invocation (critical for detector)

Ralphex spawns Claude Code with this default command line (from `.ralphex/config` comments):

```
claude --dangerously-skip-permissions --output-format stream-json --verbose
```

**Implication:** Ralphex uses Claude Code's native `stream-json` output. Each iteration spawns a **fresh** Claude session, which writes a session JSONL to the standard Claude Code location:

```
~/.claude/projects/<hashed-cwd-path>/<session-uuid>.jsonl
```

The `<hashed-cwd-path>` is Claude Code's deterministic slugification of the project's absolute path (e.g., `-tmp-ralph-smoke`).

## Iteration Boundaries

**Ralphex's fresh-context rotation = new Claude session per iteration.** Detection signals:

1. **New JSONL file appears** in `~/.claude/projects/<hashed-cwd>/` → iteration started
2. **Completion signal:** ralphex's task prompt instructs Claude to emit `<<<RALPHEX:ALL_TASKS_DONE>>>` when the plan is fully done
3. **Progress file:** ralphex writes a per-plan progress log (path templated as `{{PROGRESS_FILE}}` in `.ralphex/prompts/task.txt`; exact resolved path confirmable only via live run — candidates: `.ralphex/progress/<plan>.md` or a timestamped file under `.ralphex/runs/`)

## Transcript Schema (stream-json)

Since ralphex uses Claude Code's native `--output-format stream-json`, the transcript is Claude Code's JSONL (not a ralphex-specific schema). Events of interest for our detector:

| Event type | What it means |
|---|---|
| `{"type": "user", ...}` | User/system turn |
| `{"type": "assistant", "message": {...}}` | Assistant turn; contains `content` blocks including `tool_use` |
| `content[].type == "tool_use"` | Tool call (Write, Edit, Bash, etc.) with `input.file_path` |
| `content[].type == "tool_result"` | Tool result; may contain `is_error: true` |

**Plan impact on Phase 3.1 (`src/ralph_stack/transcript.py`):**

Our synthetic fixture used a flat `{"type": "iteration_start", ...}` / `{"type": "iteration_end", ...}` schema with explicit iteration numbers. The real Claude Code JSONL has no iteration markers — the **iteration boundary is the file boundary** (one JSONL file per ralphex iteration, due to fresh-context rotation).

The Phase 3 detector logic is schema-agnostic: it operates on `Iteration` dataclass instances. We need a thin adapter in Phase 7 (`transcript_source.py` in the plan) that:

1. Watches `~/.claude/projects/<hashed-cwd>/` for new `.jsonl` files (iteration boundary)
2. For each new file, parses Claude Code's stream-json format and builds an `Iteration` with:
   - `number` = monotonic counter (or sequence-by-mtime)
   - `files_written` = union of `tool_use.input.file_path` where tool is Write/Edit/MultiEdit
   - `errors` = messages from `tool_result` blocks where `is_error == true`
   - `checkboxes_flipped` = count of `[x]` added to the plan file between iteration start/end (git-diff of plan file OR count in that iteration's Edit tool_use on the plan file)

The existing `parse_iterations()` in `transcript.py` can stay as a reference/test helper (consuming the synthetic schema). A **new adapter** in Phase 7 produces `Iteration` objects from real Claude stream-json.

## Model Override Strategy

**Plan's Strategy A** (PreToolUse hook + `next-iter-model.txt`) is NOT the cleanest path. Ralphex sets `--task-model=` once at startup and doesn't re-read it mid-run.

**Recommended: Strategy D (claude_command override)** — new, not in original plan:

1. Write a wrapper script `~/.local/bin/claude-ralph-wrapper.sh` that:
   - Reads `./ralph/next-iter-model.txt` (if exists)
   - Invokes `claude --model <override> "$@"` (or falls back to no override)
   - Clears the override file after one use
2. Point ralphex at it via `.ralphex/config`: `claude_command = claude-ralph-wrapper.sh`

This intercepts every Claude invocation ralphex makes (one per iteration due to fresh context) and swaps the model based on the one-shot override. No PreToolUse hook needed, no ralphex modification needed.

**Codex escalation is separate** — when we escalate, we don't swap Claude's model; we swap the EXECUTOR. That's a bigger change since ralphex's `codex_command` is only used during external review, not task execution. Options:

- (i) Accept that "escalate to Codex" means ending the ralphex process gracefully, running one Codex iteration via direct `codex exec` call, then resuming ralphex → messy handoff
- (ii) Simpler: treat "escalate to Codex" as a Claude model swap only (use `claude --model claude-opus-4-6` for default, swap to a different Claude variant when stuck). Agrim's article says Codex-the-tool, but the spirit is "different reasoning surface" which Opus-variant swaps may satisfy
- (iii) Full fidelity: when escalating, pause ralphex (SIGSTOP), invoke `codex exec` directly against the plan, then SIGCONT ralphex. Needs coordination on plan file state.

**Decision required before Phase 7:** which escalation semantics. This is a **spec-level open question** — flagging here for user review.

## Worktree Handling

Ralphex has built-in `--worktree` flag and `use_worktree` config. If we rely on this, ralph-stack doesn't need to duplicate worktree logic. Current plan's Phase 7/8 assume ralph-stack handles worktree — **re-delegate to ralphex's `--worktree` flag**.

## External Review Hook

Ralphex supports `external_review_tool = custom` with `custom_review_script = <path>`. The script receives a prompt file path as arg, outputs findings to stdout, and must emit `<<<RALPHEX:CODEX_REVIEW_DONE>>>` to signal completion.

**Possibly useful** as an out-of-band channel for ralph-stack to inject detector decisions, but for now we're sticking to pre-task intervention (claude_command wrapper) rather than review hook injection.

## Codex Invocation

```bash
codex exec "<prompt>"        # one-shot
codex --version              # confirms installed: 0.118.0
```

Ralphex uses `codex_command = codex` and `codex_model = gpt-5.4` by default. Sandbox is `read-only` by default (safe).

For ralph-stack's guardrail-drafting step (Phase 6's `draft_guardrail_rules`), we're currently using `claude --model claude-opus-4-6 -p <prompt>` which is fine — doesn't touch Codex.

## What still needs a live smoke test

Not blocking Phase 7+ drafting, but required for Phase 13 dogfood:

1. **Exact progress-file path** (candidate paths listed above — confirm with live run + inspection of `.ralphex/`)
2. **Iteration-start detection latency** — how long after spawning does the new JSONL file appear? (affects the runner's `tick()` polling interval)
3. **`<<<RALPHEX:ALL_TASKS_DONE>>>` placement** — is it in the JSONL as an assistant text block, or only in ralphex's own stdout? Determines whether our detector consuming JSONL can see the completion signal vs. needing to watch the ralphex subprocess stdout too
4. **Concurrent-run safety** — can two ralphex processes run against different plans in different cwd's without clobbering each other's Claude session directories? (Claude Code hashes by cwd, so probably yes)

These are Phase 13 tasks.

---

## Summary of Plan Deltas

| Area | Plan assumption | Reality | Fix |
|---|---|---|---|
| Install | `brew install ralphex` | `brew install umputun/apps/ralphex` | Update plan Phase 0 (done, via this note) |
| Invocation | `ralphex run <plan>` | `ralphex <plan>` | Phase 7 runner.py line referencing `"run"` |
| Model flag | `--model` | `--task-model` | Phase 7 runner + any hook tests |
| Model override | PreToolUse hook | `claude_command` wrapper | Phase 10 (was PreToolUse hook → becomes wrapper script) |
| Worktree | ralph-stack handles | ralphex native `--worktree` | Phase 7/8 simplify; delegate to ralphex |
| Transcript schema | Custom iteration events | Claude Code stream-json | Phase 7 adapter needed (not blocking Phase 3 unit tests) |
| Codex escalation | Direct Codex exec mid-loop | Open question (see above) | Raise to user before Phase 7 |

None of these invalidate Phases 1–6 work. Pure-Python core is schema-agnostic and remains correct.

---

## Decisions (2026-04-18, after spike review)

**Decision 1: Model-override mechanism — Strategy D (claude_command wrapper).**

- Write `scripts/claude-ralph-wrapper.sh` in the ralph-stack package
- Wrapper reads `./ralph/next-iter-model.txt`, prepends `--model` to real `claude` call, clears the override file after one use
- Set `.ralphex/config: claude_command = /absolute/path/to/claude-ralph-wrapper.sh` during `ralph-stack run` startup

**Decision 2: "Escalate to Codex" semantics — Option (ii) Claude-variant swap.**

Mid-loop escalation swaps Claude effort level, not executor. Specifically:

| Detector decision | What the wrapper actually invokes |
|---|---|
| `next_model = "opus"` (default / handback) | `claude --model opus` (no effort override, uses ralphex's configured default) |
| `next_model = "codex"` (escalate) | `claude --model opus:max` |

Rationale:
- Real Codex CLI mid-loop would require pausing/resuming ralphex with plan-file state handoff — messy
- Opus-at-max-effort gives a different reasoning surface (matches Agrim's spirit)
- Ralphex's built-in checkpoint Codex review still fires at end of run (unchanged)
- Internal state/detector code keeps using `"codex"` as the string label — only the wrapper script translates

If dogfood shows Opus-at-max isn't enough to unstick, upgrade to Strategy (i) (real Codex with SIGSTOP/SIGCONT) in a later iteration. Not blocking v0.1.

**Downstream impact on remaining phases:**

- **Phase 7 runner.py** — invoke `ralphex <plan-file>` (no `run` subcommand). Write `.ralphex/config` override for `claude_command` on start. Delegate worktree to ralphex's `--worktree`.
- **Phase 7 transcript_source.py** — tail `~/.claude/projects/<hashed-cwd>/` for new `.jsonl` files, parse Claude Code stream-json → `Iteration` adapter.
- **Phase 10 hook script** — becomes `scripts/claude-ralph-wrapper.sh` (Bash) rather than a PreToolUse Python hook. Simpler.
- **All Phases 1–6 unchanged.**
