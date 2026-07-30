from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src import celery_tasks
from src.types import ContentToCodeMemorySnapshot


TASK_KWARGS = {
    "content": "The target encoder is updated by an exponential moving average.",
    "repo_url": "https://github.com/example/repo",
    "context": "Method section",
    "cache_key": "mapping-1",
    "paper_id": "paper-1",
    "box": {"l": 0.1, "t": 0.2, "w": 0.3, "h": 0.1},
    "page_number": 2,
    "user_id": 7,
}


def _pipeline() -> SimpleNamespace:
    return SimpleNamespace(
        map_content_to_code=AsyncMock(
            return_value={
                "reasoning": "Verified in the current repository.",
                "verdict": "implemented",
                "code_snippets": [
                    {
                        "content": "target.update(momentum)",
                        "filepath": "src/train.py",
                        "start_line": 20,
                        "end_line": 22,
                    }
                ],
            }
        ),
    )


def test_content_to_code_worker_off_path_does_not_retrieve_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _pipeline()
    persisted = Mock()
    monkeypatch.setattr(celery_tasks, "CONTENT_TO_CODE_MEMORY_MODE", "off")
    monkeypatch.setattr(
        celery_tasks,
        "_new_content_to_code_pipeline",
        lambda: agent,
    )
    monkeypatch.setattr(
        celery_tasks,
        "get_recent_content_to_code_matches_by_paper_and_user",
        Mock(side_effect=AssertionError("off mode must not query memory")),
    )
    monkeypatch.setattr(celery_tasks, "upsert_mapping_result", persisted)

    result = celery_tasks.map_content_to_code_task.run(**TASK_KWARGS)

    agent.map_content_to_code.assert_awaited_once_with(
        content=TASK_KWARGS["content"],
        repo_url=TASK_KWARGS["repo_url"],
        context=TASK_KWARGS["context"],
    )
    expected_snapshot = {
        "strategy": "off",
        "version": "v1",
        "hints": [],
    }
    assert result["memory_snapshot"] == expected_snapshot
    assert (
        persisted.call_args.args[0].outputs.memory_snapshot.model_dump(mode="json")
        == expected_snapshot
    )


def test_content_to_code_memory_retrieval_failure_records_recent_empty_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(celery_tasks, "CONTENT_TO_CODE_MEMORY_MODE", "recent")
    monkeypatch.setattr(
        celery_tasks,
        "get_recent_content_to_code_matches_by_paper_and_user",
        Mock(side_effect=RuntimeError("temporary retrieval failure")),
    )

    snapshot = celery_tasks._retrieve_content_to_code_memory(
        paper_id=TASK_KWARGS["paper_id"],
        user_id=TASK_KWARGS["user_id"],
    )

    assert snapshot.model_dump(mode="json") == {
        "strategy": "recent",
        "version": "v1",
        "hints": [],
    }


def test_content_to_code_worker_passes_and_persists_exact_recent_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _pipeline()
    snapshot = ContentToCodeMemorySnapshot.model_validate(
        {
            "strategy": "recent",
            "version": "v1",
            "hints": [
                {
                    "source_cache_key": "prior-1",
                    "source_content": "A similar target-network update.",
                    "verdict": "implemented",
                    "reasoning": "The prior interaction found this update.",
                    "paths": ["src/train.py:20-22"],
                    "folders": ["src"],
                }
            ],
        }
    )
    retrieve = Mock(return_value=snapshot)
    persisted = Mock()
    monkeypatch.setattr(celery_tasks, "CONTENT_TO_CODE_MEMORY_MODE", "recent")
    monkeypatch.setattr(
        celery_tasks,
        "_new_content_to_code_pipeline",
        lambda: agent,
    )
    monkeypatch.setattr(celery_tasks, "_retrieve_content_to_code_memory", retrieve)
    monkeypatch.setattr(celery_tasks, "upsert_mapping_result", persisted)

    result = celery_tasks.map_content_to_code_task.run(**TASK_KWARGS)

    retrieve.assert_called_once_with(
        paper_id=TASK_KWARGS["paper_id"],
        user_id=TASK_KWARGS["user_id"],
    )
    exact_hints = [hint.model_dump(mode="json") for hint in snapshot.hints]
    agent.map_content_to_code.assert_awaited_once_with(
        content=TASK_KWARGS["content"],
        repo_url=TASK_KWARGS["repo_url"],
        context=TASK_KWARGS["context"],
        memory_hints=exact_hints,
    )
    persisted_record = persisted.call_args.args[0]
    assert persisted_record.outputs.memory_snapshot == snapshot
    assert result["memory_snapshot"] == snapshot.model_dump(mode="json")
