"""
Append-only local logs for within-subjects user studies.

Each time a participant opens a paper, the client starts a new session. Events
are grouped into JSONL files under:

    {STUDY_LOG_DIR}/user_{id}_{username}/paper_{paper_id}/{session_id}/
        session.json
        ui.jsonl
        navigation.jsonl
        mapping.jsonl
        copilot.jsonl
        system.jsonl
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

logger = logging.getLogger(__name__)

StudyLogGroup = Literal["ui", "navigation", "mapping", "copilot", "system"]

_GROUP_FILES: dict[StudyLogGroup, str] = {
    "ui": "ui.jsonl",
    "navigation": "navigation.jsonl",
    "mapping": "mapping.jsonl",
    "copilot": "copilot.jsonl",
    "system": "system.jsonl",
}

_SESSION_ID_RE = re.compile(
    r"^[0-9]{8}T[0-9]{6}Z_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def study_log_root() -> Path:
    raw = os.getenv("STUDY_LOG_DIR", "study_logs")
    return Path(raw).expanduser().resolve()


def _sanitize_segment(value: str, *, fallback: str = "unknown") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())[:80]
    return cleaned or fallback


def _paper_dir_name(paper_id: str) -> str:
    short = paper_id[:16] if len(paper_id) > 16 else paper_id
    return f"paper_{_sanitize_segment(short, fallback='paper')}"


def _user_dir_name(user_id: int, username: str | None) -> str:
    name = _sanitize_segment(username or "user", fallback="user")
    return f"user_{user_id}_{name}"


def new_session_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{uuid4()}"


def create_study_session(
    *,
    user_id: int,
    paper_id: str,
    username: str | None = None,
    paper_title: str | None = None,
    client_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session_id = new_session_id()
    started_at = datetime.now(UTC)
    session_dir = (
        study_log_root()
        / _user_dir_name(user_id, username)
        / _paper_dir_name(paper_id)
        / session_id
    )
    session_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "session_id": session_id,
        "user_id": user_id,
        "username": username,
        "paper_id": paper_id,
        "paper_title": paper_title,
        "started_at": started_at.isoformat(),
        "client_meta": client_meta or {},
    }
    (session_dir / "session.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log_study_event(
        session_id,
        group="system",
        event_type="session_start",
        payload={"paper_title": paper_title, "client_meta": client_meta or {}},
        user_id=user_id,
        paper_id=paper_id,
    )
    return {"session_id": session_id, "started_at": started_at.isoformat()}


def _resolve_session_dir(session_id: str) -> Path | None:
    if not _SESSION_ID_RE.match(session_id):
        return None
    root = study_log_root()
    if not root.is_dir():
        return None
    matches = list(root.glob(f"**/{session_id}/session.json"))
    if not matches:
        return None
    return matches[0].parent


def end_study_session(
    session_id: str,
    *,
    reason: str = "client_unload",
    duration_ms: int | None = None,
) -> bool:
    session_dir = _resolve_session_dir(session_id)
    if session_dir is None:
        return False
    meta_path = session_dir / "session.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        meta = {"session_id": session_id}
    meta["ended_at"] = datetime.now(UTC).isoformat()
    meta["end_reason"] = reason
    if duration_ms is not None:
        meta["duration_ms"] = duration_ms
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log_study_event(
        session_id,
        group="system",
        event_type="session_end",
        payload={"reason": reason, "duration_ms": duration_ms},
        user_id=meta.get("user_id"),
        paper_id=meta.get("paper_id"),
    )
    return True


def log_study_event(
    session_id: str,
    *,
    group: StudyLogGroup,
    event_type: str,
    payload: dict[str, Any] | None = None,
    user_id: int | None = None,
    paper_id: str | None = None,
    source: Literal["client", "server"] = "server",
) -> bool:
    session_dir = _resolve_session_dir(session_id)
    if session_dir is None:
        logger.debug("study log: unknown session_id=%s", session_id)
        return False

    if user_id is None or paper_id is None:
        try:
            meta = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
            user_id = user_id if user_id is not None else meta.get("user_id")
            paper_id = paper_id if paper_id is not None else meta.get("paper_id")
        except (OSError, json.JSONDecodeError):
            pass

    record: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "session_id": session_id,
        "user_id": user_id,
        "paper_id": paper_id,
        "group": group,
        "event_type": event_type,
        "source": source,
        "payload": payload or {},
    }
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    log_path = session_dir / _GROUP_FILES[group]
    try:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        logger.exception("Failed to write study log session_id=%s", session_id)
        return False
    return True
