"""Source selection for SkillOpt-Sleep transcript harvesting."""
from __future__ import annotations

from typing import Optional

from skillopt_sleep.harvest import harvest
from skillopt_sleep.harvest_codex import harvest_codex
from skillopt_sleep.harvest_opencode import harvest_opencode
from skillopt_sleep.types import SessionDigest


def harvest_for_config(cfg, *, since_iso: Optional[str] = None, limit: int = 0) -> list[SessionDigest]:
    source = cfg.get("transcript_source", "claude")
    scope = cfg.get("projects", "invoked")
    invoked_project = cfg.get("invoked_project", "")

    if source == "opencode":
        return harvest_opencode(
            cfg.opencode_db_path,
            scope=scope,
            invoked_project=invoked_project,
            since_iso=since_iso,
            limit=limit,
        )
    if source == "codex":
        return harvest_codex(
            cfg.codex_archived_sessions_dir,
            scope=scope,
            invoked_project=invoked_project,
            since_iso=since_iso,
            limit=limit,
        )
    if source == "auto":
        opencode_digests = harvest_opencode(
            cfg.opencode_db_path,
            scope=scope,
            invoked_project=invoked_project,
            since_iso=since_iso,
            limit=limit,
        )
        if opencode_digests:
            return opencode_digests
        codex_digests = harvest_codex(
            cfg.codex_archived_sessions_dir,
            scope=scope,
            invoked_project=invoked_project,
            since_iso=since_iso,
            limit=limit,
        )
        if codex_digests:
            return codex_digests

    return harvest(
        cfg.transcripts_dir,
        scope=scope,
        invoked_project=invoked_project,
        since_iso=since_iso,
        limit=limit,
    )
