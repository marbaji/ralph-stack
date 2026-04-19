# ralph-stack

Autonomous markdown-plan execution for Claude Code. Write a plan with checkboxes, run `ralph-stack run plan.md`, walk away. The tool loops Claude against the plan until every box is checked, then leaves a readable exit report so you can triage what happened.

---

## What ralph is

Long LLM sessions forget things. Context fills up, memory drifts, the agent wanders. The usual fix is more supervision. Ralph takes a different approach: **stop treating the conversation as memory. Make the filesystem the memory.**

The pattern, originally from [Geoffrey Huntley](https://ghuntley.com/ralph/):

```
┌──────────────────────────────────────────┐
│  plan.md        the task list, checkboxes│
│  guardrails.md  rules the loop must obey │
│  git            history of every change  │
└──────────────────────────────────────────┘
                      ▲
         reads/writes │
                      ▼
        ┌─────────────────────────┐
        │  Fresh agent session    │  new every iteration,
        │  one iteration          │  no chat memory
        └─────────────────────────┘
                      │
                      ▼
               all boxes checked?
                │           │
                no          yes ──▶ done
                │
                └──▶ loop
```

Each iteration reads the plan fresh, does one checkbox's worth of work, commits, exits. No accumulated confusion.

Three concepts to anchor on:

- **The plan.** A markdown file with GitHub-Flavored-Markdown checkboxes (`- [ ]` and `- [x]`). Flipped boxes are the only state that survives across iterations.
- **Guardrails.** A second markdown file the loop reads at the start of every iteration — a list of rules it must obey (e.g. *"never delete migrations"*, *"always run tests before committing"*, *"don't touch the auth middleware"*). When the loop makes the same mistake twice, you write a rule; the filesystem survives the agent's memory reset, so the next iteration sees it.
- **Stateless iterations.** Each iteration spawns a fresh agent session. No chat memory, no context bleed — only what the filesystem carries forward.

Canonical ralph is a shell one-liner:

```sh
while :; do cat prompt.md | claude-code; done
```

That proves the idea. It's not enough to actually use. The rest of this README is about what's been built on top, and what's still missing.

(Agrim Singh's [Ralph For Idiots](https://x.com/agrimsingh/status/2010412150918189210) is the clearest walkthrough of the core rules.)

---

## Prior work

Two serious implementations already exist:

- **[ralphex](https://github.com/umputun/ralphex)** (umputun, Go, targets Claude Code)
- **[ralph-wiggum-cursor](https://github.com/agrimsingh/ralph-wiggum-cursor)** (Agrim Singh, Bash, targets Cursor)

### What both already have

- The core loop — stateless iterations, fresh agent session each time.
- Markdown plan with GFM checkboxes as input.
- A stream parser that reads the agent's output and surfaces errors / progress.
- Implicit resume — re-run, the loop picks up from the first unchecked box.
- `Ctrl+C` to stop.

### What only ralphex has

A **four-phase review pipeline per plan**: task execution with validation commands → five parallel Claude reviewers (quality / implementation / testing / simplification / docs) → external review via Codex (or a custom script) → two Claude agents for critical + major issues. Plus:

- **Plan archival.** Completed plans move to `completed/` automatically.
- **Pluggable agent providers.** Claude Code is primary; Cursor / Copilot / Codex supported via wrapper scripts.
- **Web dashboard.** `--serve` exposes a live progress UI on localhost:8080.
- **Stalemate detection during review.** `--review-patience=N` halts the review loop if no commits happen for N rounds.
- **Docker wrappers**, AWS Bedrock provider, interactive plan creation (`--plan`), git worktree isolation (`--worktree`).

### What only ralph-wiggum-cursor has

- **First-class `guardrails.md`.** Read at the start of every iteration. The agent writes lessons back to it as it learns.
- **Token tracking.** Estimates the running token count in real time (prompt + reads + writes + assistant output). WARNs at 70k, ROTATEs to a new session at 80k.
- **Gutter detection** — thrash detection on the task phase. Halts when (a) the same shell command fails 3×, (b) the same file is written 5× in 10 minutes, or (c) the agent emits `<ralph>GUTTER</ralph>`.
- **Rate-limit backoff.** On 429 / 5xx / timeouts, exponential backoff from 15 s to 120 s with jitter, then retry.
- **Parallel worktrees.** `--parallel` runs N tasks in isolated `.ralph-worktrees/<run_id>-jobN/` dirs, auto-merges branches, optionally opens one PR.
- **Task groups.** `<!-- group: N -->` annotations for phased parallel execution.

### What neither has

- **A consolidated human-readable exit report.** You piece status together from progress logs, git history, and error logs. Neither tool produces a single "here's what happened" file you can skim in 30 seconds.
- **Model escalation when stuck.** The agent model is static per run — `--task-model` in ralphex, `RALPH_MODEL` in wiggum. If the loop gets stuck, neither automatically swaps in a higher-effort mode (e.g. Opus with maximum reasoning effort) to break through the block. Both halt and ask the human to intervene.
- **A post-run debrief tool** that classifies each anomaly into one of three buckets — orchestrator bugs (the tool misbehaved), plan bugs (the spec was wrong), agent-process bugs (the agent keeps tripping on the same landmine) — and prescribes the right response for each (file an issue, draft a surgical follow-up plan, or bind a guardrail).
- **Combined guardrails** — per-project rules merged with your global rules into one file the loop sees every iteration, with unverified/draft rules flagged until you've reviewed them.

---

## What ralph-stack adds

ralph-stack wraps ralphex — it inherits the full four-phase review pipeline, Claude Code support, and plan archival for free. It adopts the `guardrails.md` discipline that ralph-wiggum-cursor established. Then it adds the four things neither has.

| Capability | Source |
|---|---|
| Stateless loop, plan → `completed/`, four-phase review pipeline | inherited from **ralphex** |
| `guardrails.md` as first-class memory | discipline from **ralph-wiggum-cursor** |
| **Combined guardrails** — per-project + global merged into `ralph/combined-guardrails.md`, with unverified drafts flagged | added by **ralph-stack** |
| **Stuck-state detection + model escalation** — a detector watches for thrash; on thrash, the next iteration runs on a higher-effort Claude model (e.g. Opus at maximum reasoning effort). One-shot, reverts after | added by **ralph-stack** |
| **Post-run report** — `ralph/post-run-report.md` with status, iteration count, suspect-flag heuristics, and a recommended next action, written at exit | added by **ralph-stack** |
| **Post-run debrief** — `ralph-stack debrief` (deterministic 4-section read) and `/ralph-review` (Claude Code skill that classifies each anomaly into one of the [three bug buckets](#three-kinds-of-bugs-three-mechanisms) and drafts a surgical follow-up plan with preview) | added by **ralph-stack** |

ralph-stack does not re-implement the loop. It configures ralphex, adds the detector + escalation hook, renders the combined guardrails, writes the exit artifact, and ships the debrief tooling.

---

## Three kinds of bugs, three mechanisms

When a ralph run exits and something's off, the problem falls into one of three buckets. Each needs a different response — and vanilla ralph doesn't distinguish them, so you end up eyeballing logs and guessing.

### 1. Orchestrator bugs
The wrapper itself misbehaved — ralphex, ralph-stack, or the glue between them. Example: ralphex exits ✅ COMPLETE with 0 checkboxes flipped because it moved the plan to `completed/` before the checkbox counter ran. The escalation detector fires but the next iteration still runs on the same model. Stuck-dump is empty but the progress log shows 40 iterations of the same error. Not your code. Not your plan. File an issue.

**Mechanism:** `ralph-stack debrief` surfaces suspect-flag heuristics (0-boxes-flipped-with-task-commits, branch mismatch, escalation-without-model-change, all-boxes-flipped-but-INCOMPLETE). `/ralph-review` classifies each flag and drafts a ready-to-paste issue body.

### 2. Plan bugs
The plan was wrong — missing a step, wrong file path, contradictory instructions, a task that can't be satisfied. The agent did its job; the spec was broken. Plans in flight can be edited between runs, but completed plans stay in `plans/completed/` untouched — corrections happen in a new file.

**Mechanism:** `/ralph-review` drafts a surgical `plan_<date>-<prev>-fixups.md` — one checkbox per bug, with file paths, one-line fix, one-line why — shows the full file and reasoning before writing. You review, `ralph-stack run <new-plan>`. This is Huntley's [forward ralph loop](https://ghuntley.com/loop/), structured.

### 3. Agent-process bugs
Plan was fine, orchestrator was fine, but the agent keeps tripping on the same landmines: picks the wrong tool, re-enters a dead-end, forgets a project convention three iterations in a row, gets stuck in a local minimum it can't climb out of. Fixup plans won't help — the next run will re-make the pattern. You need durable memory that binds every iteration, and compute that can punch through blocks the current model can't.

**Mechanism:** (a) Combined guardrails — per-project `tasks/lessons.md` + global `~/.ralph/guardrails.md` merged into `ralph/combined-guardrails.md` the loop sees every iteration, with auto-drafted rules flagged `## ⚠️ Unverified` until you promote them. (b) Stuck-state detection + one-shot model escalation — when the detector sees thrash, the next iteration runs on a higher-effort Claude (e.g. Opus at max reasoning), reverting after.

---

## When NOT to use ralph

Ralph is for implementation, not exploration.

**Use ralph when:**
- The specs are crisp.
- Success is machine-verifiable — tests, types, lint.
- The work is bulk execution: CRUD, migrations, refactors, porting.
- You can define "done" and express it as checkboxes, then let the loop grind through without losing the plot.

**Don't use ralph when:**
- You're still deciding what to build.
- Taste and judgment matter more than correctness.
- You can't cleanly define what "done" even means.
- The real work is thinking, exploring, or making creative decisions — that's interactive territory.

Rule of thumb: **if you can't write checkboxes, you're not ready to loop. You're ready to think.**

---

## Install

```sh
brew install umputun/apps/ralphex    # the underlying loop
git clone https://github.com/marbaji/ralph-stack
cd ralph-stack
./install.sh                         # installs ralph-stack into .venv + $PATH
```

Requires the [Claude Code CLI](https://docs.claude.com/en/docs/claude-code) (`claude`) and [Codex CLI](https://github.com/openai/codex) (`codex`) for ralphex's external-review gate.

---

## Usage

```sh
ralph-stack init [plan.md]       # scaffold ralph/ dir + per-project guardrails
ralph-stack run  plan.md         # run the plan to completion (blocks)
ralph-stack resume               # resume from last stuck-state.json
ralph-stack stop                 # stop the currently-running orchestrator
ralph-stack status               # one-shot KV dump of stuck-state (mid-run peek)
ralph-stack debrief              # read-only 4-section post-run summary
```

Typical flow:

```sh
ralph-stack init docs/plans/my-feature.md
ralph-stack run  docs/plans/my-feature.md
# step away from your desk

# when you come back:
ralph-stack debrief
# if there's anything to triage:
claude   → /ralph-review
```

---

## Runtime artifacts

Everything ralph-stack writes lives in `./ralph/` in your project:

- `post-run-report.md` — status + recommended next action (written at exit)
- `stuck-state.json` — detector state (iteration, model, escalations)
- `combined-guardrails.md` — rendered guardrails (per-project + global)
- `next-iter-model.txt` — one-shot model override for the next iteration (cleared after read)

ralphex's own progress log lives at `../.ralphex/progress/progress-<plan>.txt` and captures per-iteration narratives.

---

## Post-run workflow

1. **`ralph-stack debrief`** — deterministic 4-section read: status, what happened, unverified guardrail drafts, suspect-flag heuristics. No LLM.
2. **`/ralph-review`** — agent layer on top. Classifies each suspect flag into one of the [three bug buckets](#three-kinds-of-bugs-three-mechanisms) and recommends exactly one next action.
3. If the bug is a **pattern** (same mistake across plans), the follow-up plan fixes this instance — but also write the rule into `tasks/lessons.md` or promote it into `combined-guardrails.md` so the next run sees it. Otherwise the next run re-makes the pattern.

---

## Plan immutability

A plan in flight is a living document — if you realize mid-run it's wrong: `ralph-stack stop`, edit the plan, `ralph-stack run`. The loop picks up from the current checkbox state with no duplicate work.

A completed plan is frozen. Corrections happen in a new `plan_<date>-<prev>-fixups.md`, never by editing `plans/completed/`.

---

## Credits

- [Geoffrey Huntley — Ralph Wiggum as a software engineer](https://ghuntley.com/ralph/) — the original pattern.
- [Geoffrey Huntley — everything is a ralph loop](https://ghuntley.com/loop/) — source of the "forward ralph loop" term.
- [Agrim Singh — Ralph For Idiots](https://x.com/agrimsingh/status/2010412150918189210) — clearest explanation of the core rules.
- [ralphex (umputun)](https://github.com/umputun/ralphex) — the loop ralph-stack wraps.
- [ralph-wiggum-cursor (Agrim Singh)](https://github.com/agrimsingh/ralph-wiggum-cursor) — source of the guardrails-as-memory discipline.
- [The Ralph Playbook (Clayton Farr)](https://claytonfarr.github.io/ralph-playbook/) — conventions + prompts, no tooling.
