from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src import server
from src.db import ConversationConflictError
from src.types import ConversationRecord


client = TestClient(server.app)

TASK_ID = UUID("00000000-0000-0000-0000-000000000001")
MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000002")


def conversation(**overrides: Any) -> ConversationRecord:
    values: dict[str, Any] = {
        "id": 12,
        "paper_id": "paper-1",
        "user_id": 7,
        "title": None,
        "messages": [],
        "summary": None,
        "summarized_through_message_id": None,
        "status": "idle",
        "active_task_id": None,
        "version": 3,
        "created_at": datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return ConversationRecord.model_validate(values)


def test_get_conversation_returns_user_paper_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = conversation()
    monkeypatch.setattr(server, "get_paper_record_by_id", lambda _paper_id: object())
    monkeypatch.setattr(
        server,
        "get_conversation_by_user_and_paper",
        lambda *, user_id, paper_id: record,
    )

    response = client.get("/papers/paper-1/conversation", params={"user_id": 7})

    assert response.status_code == 200
    assert response.json()["conversation"]["id"] == 12
    assert response.json()["conversation"]["paper_id"] == "paper-1"
    assert response.json()["conversation"]["user_id"] == 7


def test_get_conversation_rejects_mismatched_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "get_paper_record_by_id", lambda _paper_id: object())
    monkeypatch.setattr(
        server,
        "get_conversation_by_user_and_paper",
        lambda *, user_id, paper_id: conversation(user_id=99),
    )

    response = client.get("/papers/paper-1/conversation", params={"user_id": 7})

    assert response.status_code == 403


def test_get_conversation_validates_paper_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "get_paper_record_by_id", lambda _paper_id: None)

    response = client.get("/papers/missing/conversation", params={"user_id": 7})

    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown paper_id"


def test_send_message_claims_appends_and_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, ...]] = []
    idle = conversation()
    processing = conversation(status="processing", active_task_id=str(TASK_ID))
    generated_ids = iter([TASK_ID, MESSAGE_ID])

    monkeypatch.setattr(server, "get_paper_record_by_id", lambda _paper_id: object())
    monkeypatch.setattr(
        server,
        "get_or_create_conversation",
        lambda *, paper_id, user_id: idle,
    )
    monkeypatch.setattr(server, "uuid4", lambda: next(generated_ids))

    def claim(*, conversation_id: int, task_id: str) -> ConversationRecord:
        calls.append(("claim", conversation_id, task_id))
        return processing

    def append(*, conversation_id, message, expected_version) -> int:
        calls.append(
            (
                "append",
                conversation_id,
                str(message.id),
                message.status,
                expected_version,
                message.context_refs[0].entity_id,
            )
        )
        return 4

    def apply_async(*, args, task_id):
        calls.append(("dispatch", args, task_id))

    monkeypatch.setattr(server, "claim_conversation", claim)
    monkeypatch.setattr(server, "append_conversation_message", append)
    monkeypatch.setattr(
        server,
        "copilot_chat_task",
        SimpleNamespace(apply_async=apply_async),
    )

    response = client.post(
        "/papers/paper-1/conversation/messages",
        json={
            "user_id": 7,
            "content": "How does this equation map to the implementation?",
            "context_refs": [
                {
                    "type": "paper_entity",
                    "entity_id": "eq-4",
                    "entity_type": "equation",
                    "label": "Equation 4",
                }
            ],
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] == str(TASK_ID)
    assert body["message_id"] == str(MESSAGE_ID)
    assert body["status"] == "PENDING"
    assert body["conversation"]["status"] == "processing"
    assert body["conversation"]["version"] == 4
    assert body["conversation"]["messages"][0]["content"].startswith("How does")
    assert calls == [
        ("claim", 12, str(TASK_ID)),
        ("append", 12, str(MESSAGE_ID), "complete", 3, "eq-4"),
        ("dispatch", [12, str(MESSAGE_ID)], str(TASK_ID)),
    ]


def test_send_message_returns_conflict_when_claim_is_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "get_paper_record_by_id", lambda _paper_id: object())
    monkeypatch.setattr(
        server,
        "get_or_create_conversation",
        lambda *, paper_id, user_id: conversation(),
    )
    monkeypatch.setattr(server, "uuid4", lambda: TASK_ID)
    monkeypatch.setattr(
        server,
        "claim_conversation",
        lambda **_kwargs: (_ for _ in ()).throw(
            ConversationConflictError("already claimed")
        ),
    )
    monkeypatch.setattr(
        server,
        "append_conversation_message",
        lambda **_kwargs: pytest.fail("message must not append after a lost claim"),
    )

    response = client.post(
        "/papers/paper-1/conversation/messages",
        json={"user_id": 7, "content": "Question"},
    )

    assert response.status_code == 409


def test_send_message_releases_claim_after_append_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed: list[tuple[int, str]] = []
    generated_ids = iter([TASK_ID, MESSAGE_ID])
    monkeypatch.setattr(server, "get_paper_record_by_id", lambda _paper_id: object())
    monkeypatch.setattr(
        server,
        "get_or_create_conversation",
        lambda *, paper_id, user_id: conversation(),
    )
    monkeypatch.setattr(server, "uuid4", lambda: next(generated_ids))
    monkeypatch.setattr(
        server,
        "claim_conversation",
        lambda **_kwargs: conversation(
            status="processing",
            active_task_id=str(TASK_ID),
        ),
    )
    monkeypatch.setattr(
        server,
        "append_conversation_message",
        lambda **_kwargs: (_ for _ in ()).throw(
            ConversationConflictError("version changed")
        ),
    )
    monkeypatch.setattr(
        server,
        "set_conversation_failed",
        lambda *, conversation_id, task_id: failed.append(
            (conversation_id, task_id)
        ),
    )

    response = client.post(
        "/papers/paper-1/conversation/messages",
        json={"user_id": 7, "content": "Question"},
    )

    assert response.status_code == 409
    assert failed == [(12, str(TASK_ID))]


def test_send_message_marks_failed_when_dispatch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed: list[tuple[int, str]] = []
    generated_ids = iter([TASK_ID, MESSAGE_ID])
    monkeypatch.setattr(server, "get_paper_record_by_id", lambda _paper_id: object())
    monkeypatch.setattr(
        server,
        "get_or_create_conversation",
        lambda *, paper_id, user_id: conversation(),
    )
    monkeypatch.setattr(server, "uuid4", lambda: next(generated_ids))
    monkeypatch.setattr(
        server,
        "claim_conversation",
        lambda **_kwargs: conversation(
            status="processing",
            active_task_id=str(TASK_ID),
        ),
    )
    monkeypatch.setattr(server, "append_conversation_message", lambda **_kwargs: 4)
    monkeypatch.setattr(
        server,
        "copilot_chat_task",
        SimpleNamespace(
            apply_async=lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("broker unavailable")
            )
        ),
    )
    monkeypatch.setattr(
        server,
        "set_conversation_failed",
        lambda *, conversation_id, task_id: failed.append(
            (conversation_id, task_id)
        ),
    )

    response = client.post(
        "/papers/paper-1/conversation/messages",
        json={"user_id": 7, "content": "Question"},
    )

    assert response.status_code == 503
    assert failed == [(12, str(TASK_ID))]
