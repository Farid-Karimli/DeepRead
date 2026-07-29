from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest

from src import celery_tasks
from src.db import ConversationConflictError
from src.types import ConversationRecord, CopilotMessage


NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def user_message(message_id: UUID | None = None) -> CopilotMessage:
    return CopilotMessage(
        id=message_id or uuid4(),
        role="user",
        content="How does this match the paper?",
        created_at=NOW,
        status="complete",
    )


def conversation(
    messages: list[CopilotMessage],
    *,
    status: str = "processing",
    active_task_id: str | None = "task-1",
    version: int = 4,
) -> ConversationRecord:
    return ConversationRecord(
        id=12,
        paper_id="paper-1",
        user_id=7,
        messages=messages,
        status=status,
        active_task_id=active_task_id,
        version=version,
        created_at=NOW,
        updated_at=NOW,
    )


def run_task(message_id: UUID, task_id: str = "task-1") -> dict[str, object]:
    result = celery_tasks.copilot_chat_task.apply(
        args=(12, str(message_id)),
        task_id=task_id,
        throw=True,
    )
    assert result.successful()
    return result.result


def test_copilot_worker_persists_summary_reply_and_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = user_message()
    initial = conversation([user])
    latest = initial.model_copy()
    summarized = latest.model_copy(
        update={
            "summary": "Earlier discussion summary.",
            "summarized_through_message_id": user.id,
        }
    )
    paper = SimpleNamespace(id="paper-1")
    answer = SimpleNamespace(
        content="The implementation follows the method in section 3.",
        citations=[],
        metadata={"model": "test-model"},
        summary="Earlier discussion summary.",
        summarized_through_message_id=user.id,
    )
    agent = SimpleNamespace(answer=AsyncMock(return_value=answer))

    get_conversation = Mock(side_effect=[initial, latest])
    get_paper = Mock(return_value=paper)
    update_summary = Mock(return_value=summarized)
    append_message = Mock(return_value=5)
    set_idle = Mock(return_value=summarized)
    set_failed = Mock()
    monkeypatch.setattr(celery_tasks, "get_conversation_by_id", get_conversation)
    monkeypatch.setattr(celery_tasks, "get_paper_record_by_id", get_paper)
    monkeypatch.setattr(celery_tasks, "_new_copilot_agent", lambda: agent)
    monkeypatch.setattr(
        celery_tasks,
        "update_conversation_summary",
        update_summary,
    )
    monkeypatch.setattr(
        celery_tasks,
        "append_conversation_message",
        append_message,
    )
    monkeypatch.setattr(celery_tasks, "set_conversation_idle", set_idle)
    monkeypatch.setattr(celery_tasks, "set_conversation_failed", set_failed)

    result = run_task(user.id)

    agent.answer.assert_awaited_once_with(paper, initial, user)
    update_summary.assert_called_once_with(
        12,
        "Earlier discussion summary.",
        str(user.id),
        task_id="task-1",
    )
    append_message.assert_called_once()
    appended_conversation_id, assistant = append_message.call_args.args
    assert appended_conversation_id == 12
    assert assistant.role == "assistant"
    assert assistant.status == "complete"
    assert assistant.in_reply_to == user.id
    assert assistant.metadata is not None
    assert assistant.metadata.model == "test-model"
    assert assistant.metadata.task_id == "task-1"
    assert append_message.call_args.kwargs == {"expected_version": 4}
    set_idle.assert_called_once_with(12, "task-1")
    set_failed.assert_not_called()
    assert result == {
        "conversation_id": 12,
        "user_message_id": str(user.id),
        "assistant_message_id": str(assistant.id),
        "status": "complete",
        "idempotent": False,
    }


def test_copilot_worker_is_idempotent_for_existing_complete_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = user_message()
    reply = CopilotMessage(
        id=uuid4(),
        role="assistant",
        content="Already answered.",
        created_at=NOW,
        status="complete",
        in_reply_to=user.id,
    )
    current = conversation(
        [user, reply],
        status="idle",
        active_task_id=None,
        version=5,
    )
    set_idle = Mock(return_value=current)
    append_message = Mock()
    new_agent = Mock(side_effect=AssertionError("agent must not run"))

    monkeypatch.setattr(
        celery_tasks,
        "get_conversation_by_id",
        Mock(return_value=current),
    )
    monkeypatch.setattr(
        celery_tasks,
        "get_paper_record_by_id",
        Mock(return_value=SimpleNamespace(id="paper-1")),
    )
    monkeypatch.setattr(celery_tasks, "_new_copilot_agent", new_agent)
    monkeypatch.setattr(
        celery_tasks,
        "append_conversation_message",
        append_message,
    )
    monkeypatch.setattr(celery_tasks, "set_conversation_idle", set_idle)
    monkeypatch.setattr(celery_tasks, "set_conversation_failed", Mock())

    result = run_task(user.id)

    assert result["assistant_message_id"] == str(reply.id)
    assert result["idempotent"] is True
    set_idle.assert_not_called()
    new_agent.assert_not_called()
    append_message.assert_not_called()


def test_copilot_worker_rejects_a_stale_task_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = user_message()
    current = conversation([user], active_task_id="newer-task")
    set_failed = Mock()
    get_paper = Mock()
    monkeypatch.setattr(
        celery_tasks,
        "get_conversation_by_id",
        Mock(return_value=current),
    )
    monkeypatch.setattr(celery_tasks, "get_paper_record_by_id", get_paper)
    monkeypatch.setattr(celery_tasks, "set_conversation_failed", set_failed)

    with pytest.raises(ConversationConflictError, match="no longer owns"):
        run_task(user.id)

    get_paper.assert_not_called()
    set_failed.assert_called_once_with(12, "task-1")


def test_copilot_worker_marks_failure_and_reraises_agent_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = user_message()
    current = conversation([user])
    agent = SimpleNamespace(
        answer=AsyncMock(side_effect=RuntimeError("model unavailable"))
    )
    set_failed = Mock()
    set_idle = Mock()
    append_message = Mock()
    monkeypatch.setattr(
        celery_tasks,
        "get_conversation_by_id",
        Mock(return_value=current),
    )
    monkeypatch.setattr(
        celery_tasks,
        "get_paper_record_by_id",
        Mock(return_value=SimpleNamespace(id="paper-1")),
    )
    monkeypatch.setattr(celery_tasks, "_new_copilot_agent", lambda: agent)
    monkeypatch.setattr(celery_tasks, "set_conversation_failed", set_failed)
    monkeypatch.setattr(celery_tasks, "set_conversation_idle", set_idle)
    monkeypatch.setattr(
        celery_tasks,
        "append_conversation_message",
        append_message,
    )

    with pytest.raises(RuntimeError, match="model unavailable"):
        run_task(user.id)

    set_failed.assert_called_once_with(12, "task-1")
    set_idle.assert_not_called()
    append_message.assert_not_called()
