# ralph-stack

A CLI wrapper around [ralphex](https://ralphex.com) that adds a structured human-review gate on top of the "ralph" autonomous coding loop.

`ralph-stack run plan.md` executes a markdown plan end-to-end without human input, then produces a debriefable exit artifact (`ralph/morning-report.md`) so you can triage what happened and decide what to do next.

## Why another ralph

"Ralph" (from Geoffrey Huntley, [ghuntley.com/ralph](https://ghuntley.com/ralph/)) is a bash-loop pattern: an agent runs against a plan file with fresh context every iteration, using the filesystem + git as memory instead of a conversation. Several implementations exist already:

| Implementation | What it does | Where ralph-stack differs |
|---|---|---|
| [ralphex](https://github.com/umputun/ralphex) (umputun) | The core loop in Go. Stateless iterations, plan-driven, moves plan to `completed/` on success. | ralph-stack wraps ralphex and adds a review/exit layer — it does NOT re-implement the loop. |
| [ralph-wiggum-cursor](https://github.com/agrimsingh/ralph-wiggum-cursor) (Agrim Singh) | Cursor port. Adds stream parsing, token tracking, gutter detection. | Targets Cursor, not Claude Code. Ralph-stack targets Claude Code (via ralphex). |
| [Ralph Playbook](https://claytonfarr.github.io/ralph-playbook/) (Clayton Farr) | A set of conventions + prompts, no tooling. | Ralph-stack is actual tooling. |
| Raw ralphex | You read `.ralphex/progress/*.txt` yourself after a run. | Ralph-stack generates `morning-report.md`, tracks stuck-state, renders combined guardrails, and exposes a `/ralph-review` skill for post-run triage. |

**Use ralph-stack if:**
- You want ralph's stateless-iteration pattern.
- You want to be able to walk away from a run and come back to a readable status artifact.
- You want per-project + global guardrails rendered together for each run.
- You're on Claude Code (ralph-stack delegates execution to ralphex, which wraps `claude`).

**Use something else if:**
- You're on Cursor → use ralph-wiggum-cursor.
- You want the minimal raw loop with no wrapper → use ralphex directly.

## Core concepts

### What comes from ralph canon

These are **not** ralph-stack inventions — they're how "ralph" works, as described by Huntley and Agrim:

- **Stateless iterations.** Each iteration spawns a fresh Claude Code session. No conversation memory leaks across iterations. Source: [ralphex.com](https://ralphex.com/) — *"Fresh Context: Each task executes in a new Claude session."*
- **Plan as single source of truth.** The plan markdown file with GFM checkboxes is what survives rotations. Source: [Agrim Singh, "Ralph For Idiots"](https://x.com/agrimsingh/status/2010412150918189210) — *"The memory is not the chat. The memory is the filesystem + git."*
- **Guardrails file as append-only memory.** When the loop makes a repeat mistake, write a rule into `guardrails.md` so the next iteration sees it. Source: Agrim, same post — *"the same mistake never happens twice."*
- **Plan moves to `completed/` on success.** Completed plans are archived under `docs/plans/completed/`. Source: [ralphex.com](https://ralphex.com/).

### What ralph-stack adds on top

- **`ralph/morning-report.md`** — exit artifact summarizing status, checkbox count, iterations, branch. Readable by a human after the run.
- **`ralph/stuck-state.json`** — detector state across escalations.
- **`ralph/combined-guardrails.md`** — per-project + global guardrails rendered into one file per run, with unverified drafts flagged.
- **Three-gate review pipeline** (Claude review 0 with 5 sub-agents, Claude review 1 with 2 sub-agents, external Codex review) — ralphex's native review hooks, configured by ralph-stack.
- **Escalation model swap** — when the detector sees thrash, the wrapper script swaps to a higher-effort Claude model for the next iteration.
- **`/ralph-review` skill** — post-run debrief that reads morning-report, flags unverified guardrail drafts, and recommends the next action.

## Install

```sh
brew install umputun/apps/ralphex    # prerequisite
./install.sh                          # installs ralph-stack into .venv + $PATH
```

Requires `claude` (Claude Code CLI) and `codex` (for ralphex's external-review gate).

## Commands

```sh
ralph-stack init [plan.md]       # scaffold ralph/ dir + per-project guardrails
ralph-stack run  plan.md         # run the plan to completion (blocks)
ralph-stack resume               # resume from last stuck-state.json
ralph-stack stop                 # stop the currently-running orchestrator
ralph-stack status               # one-shot KV dump of stuck-state (mid-run peek)
ralph-stack debrief              # read-only 4-section post-run summary
```

After a run completes, run `ralph-stack debrief` for a quick read-only summary, then invoke `/ralph-review` for agent-assisted bug triage and optional follow-up-plan drafting.

## Runtime artifacts (`./ralph/`)

- `morning-report.md` — status + recommended next action (written at exit)
- `stuck-state.json` — detector state (iteration, model, escalations)
- `combined-guardrails.md` — rendered guardrails (per-project + global)
- `next-iter-model.txt` — one-shot model override for the next iteration (cleared after read)
- `../.ralphex/progress/progress-<plan>.txt` — ralphex's per-plan progress log (iteration narratives)

## Post-run workflow

1. **`ralph-stack debrief`** — read-only. Prints a 4-section summary: status, what happened (tail of progress log if not COMPLETE), unverified guardrail drafts, and suspect-flag heuristics for known orchestrator bugs. Deterministic, no LLM.
2. **`/ralph-review`** — agent layer on top. Interprets the suspect flags, classifies bugs (orchestrator vs deliverable), and offers to draft a surgical corrective follow-up plan (`plan_<date>-<prev>-fixups.md`) with preview + reasoning before writing. See `/Users/mohannadarbaji/.claude/skills/ralph-review/README.md` for the doctrine.
3. **Orchestrator bugs** (bugs in ralph-stack itself): fix live on the ralph-stack repo. Write a regression test, commit, then launch the next run.
4. **Deliverable bugs** (bugs in the code ralph produced): **do not hand-fix between runs.** Use the follow-up plan. The original completed plan stays in `plans/completed/` untouched. Follows Huntley's "forward ralph loop" pattern ([ghuntley.com/loop](https://ghuntley.com/loop/)).
5. **Pattern bugs** (ralph keeps getting the same thing wrong): fix the bug via follow-up plan AND add a rule to `tasks/lessons.md` or promote it into `combined-guardrails.md` so the next run doesn't repeat the mistake.

## Plan immutability

Don't edit a completed plan. If the plan was wrong and needs restructuring mid-run: `ralph-stack stop`, edit the plan, `ralph-stack run` — ralph picks up from the current checkbox state (no duplicate work because it just reads the file).

Post-completion corrections go in a new plan file (`plan_<date>-<prev-name>-fixups.md`), never by editing `plans/completed/`.

## Orchestrator bug log

Known orchestrator bugs live under `docs/superpowers/specs/spec_*-ralph-orchestrator-bugs.md`. New bugs surfaced during a run's debrief get appended there before the next launch.

## Sources

- [Geoffrey Huntley — Ralph Wiggum as a software engineer](https://ghuntley.com/ralph/) (the original)
- [Geoffrey Huntley — everything is a ralph loop](https://ghuntley.com/loop/) (source of the "forward ralph loop" term)
- [Agrim Singh — Ralph For Idiots](https://x.com/agrimsingh/status/2010412150918189210)
- [ralphex (umputun/ralphex)](https://github.com/umputun/ralphex) — the loop ralph-stack wraps
- [ralphex.com](https://ralphex.com/) — landing page
- [ralph-wiggum-cursor (agrimsingh)](https://github.com/agrimsingh/ralph-wiggum-cursor) — Cursor port
- [The Ralph Playbook (Clayton Farr)](https://claytonfarr.github.io/ralph-playbook/) — convention notes

## Spec / design notes

See `SPIKE-NOTES.md` for the Phase 0 spike that confirmed ralphex's CLI shape, model-override mechanism, and escalation semantics for v0.1.
