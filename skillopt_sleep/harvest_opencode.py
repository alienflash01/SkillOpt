"""SkillOpt-Sleep opencode session harvesting.

opencode (https://opencode.ai) stores sessions in a SQLite database, not JSONL:

  * ~/.local/share/opencode/opencode.db
    - session(id, directory, title, time_created, time_updated, ...)
    - message(id, session_id, time_created, data)   # data = Info: role/path/tokens
    - part(id, message_id, session_id, time_created, data)  # data = Part (type-tagged)
    - session_message(id, session_id, type, data)    # v2 event-sourced messages

The legacy ``message`` + ``part`` tables carry the real user/assistant content in
current installs (``part.data.type`` ∈ text/reasoning/tool/patch/...); the v2
``session_message`` table is read as a fallback when a session has no legacy
content. This module performs NO writes and opens the database read-only.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from skillopt_sleep.harvest import (
    _detect_feedback,
    _is_meta_prompt,
    _project_matches,
)
from skillopt_sleep.harvest_codex import _SECRET_PATTERNS, _sanitize_tool_name
from skillopt_sleep.types import SessionDigest


def _open_db(db_path: str) -> Optional[sqlite3.Connection]:
    """Open the opencode SQLite DB read-only; return None if unavailable."""
    if not db_path or not os.path.exists(db_path):
        return None
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def _iso_from_ms(ms: Any) -> str:
    """opencode stores epoch milliseconds; return a '...Z' ISO string."""
    try:
        value = int(ms)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _sanitize_text(text: str) -> str:
    sanitized = (text or "").replace("\x00", "").strip()
    if not sanitized or _is_meta_prompt(sanitized):
        return ""
    for pattern, replacement in _SECRET_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def _dedup(xs: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for x in xs:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _files_from_tool_input(tool: str, state_input: Dict[str, Any]) -> List[str]:
    """Best-effort file extraction from a completed tool's input args."""
    if not isinstance(state_input, dict):
        return []
    candidates: List[str] = []
    if tool in {"edit", "write"}:
        for key in ("filePath", "path", "file_path"):
            value = state_input.get(key)
            if isinstance(value, str) and value:
                candidates.append(value)
    elif tool in {"read", "glob", "grep"}:
        for key in ("path", "filePath", "file_path"):
            value = state_input.get(key)
            if isinstance(value, str) and value:
                candidates.append(value)
    return candidates


def _digest_legacy(
    con: sqlite3.Connection, session_id: str
) -> tuple[List[str], List[str], List[str], List[str], int, int, str, str]:
    """Read content from the legacy ``message`` + ``part`` tables.

    Returns (user_prompts, assistant_texts, tools, files, n_user, n_asst,
    earliest_iso, latest_iso). All text is sanitized.
    """
    user_prompts: List[str] = []
    assistant_texts: List[str] = []
    tools: List[str] = []
    files: List[str] = []
    n_user = 0
    n_asst = 0
    earliest = ""
    latest = ""

    rows = con.execute(
        """
        SELECT m.id, m.time_created,
               json_extract(m.data, '$.role') AS role,
               p.data AS pdata
        FROM part p
        JOIN message m ON p.message_id = m.id
        WHERE p.session_id = ?
        ORDER BY p.time_created ASC, p.id ASC
        """,
        (session_id,),
    ).fetchall()

    current_role: Optional[str] = None
    current_msg_id: Optional[str] = None
    for row in rows:
        msg_id = row[0]
        role = row[2]
        if msg_id != current_msg_id:
            current_msg_id = msg_id
            if role in {"user", "assistant"}:
                if role == "user":
                    n_user += 1
                else:
                    n_asst += 1
            current_role = role

        try:
            pdata = __import__("json").loads(row[3]) if row[3] else {}
        except Exception:
            continue
        if not isinstance(pdata, dict):
            continue

        ptype = pdata.get("type")

        # timestamps: prefer per-part time, fall back to message time_created
        ts_iso = _iso_from_ms(row[1])
        ptime = pdata.get("time") or {}
        if isinstance(ptime, dict):
            for key in ("end", "start", "created"):
                iso = _iso_from_ms(ptime.get(key))
                if iso:
                    ts_iso = iso
                    break
        if ts_iso:
            if not earliest:
                earliest = ts_iso
            latest = ts_iso

        if ptype == "text":
            text = _sanitize_text(str(pdata.get("text", "")))
            if not text:
                continue
            if role == "user":
                user_prompts.append(text)
                # feedback detection only on user text
                # (done by caller via _detect_feedback on joined text)
            elif role == "assistant":
                assistant_texts.append(text)
        elif ptype == "tool":
            name = pdata.get("tool")
            if isinstance(name, str) and name:
                tools.append(_sanitize_tool_name(name))
                state = pdata.get("state") or {}
                if isinstance(state, dict):
                    files.extend(
                        _files_from_tool_input(_sanitize_tool_name(name), state.get("input") or {})
                    )
        elif ptype == "patch":
            for f in pdata.get("files") or []:
                if isinstance(f, str) and f:
                    files.append(f)

    return user_prompts, assistant_texts, tools, files, n_user, n_asst, earliest, latest


def _digest_v2(
    con: sqlite3.Connection, session_id: str
) -> tuple[List[str], List[str], List[str], int, int]:
    """Fallback: read content from the v2 ``session_message`` table.

    Returns (user_prompts, assistant_texts, tools, n_user, n_asst).
    """
    import json as _json

    user_prompts: List[str] = []
    assistant_texts: List[str] = []
    tools: List[str] = []
    n_user = 0
    n_asst = 0

    rows = con.execute(
        "SELECT type, data FROM session_message WHERE session_id = ? "
        "ORDER BY time_created ASC, id ASC",
        (session_id,),
    ).fetchall()

    for type_, data in rows:
        try:
            d = _json.loads(data) if data else {}
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        if type_ == "user":
            text = _sanitize_text(str(d.get("text", "")))
            if text:
                n_user += 1
                user_prompts.append(text)
        elif type_ == "assistant":
            content = d.get("content")
            if isinstance(content, list) and content:
                n_asst += 1
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    itype = item.get("type")
                    if itype == "text":
                        text = _sanitize_text(str(item.get("text", "")))
                        if text:
                            assistant_texts.append(text)
                    elif itype == "tool":
                        name = item.get("name")
                        if isinstance(name, str) and name:
                            tools.append(_sanitize_tool_name(name))
        elif type_ == "shell":
            cmd = d.get("command")
            if isinstance(cmd, str) and cmd:
                tools.append("bash")
    return user_prompts, assistant_texts, tools, n_user, n_asst


def digest_opencode_session(
    con: sqlite3.Connection, session_id: str, project: str = ""
) -> Optional[SessionDigest]:
    """Build a ``SessionDigest`` from one opencode session row."""
    import json as _json

    row = con.execute(
        "SELECT id, directory, title, time_created, time_updated, summary_diffs "
        "FROM session WHERE id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    sid, directory, _title, t_created, t_updated, summary_diffs = row
    session_project = directory or ""

    user_prompts, assistant_texts, tools, files, n_user, n_asst, earliest, latest = (
        _digest_legacy(con, session_id)
    )

    # Fallback to v2 session_message when legacy tables held no content.
    if n_user == 0 and n_asst == 0:
        v_user, v_asst, v_tools, v_nu, v_na = _digest_v2(con, session_id)
        user_prompts = v_user
        assistant_texts = v_asst
        tools = v_tools
        n_user = v_nu
        n_asst = v_na

    if n_user == 0 and n_asst == 0:
        return None

    started = earliest or _iso_from_ms(t_created)
    ended = latest or _iso_from_ms(t_updated) or started

    # files from snapshot summary diffs (JSON list of {file, ...})
    if isinstance(summary_diffs, str) and summary_diffs:
        try:
            diffs = _json.loads(summary_diffs)
            if isinstance(diffs, list):
                for d in diffs:
                    if isinstance(d, dict):
                        f = d.get("file")
                        if isinstance(f, str) and f:
                            files.append(f)
        except Exception:
            pass

    if project and not _project_matches(session_project or "", "invoked", project):
        return None

    joined_user = "\n".join(user_prompts)
    feedback = _detect_feedback(joined_user) if joined_user else []

    return SessionDigest(
        session_id=session_id,
        project=session_project,
        started_at=started,
        ended_at=ended,
        user_prompts=user_prompts,
        assistant_finals=assistant_texts[-5:],
        tools_used=_dedup(tools),
        files_touched=_dedup(files),
        feedback_signals=feedback,
        n_user_turns=n_user,
        n_assistant_turns=n_asst,
        raw_path=f"opencode.db::{session_id}",
    )


def harvest_opencode(
    db_path: str,
    *,
    scope: Any = "all",
    invoked_project: str = "",
    since_iso: Optional[str] = None,
    limit: int = 0,
) -> List[SessionDigest]:
    """Walk the opencode SQLite DB and return matching digests (newest first)."""
    digests: List[SessionDigest] = []
    con = _open_db(db_path)
    if con is None:
        return digests
    try:
        # newest sessions first by time_updated (opencode uses epoch ms)
        rows = con.execute(
            "SELECT id, time_updated FROM session ORDER BY time_updated DESC, id DESC"
        ).fetchall()
        project_hint = invoked_project if scope == "invoked" else ""
        for sid, _ts in rows:
            digest = digest_opencode_session(con, sid, project=project_hint)
            if digest is None:
                continue
            if not _project_matches(digest.project or "", scope, invoked_project):
                continue
            if since_iso and digest.ended_at and digest.ended_at < since_iso:
                continue
            digests.append(digest)
            if limit and len(digests) >= limit:
                break
    finally:
        con.close()
    return digests
