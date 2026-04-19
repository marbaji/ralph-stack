---
name: ralph-review
description: Post-run debrief for a ralph-stack run. Runs `ralph-stack debrief` to get the deterministic 4-section summary (status, what happened, unverified guardrails, suspect flags), then layers agent judgment on top — interprets suspect flags as orchestrator vs deliverable bugs, recommends the next action, and (for deliverable bugs) offers to draft a surgical `plan_<date>-<prev>-fixups.md` with preview + reasoning before writing. Triggers on "ralph-review", "/ralph-review", "debrief ralph run", "review ralph run", or after a `ralph-stack run` / `ralph-stack resume` completes.
---

# Ralph Review — Post-Run Debrief

You are running a post-run debrief on a ralph-stack run. The deterministic half (read files, surface heuristic flags) is done by the CLI — **`ralph-stack debrief`**. Your job is the agent half: interpret the flags, classify bugs, recommend one next action, and optionally draft a surgical follow-up plan.

## Setup — Resolve the run's `ralph/` dir

The `ralph/` dir lives at `<ralph-stack-cwd>/ralph/` where `<ralph-stack-cwd>` is whatever directory the user was in when they invoked `ralph-stack run` (NOT necessarily the Python package root — ralph-stack uses `Path.cwd()` via `ProjectPaths`).

Walk up from the current working directory until you find `ralph/post-run-report.md`. If the user passed an explicit path (`/ralph-review /path/to/worktree`), use that directly. If nothing is found, stop with: `no ralph run to review in <cwd>`.

## Step 1 — Run `ralph-stack debrief`

From the resolved cwd:

```bash
ralph-stack debrief
```

It prints a 4-section markdown block:
1. **Status** — status line + checkbox count + iterations + branch.
2. **What happened** — last ~40 lines of the progress log (included when not COMPLETE).
3. **Unverified guardrails** — draft rules awaiting promote/edit/delete.
4. **Suspect flags** — heuristic orchestrator-bug flags (e.g. 0/0 with task commits → Bug 6 suspect; branch mismatch; escalation + COMPLETE; all-boxes-flipped + INCOMPLETE).

Use this output verbatim as your sections 1–4. Don't re-derive what the CLI already surfaced.

## Step 2 — Agent layer (sections 5–6)

### Section 5: Bug classification

For each suspect flag from Section 4, decide:
- **Orchestrator bug** (ralph-stack itself misbehaved) — the user is not expected to fix this from inside their project. Capture the flag + relevant context (post-run-report excerpt, stuck-state snapshot, progress-log tail) and point the user at `https://github.com/marbaji/ralph-stack/issues` to file a report.
- **Deliverable bug** (ralph produced bad code) — tests failing on the branch, lint/type errors, plan checkbox flipped but the referenced file missing or wrong content. Categorize as:
  - **Small + localized** (<30 min, single file) → inline fix on the same branch is fine.
  - **Multi-task / plan-shape miss** → corrective follow-up plan.

If Section 4 had no flags: "No bugs surfaced."

### Section 6: Next action

Exactly one recommendation, prioritized:

1. If orchestrator bugs surfaced: **"File a ralph-stack issue for <bug>."** Give the user a ready-to-paste issue body (one-line title + the relevant debrief excerpt) and the URL `https://github.com/marbaji/ralph-stack/issues/new`. Do not propose writing tests or fixes — ralph-stack is not the user's code to fix.
2. If guardrail drafts need action: **"Review N draft guardrail(s) above (promote/edit/delete), then `ralph-stack resume`."**
3. If deliverable bugs surfaced: **"Draft a corrective follow-up plan for these N bugs."** Do NOT write anything yet. Ask for confirmation with this exact wording:

   > Want me to draft `plan_<today>-<prev-name>-fixups.md` with these N items? If you say yes, I will show you the exact file contents and reasoning for each checkbox before writing anything, and it will be a **new** plan file — your existing plan at `<plan_path>` will not be edited.

   Do not offer inline hand-fixes. Ralph-stack's convention is forward-ralph-loop via a new plan. The original completed plan stays in `plans/completed/` untouched.
4. If status is COMPLETE and nothing flagged: **"Ship it. Branch `<branch>` is ready to merge / push / PR."**
5. If status is PAUSED and no drafts: **"Check progress log for the escalation reason; decide whether to resume, stop, or amend."**

## Follow-up plan drafter (only if the user says yes to #3 above)

When the user confirms, draft a surgical fixup plan. Rules:

- **Filename:** `plan_<YYYY-MM-DD>-<prev-plan-basename>-fixups.md` (sibling of the original plan location, e.g., `docs/plans/` not `plans/completed/`).
- **Content template:**

  ```markdown
  # Fixups for <prev-plan-basename>

  Corrects issues found post-run in `<original-plan-path>`.

  - [ ] <bug description>. **File:** `<path:line>`. **Fix:** <one-line change>. **Why:** <one-line reason from debrief>.
  - [ ] <next bug>. **File:** `<path:line>`. **Fix:** <one-line change>. **Why:** <one-line reason>.
  ```

- **Surgical only.** One checkbox per deliverable bug from Section 5. No architecture section, no tech stack, no re-statement of the original plan's goals, no TDD scaffolding. If the user wants a full replanning, they should invoke `superpowers:writing-plans` directly — not this drafter.
- **Preview before write.** Show the full file contents in a fenced code block. For each checkbox, show a one-sentence reasoning trace (*"Why this fix and not another"*) outside the code block. Wait for explicit approval before calling Write.
- **Do not edit the original plan.** Do not touch `plans/completed/<prev>.md`. Do not uncheck its boxes. The original is archived.
- **After writing:** tell the user to review and then `ralph-stack run <new-plan-path>`. Do not launch ralph-stack yourself.

## Output format

Print the `ralph-stack debrief` output verbatim as sections 1–4, then add sections 5–6 above. Keep total output under ~60 lines unless findings require more. After the debrief, ask: "Want me to <execute-recommendation>?" — turning the next-action into an actionable follow-up.

## Do not

- Do not re-parse the post-run-report yourself — `ralph-stack debrief` already did it. If the CLI output is wrong, that's an orchestrator bug to flag.
- Do not invent bugs. Only interpret suspect flags that `debrief` actually surfaced.
- Do not edit files unless the user approves a recommendation.
- Do not run long tests or build steps inside the debrief. Read files, quick `git log`, quick `pytest --co` at most.
