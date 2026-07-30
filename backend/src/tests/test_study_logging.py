import json
from pathlib import Path

import pytest

from src import study_logging


@pytest.fixture
def study_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STUDY_LOG_DIR", str(tmp_path))
    return tmp_path


def test_create_session_writes_grouped_logs(study_log_dir: Path):
    result = study_logging.create_study_session(
        user_id=7,
        paper_id="paper-abc",
        username="alice",
        paper_title="Test Paper",
    )
    session_id = result["session_id"]
    session_dirs = list(study_log_dir.glob("**/session.json"))
    assert len(session_dirs) == 1
    session_dir = session_dirs[0].parent
    assert session_dir.name == session_id
    assert (session_dir / "system.jsonl").is_file()

    ok = study_logging.log_study_event(
        session_id,
        group="ui",
        event_type="highlight_click",
        payload={"match_source": "ai"},
        source="client",
    )
    assert ok
    ui_lines = (session_dir / "ui.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(ui_lines) == 1
    event = json.loads(ui_lines[0])
    assert event["event_type"] == "highlight_click"
    assert event["payload"]["match_source"] == "ai"


def test_end_session_updates_meta(study_log_dir: Path):
    result = study_logging.create_study_session(
        user_id=1,
        paper_id="p1",
        username="bob",
    )
    session_id = result["session_id"]
    assert study_logging.end_study_session(session_id, reason="test", duration_ms=1000)
    session_json = json.loads(
        next(study_log_dir.glob("**/session.json")).read_text(encoding="utf-8"),
    )
    assert session_json["end_reason"] == "test"
    assert session_json["duration_ms"] == 1000
