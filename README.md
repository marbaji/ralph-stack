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

Each iteration reads the plan fresh, does one checkbox's worth of work, commits, exits. No accumulated confusion. When the loop makes a mistake, you write a rule into a guardrails file — the filesystem survives, the conversation doesn't, so the next iteration sees it. (Agrim Singh's [Ralph For Idiots](https://x.com/agrimsingh/status/2010412150918189210) is the cleanest walkthrough of the core rules.)

Canonical ralph is a shell one-liner:

```sh
while :; do cat prompt.md | claude-code; done
```

That proves the idea. It's not enough to actually use. The rest of this README is about what's been built on top, and what's still missing.

---

## Prior work, and what each is missing

Two serious implementations already exist.

### [ralphex](https://github.com/umputun/ralphex) (umputun, Go, targets Claude Code)

ralphex's defining feature is a four-phase review pipeline per plan:

1. Task execution with validation commands
2. Five parallel Claude reviewers (quality / implementation / testing / simplification / docs)
3. External review via Codex (or a custom script)
4. Two Claude agents for critical + major issues

It also handles plan archival (plans move to `completed/` on success), pluggable agent providers (Claude Code primary, Cursor / Copilot / Codex via wrapper scripts), a web dashboard (`--serve`), Docker wrappers, and AWS Bedrock.

**What ralphex doesn't have:**

- No `guardrails.md` concept. Closest is a static `CLAUDE.md` / prompt files.
- No token or context-budget tracking in the loop.
- No thrash detection on the task phase (only on review phase, via `--review-patience`).
- No model escalation when stuck — `--task-model` and `--review-model` are static per run.
- No single consolidated exit summary. You piece it together from `.ralphex/progress/progress-*.txt`, git history, and optional push notifications.
- No true resume cursor — resume = re-run the plan, it finds the first unchecked box.
- No post-run debrief / triage command.

### [ralph-wiggum-cursor](https://github.com/agrimsingh/ralph-wiggum-cursor) (Agrim Singh, Bash, targets Cursor)

ralph-wiggum-cursor's defining features are its stream parser and its gutter semantics:

- **Token tracking.** Estimates tokens in real time from prompt + reads + writes + assistant chars + shell output. WARNs at 70k, ROTATEs to a new session at 80k.
- **Gutter detection.** Halts the loop when (a) the same shell command fails 3×, (b) the same file is written 5× in 10 minutes, or (c) the agent emits `<ralph>GUTTER</ralph>`.
- **Defer on rate limits.** Exponential backoff (15s → 120s, jittered) and retry.
- **First-class `guardrails.md`.** Agent reads it first every iteration and writes lessons back to it as it learns.
- **Parallel worktrees.** `--parallel` runs N tasks in isolated `.ralph-worktrees/<run_id>-jobN/`, auto-merges, optionally opens one PR.
- **Task groups.** `<!-- group: N -->` annotations for phased parallel execution.

**What ralph-wiggum-cursor doesn't have:**

- No multi-agent review pipeline. Review is whatever the single agent does during its iteration, plus an optional `test_command`.
- No external reviewer (no Codex integration).
- No plan archival to `completed/`.
- No Claude Code support — Cursor-only.
- No consolidated morning report.
- No model escalation — single `RALPH_MODEL` per run, halts on GUTTER instead of trying a harder model.
- No post-run debrief tool.

### What neither has

- A **consolidated human-readable exit report** summarizing status, what happened, iteration count, and suspect flags in one file.
- **Model escalation on thrash.** Both halt when stuck; neither automatically tries a higher-capability model.
- A **post-run debrief** that classifies anomalies as orchestrator bugs (the tool misbehaved) vs deliverable bugs (the code is wrong) and drafts a corrective follow-up plan.
- **Combined guardrails** (per-project + global, merged into one file) with unverified/draft rules flagged until you've reviewed them.

---

## What ralph-stack is

ralph-stack wraps ralphex — it inherits ralphex's review pipeline, Claude Code support, and plan archival. It adopts the `guardrails.md` discipline that ralph-wiggum-cursor established. Then it adds the four things neither tool has.

| Capability | Source |
|---|---|
| Stateless loop, plan → `completed/`, 4-phase review pipeline | inherited from **ralphex** |
| `guardrails.md` as first-class memory | discipline from **ralph-wiggum-cursor** |
| **Combined guardrails** — per-project + global merged into `ralph/combined-guardrails.md`, with unverified drafts flagged | added by **ralph-stack** |
| **Stuck-state detection + model escalation** — detector watches for thrash; on thrash, swaps the next iteration to a higher-effort Claude model (one-shot, then reverts) | added by **ralph-stack** |
| **Morning report** — `ralph/morning-report.md` with status, iteration count, suspect-flag heuristics, and recommended next action, written at exit | added by **ralph-stack** |
| **Post-run debrief** — `ralph-stack debrief` (deterministic 4-section read) and `/ralph-review` (Claude Code skill that classifies orchestrator vs deliverable bugs and drafts a surgical follow-up plan with preview) | added by **ralph-stack** |

ralph-stack does not re-implement the loop. It configures ralphex, adds the detector + escalation hook, renders the combined guardrails, writes the exit artifact, and ships the debrief tooling.

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
# walk away

# next morning:
ralph-stack debrief
# if there's anything to triage:
claude   → /ralph-review
```

---

## Runtime artifacts

Everything ralph-stack writes lives in `./ralph/` in your project:

- `morning-report.md` — status + recommended next action (written at exit)
- `stuck-state.json` — detector state (iteration, model, escalations)
- `combined-guardrails.md` — rendered guardrails (per-project + global)
- `next-iter-model.txt` — one-shot model override for the next iteration (cleared after read)

ralphex's own progress log lives at `../.ralphex/progress/progress-<plan>.txt` and captures per-iteration narratives.

---

## Post-run workflow

1. **`ralph-stack debrief`** — deterministic 4-section read: status, what happened, unverified guardrail drafts, suspect-flag heuristics. No LLM.
2. **`/ralph-review`** — agent layer on top. Classifies each suspect flag as orchestrator or deliverable, drafts a follow-up plan if needed with preview + reasoning.
3. **Orchestrator bugs** (ralph-stack itself misbehaved) → [file an issue](https://github.com/marbaji/ralph-stack/issues) with the debrief output attached. Don't hand-fix ralph-stack from inside your project.
4. **Deliverable bugs** (the code ralph produced is wrong) → don't hand-fix between runs. Write a follow-up plan (`plan_<date>-<prev>-fixups.md`). The original plan stays in `plans/completed/` untouched. This is Huntley's [forward ralph loop](https://ghuntley.com/loop/).
5. **Pattern bugs** (ralph keeps making the same mistake) → fix via follow-up plan AND add a rule to `tasks/lessons.md` or promote it into `combined-guardrails.md` so the next run sees it.

---

## Plan immutability

A plan in flight is a living document — if you realize mid-run it's wrong: `ralph-stack stop`, edit the plan, `ralph-stack run`. The loop picks up from the current checkbox state with no duplicate work.

A completed plan is frozen. Corrections happen in a new `plan_<date>-<prev>-fixups.md`, never by editing `plans/completed/`.

---

## Design notes

See [`SPIKE-NOTES.md`](SPIKE-NOTES.md) for the Phase 0 spike that confirmed ralphex's CLI shape, model-override mechanism, and escalation semantics for v0.1.

---

## Credits

- [Geoffrey Huntley — Ralph Wiggum as a software engineer](https://ghuntley.com/ralph/) — the original pattern.
- [Geoffrey Huntley — everything is a ralph loop](https://ghuntley.com/loop/) — source of the "forward ralph loop" term.
- [Agrim Singh — Ralph For Idiots](https://x.com/agrimsingh/status/2010412150918189210) — clearest explanation of the core rules.
- [ralphex (umputun)](https://github.com/umputun/ralphex) — the loop ralph-stack wraps.
- [ralph-wiggum-cursor (Agrim Singh)](https://github.com/agrimsingh/ralph-wiggum-cursor) — source of the guardrails-as-memory discipline.
- [The Ralph Playbook (Clayton Farr)](https://claytonfarr.github.io/ralph-playbook/) — conventions + prompts, no tooling.
