from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from src import db
from src.types import CopilotMessage


class FakeQuery:
    def __init__(
        self,
        client: "FakeSupabase",
        *,
        table: str | None = None,
        rpc: str | None = None,
        rpc_params: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.table = table
        self.rpc = rpc
        self.rpc_params = rpc_params
        self.operation: str | None = None
        self.payload: Any = None
        self.options: dict[str, Any] = {}
        self.filters: list[tuple[str, str, Any]] = []

    def select(self, columns: str) -> "FakeQuery":
        self.operation = "select"
        self.payload = columns
        return self

    def upsert(self, values: dict[str, Any], **options: Any) -> "FakeQuery":
        self.operation = "upsert"
        self.payload = values
        self.options = options
        return self

    def update(self, values: dict[str, Any]) -> "FakeQuery":
        self.operation = "update"
        self.payload = values
        return self

    def eq(self, column: str, value: Any) -> "FakeQuery":
        self.filters.append(("eq", column, value))
        return self

    def in_(self, column: str, values: list[Any]) -> "FakeQuery":
        self.filters.append(("in", column, values))
        return self

    def contains(self, column: str, value: Any) -> "FakeQuery":
        self.filters.append(("contains", column, value))
        return self

    def limit(self, value: int) -> "FakeQuery":
        self.filters.append(("limit", "", value))
        return self

    def execute(self) -> SimpleNamespace:
        self.client.calls.append(
            {
                "table": self.table,
                "rpc": self.rpc,
                "rpc_params": self.rpc_params,
                "operation": self.operation,
                "payload": self.payload,
                "options": self.options,
                "filters": self.filters,
            }
        )
        return SimpleNamespace(data=self.client.responses.pop(0))


class FakeSupabase:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, table=name)

    def rpc(self, name: str, params: dict[str, Any]) -> FakeQuery:
        return FakeQuery(self, rpc=name, rpc_params=params)


def conversation_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": 12,
        "paper_id": "paper-1",
        "user_id": 7,
        "title": None,
        "messages": [],
        "summary": None,
        "summarized_through_message_id": None,
        "status": "idle",
        "active_task_id": None,
        "version": 0,
        "created_at": "2026-07-29T12:00:00Z",
        "updated_at": "2026-07-29T12:00:00Z",
    }
    row.update(overrides)
    return row


def use_client(monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> FakeSupabase:
    client = FakeSupabase(responses)
    monkeypatch.setattr(db, "get_supabase_client", lambda: client)
    return client


def test_get_or_create_uses_unique_constraint_without_overwriting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = use_client(monkeypatch, [[], [conversation_row()]])

    conversation = db.get_or_create_conversation("paper-1", 7, title="Paper")

    assert conversation.id == 12
    assert client.calls[0]["operation"] == "upsert"
    assert client.calls[0]["payload"] == {
        "paper_id": "paper-1",
        "user_id": 7,
        "title": "Paper",
    }
    assert client.calls[0]["options"] == {
        "on_conflict": "paper_id,user_id",
        "ignore_duplicates": True,
    }
    assert ("eq", "user_id", 7) in client.calls[1]["filters"]
    assert ("eq", "paper_id", "paper-1") in client.calls[1]["filters"]


def test_get_conversation_by_id_returns_none_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = use_client(monkeypatch, [[]])

    assert db.get_conversation_by_id(404) is None
    assert ("eq", "id", 404) in client.calls[0]["filters"]


def test_append_message_uses_atomic_rpc_and_returns_new_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = use_client(monkeypatch, [4])
    message = CopilotMessage(
        id=uuid4(),
        role="user",
        content="How is this implemented?",
        created_at=datetime.now(UTC),
    )

    version = db.append_conversation_message(12, message, expected_version=3)

    assert version == 4
    assert client.calls[0]["rpc"] == "append_conversation_message"
    assert client.calls[0]["rpc_params"]["p_conversation_id"] == 12
    assert client.calls[0]["rpc_params"]["p_expected_version"] == 3
    assert client.calls[0]["rpc_params"]["p_message"]["content"] == message.content


@pytest.mark.parametrize("rpc_result", [None, []])
def test_append_message_raises_clear_version_conflict(
    monkeypatch: pytest.MonkeyPatch,
    rpc_result: Any,
) -> None:
    use_client(monkeypatch, [rpc_result])
    message = CopilotMessage(
        id=uuid4(),
        role="user",
        content="Question",
        created_at=datetime.now(UTC),
    )

    with pytest.raises(db.ConversationConflictError, match="expected_version=3"):
        db.append_conversation_message(12, message, expected_version=3)


def test_claim_is_conditional_on_available_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processing = conversation_row(status="processing", active_task_id="task-1")
    client = use_client(monkeypatch, [[processing]])

    conversation = db.claim_conversation(12, "task-1")

    assert conversation.status == "processing"
    assert client.calls[0]["payload"] == {
        "status": "processing",
        "active_task_id": "task-1",
    }
    assert ("eq", "id", 12) in client.calls[0]["filters"]
    assert ("in", "status", ["idle", "failed"]) in client.calls[0]["filters"]


def test_claim_conflict_is_not_silently_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_client(monkeypatch, [[]])

    with pytest.raises(db.ConversationConflictError, match="claim conversation"):
        db.claim_conversation(12, "task-2")


@pytest.mark.parametrize(
    ("transition", "expected_status"),
    [
        (db.set_conversation_idle, "idle"),
        (db.set_conversation_failed, "failed"),
    ],
)
def test_completion_transitions_are_guarded_by_active_task(
    monkeypatch: pytest.MonkeyPatch,
    transition: Any,
    expected_status: str,
) -> None:
    result = conversation_row(status=expected_status, active_task_id=None)
    client = use_client(monkeypatch, [[result]])

    conversation = transition(12, "task-1")

    assert conversation.status == expected_status
    assert ("eq", "status", "processing") in client.calls[0]["filters"]
    assert ("eq", "active_task_id", "task-1") in client.calls[0]["filters"]


def test_summary_update_advances_boundary_and_guards_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = uuid4()
    updated = conversation_row(
        status="processing",
        active_task_id="task-1",
        summary="Prior findings",
        summarized_through_message_id=str(boundary),
    )
    client = use_client(monkeypatch, [[updated]])

    conversation = db.update_conversation_summary(
        12,
        "Prior findings",
        str(boundary),
        task_id="task-1",
    )

    assert conversation.summarized_through_message_id == boundary
    assert client.calls[0]["payload"] == {
        "summary": "Prior findings",
        "summarized_through_message_id": str(boundary),
    }
    assert ("eq", "active_task_id", "task-1") in client.calls[0]["filters"]


@pytest.mark.parametrize(("rows", "expected"), [([{"id": 12}], True), ([], False)])
def test_assistant_reply_idempotency_lookup(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, Any]],
    expected: bool,
) -> None:
    user_message_id = str(uuid4())
    client = use_client(monkeypatch, [rows])

    assert db.has_assistant_reply(12, user_message_id) is expected
    assert (
        "contains",
        "messages",
        [{"role": "assistant", "in_reply_to": user_message_id}],
    ) in client.calls[0]["filters"]
