#!/usr/bin/env bash
# Install the SkillOpt-Sleep opencode integration as a global opencode skill.
# Idempotent; prints what it does.
#
# opencode global skills live at ~/.config/opencode/skills/<name>/SKILL.md
# (see https://opencode.ai — skills are auto-loaded, no slash command needed).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OPENCODE_CONFIG_HOME="${OPENCODE_CONFIG_HOME:-$HOME/.config/opencode}"
SKILLS_DIR="${OPENCODE_CONFIG_HOME}/skills"
DEST="${SKILLS_DIR}/skillopt-sleep/SKILL.md"

echo "[install] repo: $REPO_ROOT"

# 1) global opencode skill
mkdir -p "$(dirname "$DEST")"
cp "$REPO_ROOT/plugins/opencode/skills/skillopt-sleep/SKILL.md" "$DEST"
echo "[install] skill           -> $DEST"

# 2) record the repo location so the runner is found from anywhere
cat <<EOF

[install] add to your shell profile:
    export SKILLOPT_SLEEP_REPO="$REPO_ROOT"

[install] Optional — add this to ~/.config/opencode/AGENTS.md so opencode
          always knows the tool:

  ## SkillOpt-Sleep
  Use the skillopt-sleep skill when I ask to run a sleep/dream/offline
  self-improvement cycle. The runner is:
  \`bash "$REPO_ROOT/plugins/run-sleep.sh" status --project "\$(pwd)"\`.

Done. Restart opencode (config/skills load once at startup), then try:
  Use the skillopt-sleep skill to run status for this project.
  Use the skillopt-sleep skill to run a harvest from my opencode sessions.
EOF
