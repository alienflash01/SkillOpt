#!/usr/bin/env bash
# SkillOpt-Sleep runner — invokes the skillopt_sleep engine with a suitable
# Python interpreter, from the repo that contains this plugin.
#
# Usage: sleep.sh <run|dry-run|status|adopt|harvest> [extra args...]
set -euo pipefail

# Resolve the repo root: the plugin lives at <repo>/skillopt-sleep-plugin,
# so the engine package is at <repo>/skillopt_sleep. CLAUDE_PLUGIN_ROOT points
# at the plugin dir when run by Claude Code; fall back to this script's dir.
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
REPO_ROOT="$(cd "$PLUGIN_ROOT/.." && pwd)"

# Pick an interpreter that satisfies SkillOpt's 3.10+ requirement.
PY=""
for cand in python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    ver="$("$cand" -c 'import sys; print("%d%d" % sys.version_info[:2])' 2>/dev/null || echo 0)"
    if [ "${ver:-0}" -ge 310 ]; then PY="$cand"; break; fi
  fi
done
if [ -z "$PY" ]; then
  echo "[sleep] ERROR: need Python >= 3.10 (found none). Install one and retry." >&2
  exit 1
fi

if [ "$#" -eq 0 ]; then set -- status; fi

cd "$REPO_ROOT"
exec "$PY" -m skillopt_sleep "$@"
