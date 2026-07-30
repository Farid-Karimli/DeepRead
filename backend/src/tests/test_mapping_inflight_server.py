from unittest.mock import MagicMock

from src.server import _resolve_inflight_mapping_task_id


def test_resolve_inflight_returns_existing_active_task(monkeypatch):
    monkeypatch.setattr(
        "src.server.claim_mapping_inflight",
        lambda cache_key, task_id: False,
    )
    monkeypatch.setattr(
        "src.server.get_mapping_inflight_task_id",
        lambda cache_key: "existing-task",
    )
    monkeypatch.setattr(
        "src.server.celery.AsyncResult",
        lambda task_id: MagicMock(state="STARTED"),
    )

    resolved = _resolve_inflight_mapping_task_id("cache-key", "new-task")
    assert resolved == "existing-task"


def test_resolve_inflight_reclaims_stale_slot(monkeypatch):
    calls: list[str] = []

    def fake_claim(cache_key, task_id):
        calls.append(task_id)
        return len(calls) == 2

    monkeypatch.setattr("src.server.claim_mapping_inflight", fake_claim)
    monkeypatch.setattr(
        "src.server.get_mapping_inflight_task_id",
        lambda cache_key: "stale-task",
    )
    monkeypatch.setattr(
        "src.server.release_mapping_inflight",
        lambda cache_key, task_id: None,
    )
    monkeypatch.setattr(
        "src.server.celery.AsyncResult",
        lambda task_id: MagicMock(state="FAILURE"),
    )

    resolved = _resolve_inflight_mapping_task_id("cache-key", "new-task")
    assert resolved == "new-task"
    assert calls == ["new-task", "new-task"]
