# SkillOpt-Sleep — opencode integration

Give your **opencode** agent a nightly **sleep cycle**: it reviews past opencode
sessions offline, replays your recurring tasks on your own budget, and
consolidates what it learns into validated memory + skills behind a held-out
gate. Same engine as the Claude Code / Codex plugins (`skillopt_sleep`),
wrapped for opencode.

> opencode stores sessions in a **SQLite** database
> (`~/.local/share/opencode/opencode.db`), not JSONL. This integration reads
> that database **read-only** to harvest sessions — there is no JSONL to parse.

## What opencode supports (and what we use)

opencode extends via **`AGENTS.md`** instructions and **skills** at
`~/.config/opencode/skills/<name>/SKILL.md` (auto-loaded, no slash command
required). This integration is skill-first: the installed `skillopt-sleep`
skill contains the launch commands and operating rules. The shared runner is a
plain shell entrypoint that the skill calls.

## Install

```bash
git clone <repo-url> SkillOpt-Sleep
cd SkillOpt-Sleep
bash plugins/opencode/install.sh          # installs the global skill
export SKILLOPT_SLEEP_REPO="$(pwd)"        # so the runner is found from anywhere
```

Requires Python ≥ 3.10. Then **quit and restart opencode** so the new skill is
loaded (opencode loads config/skills once at startup).

## Use

Ask opencode in natural language:

```text
Use the skillopt-sleep skill to run status for this project.
Use the skillopt-sleep skill to run a dry-run for this project.
Use the skillopt-sleep skill to harvest from my opencode sessions.
Use the skillopt-sleep skill to run the full cycle for this project with the mock backend.
Use the skillopt-sleep skill to adopt the latest staged proposal.
```

Or call the engine directly:

```bash
python -m skillopt_sleep dry-run --project "$(pwd)" --source opencode --backend mock
python -m skillopt_sleep run --project "$(pwd)" --source opencode --backend mock \
  --max-sessions 5 --max-tasks 3 --progress
python -m skillopt_sleep run --project "$(pwd)" --source opencode --backend claude \
  --target-skill-path .opencode/skills/example/SKILL.md \
  --max-sessions 5 --max-tasks 3 --progress
```

`--source opencode` reads sessions from `~/.local/share/opencode/opencode.db`
(opened read-only). Use `--opencode-home /path/to/opencode-data` to point at a
different data directory — for example
`~/Library/Application Support/opencode` on macOS. Use `--source auto` to try
opencode first, then Codex archives, then Claude Code transcripts. Default
backend is `mock` (no API spend). Use `--target-skill-path` to stage/adopt into
a repo-scoped opencode skill such as `.opencode/skills/<name>/SKILL.md`; target
runs over-sample mined tasks and prefer tasks that match the target skill's
path, headings, and content.

For privacy-sensitive projects, split the run into reviewable steps:

```bash
python -m skillopt_sleep harvest --project "$(pwd)" --source opencode \
  --target-skill-path .opencode/skills/example/SKILL.md \
  --max-sessions 5 --max-tasks 3 \
  --output reviewed-tasks.json

python -m skillopt_sleep dry-run --project "$(pwd)" --backend claude \
  --tasks-file reviewed-tasks.json --progress --json
```

Inspect/redact the JSON and set `"reviewed": true` before using a real backend.
`--tasks-file` skips harvest/mining and replays only the reviewed JSON tasks;
real backends refuse task files still marked `"reviewed": false`.

## Notes / status

- **Read-only harvest.** opencode's session store is a SQLite database. The
  harvester opens it in read-only mode (`?mode=ro`) and never writes.
- opencode records sessions across **two** schemas (legacy `message`+`part`
  tables, and the newer event-sourced `session_message` table). The harvester
  reads the legacy tables primarily and falls back to `session_message` when a
  session has no legacy content, so it keeps working as opencode evolves.
- opencode does not persist a git branch per session in the store, so
  `git_branch` is left empty in digests (same convention as the Codex harvester).
- Secrets are redacted with the same patterns as the Codex harvester.
