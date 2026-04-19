# ralph-stack

Autonomous markdown-plan execution for Claude Code. Write a plan with checkboxes, run `ralph-stack run plan.md`, walk away. The tool loops Claude against the plan until every box is checked, then leaves a readable exit report so you can triage what happened.

---

## The idea

Long LLM sessions forget things. Context windows fill up, memory drifts, the agent wanders. The usual fix is more supervision — interrupt, correct, re-prompt. But that means you can't walk away.

**Ralph** (from [Geoffrey Huntley](https://ghuntley.com/ralph/), popularized by [Agrim Singh](https://x.com/agrimsingh/status/2010412150918189210)) takes a different approach: **stop treating the conversation as memory. Make the filesystem the memory.**

```
          ┌──────────────────────────────────────────┐
          │  plan.md       the task list, checkboxes │
          │  tasks/        scratchpad, lessons       │
          │  guardrails.md rules the loop must obey  │
          │  git           history of every change   │
          └──────────────────────────────────────────┘
                              ▲
                reads / writes │
                              ▼
                   ┌──────────────────────┐
                   │  Fresh Claude session │  new session every iteration
                   │  one iteration        │  no conversation memory
                   └──────────────────────┘
                              │
                              ▼
                      all boxes checked?
                        │           │
                        no          yes ──▶ done
                        │
                        └──▶ loop
```

Each iteration reads the plan fresh, does one checkbox's worth of work, commits, exits. No accumulated confusion, no context bleed. When the loop makes the same mistake twice, you write a rule into a guardrails file — the filesystem survives, the conversation doesn't, so the next iteration sees it.

### The three rules

Paraphrased from Agrim's [Ralph For Idiots](https://x.com/agrimsingh/status/2010412150918189210):

1. **Memory is the filesystem + git, not the chat.** Anything the next iteration needs to know goes in a file.
2. **One plan, one source of truth.** You edit it before the run. During the run, iterations only flip checkboxes and commit.
3. **The same mistake never happens twice.** If you catch the loop doing something wrong, write a rule. The rule outlives the session that noticed it.

---

## What ralph-stack adds

Ralph is a pattern. The cleanest implementation is [ralphex](https://github.com/umputun/ralphex) — a Go CLI that runs the loop. Ralph-stack wraps ralphex and adds the piece that's missing if you want to run something overnight and review it in the morning: **a human-review exit surface.**

- **Exit artifact (`ralph/morning-report.md`)** — when the run ends (done, stuck, or halted), a readable summary is written: status, what happened, iteration count, suspect flags. Skim it in 30 seconds.
- **Stuck-state detection** — a deterministic detector watches for thrash (repeating errors, no progress). On thrash, it escalates.
- **Escalation via model swap** — on thrash, the next iteration runs on a higher-effort Claude model. One-shot, then reverts.
- **Combined guardrails** — per-project rules and your global rules render into one file the loop sees every iteration. Unverified new drafts are flagged so you don't promote an untested rule unreviewed.
- **Three-gate review pipeline** — ralphex's native review hooks, pre-configured: Claude review 0 (5 sub-agents), Claude review 1 (2 sub-agents), external Codex review.
- **`/ralph-review` skill** — a post-run Claude Code skill that reads the debrief, classifies suspect flags as orchestrator vs deliverable bugs, and optionally drafts a surgical corrective follow-up plan.

Ralph-stack does not re-implement the loop itself. Stateless iterations, plan-completion archiving, and the review hooks all come from ralphex.

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

Ralphex's own progress log lives at `../.ralphex/progress/progress-<plan>.txt` and captures per-iteration narratives.

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

## Credits and prior work

Ralph-stack builds on work by others. If ralph-stack isn't the right fit, one of these probably is:

| Project | What it is |
|---|---|
| [Geoffrey Huntley — Ralph Wiggum as a software engineer](https://ghuntley.com/ralph/) | The original pattern. Everything else descends from here. |
| [Geoffrey Huntley — everything is a ralph loop](https://ghuntley.com/loop/) | Source of the "forward ralph loop" term for post-run corrections. |
| [Agrim Singh — Ralph For Idiots](https://x.com/agrimsingh/status/2010412150918189210) | Plain-language explanation of the core rules. The best starting point. |
| [ralphex (umputun)](https://github.com/umputun/ralphex) | The loop itself, in Go. Ralph-stack wraps this. |
| [ralph-wiggum-cursor (Agrim Singh)](https://github.com/agrimsingh/ralph-wiggum-cursor) | Cursor port. Use this if you're on Cursor, not Claude Code. |
| [The Ralph Playbook (Clayton Farr)](https://claytonfarr.github.io/ralph-playbook/) | Conventions + prompts, no tooling. |

---

## Design notes

See [`SPIKE-NOTES.md`](SPIKE-NOTES.md) for the Phase 0 spike that confirmed ralphex's CLI shape, model-override mechanism, and escalation semantics for v0.1.
