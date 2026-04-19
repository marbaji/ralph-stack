#!/usr/bin/env bash
# claude_command wrapper: translates ralph-stack's model override into a real
# Claude Code invocation. Installed by the runner writing .ralphex/config
# claude_command = <path-to-this-script>.
#
# One-shot: consumes ./ralph/next-iter-model.txt (if present) for this run,
# then delegates to the real `claude` binary.
#
# Mapping (per SPIKE-NOTES.md Decision 2 — Claude-variant swap):
#   opus   -> claude --model opus         (default, Opus at ralphex's configured effort)
#   codex  -> claude --model opus:max     (mid-loop "escalate to Codex" = Opus max effort)
#   (anything else) -> passed through as --model <value>

set -eu

OVERRIDE_FILE="./ralph/next-iter-model.txt"
MODEL_FLAG=()

if [[ -f "$OVERRIDE_FILE" ]]; then
  RAW=$(tr -d '[:space:]' < "$OVERRIDE_FILE" || true)
  case "$RAW" in
    opus)  MODEL_FLAG=(--model opus) ;;
    codex) MODEL_FLAG=(--model opus) ;;  # TEMP: opus:max isn't a real CLI alias; keep on opus
    "")    MODEL_FLAG=() ;;
    *)     MODEL_FLAG=(--model "$RAW") ;;
  esac
  rm -f "$OVERRIDE_FILE"  # one-shot
fi

exec claude ${MODEL_FLAG[@]+"${MODEL_FLAG[@]}"} "$@"
