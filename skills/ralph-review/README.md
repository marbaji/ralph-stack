# /ralph-review

Post-run debrief for a [ralph-stack](https://github.com/umputun/ralphex) run. One command that reads the exit artifacts and tells you what to do next.

## What it does

After `ralph-stack run` or `ralph-stack resume` completes (COMPLETE, INCOMPLETE, or PAUSED), invoke this skill. It runs `ralph-stack debrief` (the CLI does the deterministic half: reads artifacts, surfaces heuristic suspect flags) and then layers agent judgment on top.

**CLI does (sections 1–4, printed verbatim):**
1. **Status** — one-liner: plan, branch, checkbox count, iterations.
2. **What happened** — tail of the progress log (included when not COMPLETE).
3. **Unverified guardrails** — drafts needing promote / edit / delete.
4. **Suspect flags** — heuristic orchestrator-bug checks (0/0 with task commits, branch mismatch, escalation + COMPLETE, all-boxes-flipped + INCOMPLETE).

**Skill adds (sections 5–6):**
5. **Bug classification** — reads the suspect flags and categorizes each as orchestrator bug (fix live) or deliverable bug (follow-up plan).
6. **Next action** — exactly one recommendation, prioritized.

If Section 5 flags deliverable bugs, Section 6's recommendation is to **draft a surgical corrective follow-up plan** (`plan_<today>-<prev-name>-fixups.md`). The skill asks first — never writes without confirmation — and when you say yes, it shows the exact file contents and reasoning for each checkbox *before* calling Write. The new plan is always a **new file**; the original plan in `plans/completed/` is never edited.

## The surgical drafter (how it behaves)

When you confirm the draft:

- **Filename:** `plan_<YYYY-MM-DD>-<prev-plan-basename>-fixups.md` (sibling of `docs/plans/`, not `plans/completed/`).
- **Content:** one checkbox per bug surfaced in Section 4, each with file path, one-line fix, one-line why.
- **Delta-only:** no architecture, no tech stack, no re-statement of the original plan's goals, no TDD scaffolding. Only what changed. If you want a full replan, invoke `superpowers:writing-plans` directly — the drafter will not do that.
- **Preview before write:** full file contents shown in a code block + one sentence of reasoning per checkbox, outside the code block. You approve, then the skill writes.
- **After writing:** you review, tweak if needed, then `ralph-stack run <new-plan-path>`. The skill does not launch ralph-stack for you.

## When to use

- After any `ralph-stack run` or `ralph-stack resume` completes.
- Triggers: `ralph-review`, `/ralph-review`, `debrief ralph run`, `review ralph run`.
- Accepts an explicit path: `/ralph-review /path/to/worktree`.

## Doctrine — why the recommendations look the way they do

### What's grounded in ralph canon

These are **ralph rules**, not ralph-stack inventions — sourced from Huntley, Agrim, ralphex:

- **Stateless iterations.** Each iteration = fresh Claude session. No conversation memory between iterations within a run. Source: [ralphex.com](https://ralphex.com/), [Agrim Singh](https://x.com/agrimsingh/status/2010412150918189210).
- **Plan is the single source of truth.** The markdown file with GFM checkboxes is what survives. Source: Agrim, same post.
- **Guardrails file = append-only memory for repeat mistakes.** Win condition: *"the same mistake never happens twice."* Source: Agrim, same post.
- **Plan moves to `completed/` on success.** Archived, treated as done. Source: [ralphex.com](https://ralphex.com/).

### Just ordinary tool hygiene (not ralph-specific)

- **Orchestrator bugs (bugs in ralph-stack itself) get fixed live.** Ralph-stack isn't a ralph deliverable — it's the tool that runs ralph. Write a regression test in `ralph-stack/tests/`, fix in `ralph-stack/src/`, commit with `fix(orchestrator): ...`, launch next run. This is just "fix your tools before running them" — no ralph principle involved.

### ralph-stack's own convention (explicitly chosen, not in canon)

**When ralph exits and you find a bug in the code ralph produced, what do you do?**

Ralph canon is **silent** on this. Huntley, Agrim, ralphex, and ralph-wiggum-cursor all stop documenting at "plan moves to `completed/`." There is no prescribed post-run bug-fix workflow.

We researched what the community actually does ([details below](#community-research)) and found one universal pattern: **launch another ralph run, don't hand-fix.** The *exact form* of that next run is unspecified.

Ralph-stack picks the cleanest form: **corrective follow-up plan.**

- Write `plan_<today>-<prev-name>-fixups.md` with a checkbox list for the bugs.
- `ralph-stack run` that new plan.
- The original completed plan stays untouched in `plans/completed/`.
- No inline hand-fixes between runs (preserves the "ralph does all code mutation" invariant).
- No editing of the completed plan's checkboxes (preserves plan immutability).

**Rationale for this form over alternatives:**

| Form | Where it comes from | Why ralph-stack didn't pick it |
|---|---|---|
| "Forward ralph loop" (just another run, ad-hoc) | [Huntley](https://ghuntley.com/loop/) | Too vague — no artifact for future-you to read. |
| Uncheck boxes, rerun same plan | [ralphex README](https://github.com/umputun/ralphex) | Requires editing an archived plan → breaks immutability. |
| Append to original plan | [Clayton Farr playbook](https://claytonfarr.github.io/ralph-playbook/) | Same problem — the completed plan is supposed to be done. |
| Create a ticket | [HN commenter](https://news.ycombinator.com/item?id=46632445) | No tooling; vague. |
| **Corrective follow-up plan** | **ralph-stack** | Structured, preserves immutability, uses the same `ralph-stack run` path as any other plan. |

### Pattern bugs — when the fix alone isn't enough

If ralph keeps making the **same** mistake across plans (not a one-off), the follow-up plan fixes this instance but the next run will re-make the pattern. For those:

- Write the rule into `tasks/lessons.md` (short-form lesson), or
- Promote it into `combined-guardrails.md` (binds the next run).

This is the sanctioned durable-learning channel from Agrim's writeup — *"the same mistake never happens twice."*

## The three human gates

Plan immutability means ralphex re-reads the plan every iteration, so mid-run plan edits break ralph's tracking. Human intervention happens at three points only:

1. **Pre-launch** (primary gate): read the plan end-to-end before `ralph-stack run`. Plan mistakes caught here save 30+ min of wall-clock. Most valuable gate.
2. **Mid-run (if the plan is broken):** `ralph-stack stop`, edit the plan, `ralph-stack run <same_plan>`. Ralph resumes from flipped-boxes state.
3. **Post-run (via `/ralph-review`):** debrief, decide orchestrator fix / follow-up plan / ship.

## Community research

We checked whether the post-run deliverable-bug workflow had a convention we missed. Summary of sources reviewed:

- **Huntley** ([ghuntley.com/loop](https://ghuntley.com/loop/)): *"Any faults identified can be resolved through forward ralph loops to rectify issues."* — prescribes another run, doesn't specify form.
- **Clayton Farr playbook:** *"document bugs in `@IMPLEMENTATION_PLAN.md` using a subagent"* or *"if it's wrong, throw it out and start over."* — append-or-regenerate, not inline.
- **ralphex README:** *"uncheck `[x]` → `[ ]` to redo tasks, add/remove tasks, modify descriptions, then re-run."* — framed as mid-run recovery, not post-completion.
- **ralph-wiggum-cursor:** *"Fix the underlying issue manually OR add a guardrail to `.ralph/guardrails.md`."* — documented for mid-run only.
- **HN thread "Continuous agents and what happens after Ralph Wiggum?":** one commenter (waynenilsen) says *"it can often easily find its own bugs when prompted to do so, in this case, with a ticket perhaps."*

**Count of endorsements across ~15 sources reviewed:**
- Hand-fix inline: **0**
- Forward-ralph-loop (in some form): **3** (Huntley, ralphex, waynenilsen)
- Document-in-plan-file: **1** (Farr, mid-run)
- Add-to-guardrails: **1** (Agrim, mid-run)

**Honest conclusion:** the post-run deliverable-bug workflow is genuinely open. Ralph-stack's "corrective follow-up plan" convention is more structured than anything published but consistent with the community spirit ("don't hand-fix, launch another run"). It's the cleanest form that preserves plan immutability.

## Do not

- **Do not re-render the morning-report.** Read the persisted one. (Re-rendering from live state gives different answers than what was written at exit, defeating the point of this skill.)
- **Do not edit files unless the user approves a recommendation.**
- **Do not run long tests or builds inside the debrief.** Read files, quick `git log`, quick `pytest --co` at most.
- **Do not invent bugs.** Only flag what the heuristic checks surface.

## Sources

- [Geoffrey Huntley — Ralph Wiggum as a software engineer](https://ghuntley.com/ralph/)
- [Geoffrey Huntley — everything is a ralph loop](https://ghuntley.com/loop/)
- [Agrim Singh — Ralph For Idiots](https://x.com/agrimsingh/status/2010412150918189210)
- [ralphex (umputun/ralphex)](https://github.com/umputun/ralphex)
- [ralphex.com](https://ralphex.com/)
- [ralph-wiggum-cursor (agrimsingh)](https://github.com/agrimsingh/ralph-wiggum-cursor)
- [The Ralph Playbook (Clayton Farr)](https://claytonfarr.github.io/ralph-playbook/)
- [HN: Continuous agents and what happens after Ralph Wiggum?](https://news.ycombinator.com/item?id=46632445)

See `SKILL.md` for the operational spec (what the skill actually does at runtime).
