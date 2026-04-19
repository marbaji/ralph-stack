#!/usr/bin/env bash
# Install ralph-stack: pip install -e, ensure ~/.ralph/, make wrapper script executable.
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"

echo "-> pip install -e $HERE"
pip install -e "$HERE"

echo "-> ensure ~/.ralph/"
mkdir -p "$HOME/.ralph"
if [[ ! -f "$HOME/.ralph/guardrails.md" ]]; then
  cat > "$HOME/.ralph/guardrails.md" <<'EOF'
# Ralph Global Guardrails

Append-only rules that apply across all projects.
EOF
fi

echo "-> make wrapper executable"
chmod +x "$HERE/scripts/claude-ralph-wrapper.sh"

echo ""
echo "ralph-stack installed."
echo "  Wrapper: $HERE/scripts/claude-ralph-wrapper.sh"
echo "  The runner writes this path into .ralphex/config on every run."
echo ""
echo "To start a run:"
echo "  caffeinate -dims ralph-stack run <plan.md>"
