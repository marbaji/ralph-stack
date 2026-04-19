---
name: ralph
description: Start, resume, or inspect an overnight ralph-stack run. Use when the user says "ralph run <plan>", "ralph status", or "ralph report". Thin wrapper around the ralph-stack CLI.
---

# /ralph — overnight ralph loop

This skill is a thin wrapper around the `ralph-stack` CLI. All logic lives in that CLI; this skill just validates inputs and shells out.

> **Canonical location:** this file lives in the ralph-stack worktree at `skills/ralph/SKILL.md`. Copy or symlink it into `~/.claude/plugins/marketplaces/marbaji-claude/skills/ralph/SKILL.md` so Claude Code discovers it. The ralph-stack worktree is the source of truth; the marketplace copy is downstream.

## Commands

### /ralph run <plan-path>

Start a new overnight run.

1. Verify the plan path exists and is a markdown file.
2. Verify `ralph-stack` is installed (`which ralph-stack`).
3. Warn if not inside a git repo — ralph relies on per-iteration commits.
4. Run the command in the user's Terminal:
   ```
   caffeinate -dims ralph-stack run <plan-path>
   ```
5. Do NOT spawn this inside Claude Code. Instruct the user to run it themselves in a Terminal they'll leave open on their desk.

### /ralph status

Run `ralph-stack status` and summarize the output to the user.

### /ralph report

Run `ralph-stack report` to regenerate the morning report, then read and present `./ralph/morning-report.md` to the user. If `## ⚠️ Unverified rules awaiting review` is present, call attention to it first.

## Prerequisites

- `ralph-stack` CLI installed (from `marbaji-claude/ralph-stack/`, via `./install.sh` or `pip install -e .`)
- ralphex installed (`brew install umputun/apps/ralphex`)
- Codex CLI authenticated
- Plan file exists at the given path (preferably authored via `/superpowers:brainstorming` → `/superpowers:writing-plans`)
- The `scripts/claude-ralph-wrapper.sh` in the ralph-stack install is picked up automatically by the runner (it writes `claude_command = <absolute-wrapper-path>` into `.ralphex/config` on every run). **No hook registration in `settings.json` is required** — the per-iteration model swap goes through the wrapper, not through a PreToolUse hook.

## Escalation

- If `ralph-stack resume` refuses due to stale `⚠️ Unverified` rules, read `tasks/lessons.md` to the user, point at the unverified rules, and help them promote/edit/delete.
- If ralph-stack is not installed, point to `~/.claude/plugins/marketplaces/marbaji-claude/ralph-stack/install.sh`.

## Do Not

- Do not invoke `ralph-stack run` inside a Claude Code session — it needs to be the user's own Terminal process to survive session boundaries.
- Do not auto-promote unverified rules. Only the user promotes.
- Do not use ralph for exploration work — it's for implementation only (per the spec's "steering vs rowing" philosophy).
