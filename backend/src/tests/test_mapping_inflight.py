from unittest.mock import MagicMock

from src.mapping_inflight import (
    claim_mapping_inflight,
    get_mapping_inflight_task_id,
    release_mapping_inflight,
)


def test_claim_and_release_mapping_inflight(monkeypatch):
    store: dict[str, str] = {}

    mock_redis = MagicMock()
    mock_redis.set = MagicMock(
        side_effect=lambda key, value, nx=False, ex=None: (
            False
            if nx and key in store
            else store.update({key: value}) or True
        )
    )
    mock_redis.get = MagicMock(side_effect=lambda key: store.get(key))
    mock_redis.delete = MagicMock(
        side_effect=lambda key: store.pop(key, None) is not None
    )

    monkeypatch.setattr(
        "src.mapping_inflight._client",
        lambda: mock_redis,
    )

    cache_key = "cache-abc"
    assert claim_mapping_inflight(cache_key, "task-1") is True
    assert get_mapping_inflight_task_id(cache_key) == "task-1"
    assert claim_mapping_inflight(cache_key, "task-2") is False

    release_mapping_inflight(cache_key, "task-2")
    assert get_mapping_inflight_task_id(cache_key) == "task-1"

    release_mapping_inflight(cache_key, "task-1")
    assert get_mapping_inflight_task_id(cache_key) is None
    assert claim_mapping_inflight(cache_key, "task-3") is True
