from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from src.copilot_agent import CopilotAgent, ModelCompletion, _repo_tool_guard
from src.types import (
    BoxModel,
    CodeRangeRef,
    ConversationRecord,
    CopilotMessage,
    PaperEntityRef,
    PaperMageResult,
    PaperRecord,
    SectionEntity,
    SentenceEntity,
)


class FakeModel:
    model = "fake-copilot"

    def __init__(self, answer_payload: dict[str, Any]) -> None:
        self.answer_payload = answer_payload
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        prompt: str,
        *,
        cwd: Path | None,
        allowed_tools: list[str],
        output_schema: dict[str, Any],
    ) -> ModelCompletion:
        self.calls.append(
            {
                "prompt": prompt,
                "cwd": cwd,
                "allowed_tools": allowed_tools,
                "schema": output_schema,
            }
        )
        if "summary" in output_schema.get("properties", {}):
            return ModelCompletion(
                structured_output={"summary": "Earlier: the user is tracing training."}
            )
        return ModelCompletion(
            structured_output=self.answer_payload,
            usage={"input_tokens": 120, "output_tokens": 30},
            duration_seconds=0.25,
            tool_calls=2,
        )


def _message(
    role: str,
    content: str,
    *,
    message_id: UUID | None = None,
    context_refs: list[Any] | None = None,
) -> CopilotMessage:
    return CopilotMessage(
        id=message_id or uuid4(),
        role=role,
        content=content,
        context_refs=context_refs or [],
        created_at=datetime.now(UTC),
    )


def _paper() -> PaperRecord:
    box = BoxModel(page=0, l=0, t=0, w=1, h=1)
    sentence = SentenceEntity(
        entity_id="sent-1",
        sentence_content="The encoder is optimized with a contrastive objective.",
        page_index=0,
        box=box,
    )
    section = SectionEntity(
        entity_id="sec-1",
        section_header="Method",
        section_content="We train an encoder and target encoder.",
        sentences=[sentence],
        page_index=0,
        box=box,
    )
    return PaperRecord(
        id="paper-1",
        paper_title="A Test Paper",
        github_link="https://github.com/example/repo",
        created_at=datetime.now(UTC),
        papermage_result=PaperMageResult(
            paper_title="A Test Paper",
            n_pages=1,
            sections=[section],
        ),
    )


def _conversation(
    messages: list[CopilotMessage] | None = None,
    *,
    summary: str | None = None,
    boundary: UUID | None = None,
) -> ConversationRecord:
    now = datetime.now(UTC)
    return ConversationRecord(
        id=1,
        paper_id="paper-1",
        user_id=7,
        messages=messages or [],
        summary=summary,
        summarized_through_message_id=boundary,
        created_at=now,
        updated_at=now,
    )


def test_resolves_canonical_paper_and_code_context(tmp_path: Path) -> None:
    source = tmp_path / "src" / "train.py"
    source.parent.mkdir()
    source.write_text("def train():\n    return 'loss'\n")
    paper_ref = PaperEntityRef(
        entity_id="sent-1",
        entity_type="sentence",
        section_id="sec-1",
        label="contrastive objective",
    )
    code_ref = CodeRangeRef(
        filepath="src/train.py",
        start_line=1,
        end_line=2,
        label="training function",
    )
    current = _message(
        "user",
        "How do these correspond?",
        context_refs=[paper_ref, code_ref],
    )
    fake = FakeModel(
        {
            "content": "The function is the implementation.",
            "citations": [
                paper_ref.model_dump(mode="json"),
                code_ref.model_dump(mode="json"),
            ],
        }
    )
    agent = CopilotAgent(
        model=fake,
        repo_resolver=lambda _: tmp_path,
        history_char_budget=2_000,
        context_char_budget=4_000,
    )

    result = asyncio.run(agent.answer(_paper(), _conversation([current]), current))

    prompt = fake.calls[-1]["prompt"]
    assert "contrastive objective" in prompt
    assert "1: def train():" in prompt
    assert result.citations == [paper_ref, code_ref]
    assert result.metadata.resolved_context_count == 2
    assert fake.calls[-1]["cwd"] == tmp_path.resolve()
    assert fake.calls[-1]["allowed_tools"] == ["Search", "ReadFile"]


def test_path_traversal_attachment_and_citation_are_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "secret.py"
    outside.write_text("SECRET = 'must not leak'\n")
    traversal = CodeRangeRef(
        filepath="../secret.py",
        start_line=1,
        end_line=1,
        label="outside file",
    )
    current = _message("user", "Read this.", context_refs=[traversal])
    fake = FakeModel(
        {
            "content": "That attachment is not available.",
            "citations": [traversal.model_dump(mode="json")],
        }
    )
    agent = CopilotAgent(model=fake, repo_resolver=lambda _: tmp_path)

    result = asyncio.run(agent.answer(_paper(), _conversation(), current))

    assert "SECRET" not in fake.calls[-1]["prompt"]
    assert "Unresolved attachments" in fake.calls[-1]["prompt"]
    assert result.citations == []
    assert result.metadata.unresolved_context_count == 1


def test_repository_tool_guard_rejects_outside_path(tmp_path: Path) -> None:
    guard = _repo_tool_guard(tmp_path)

    allowed = asyncio.run(guard("ReadFile", {"file_path": "src/train.py"}, None))
    denied = asyncio.run(guard("ReadFile", {"file_path": "../secret.py"}, None))

    assert allowed.behavior == "allow"
    assert denied.behavior == "deny"


def test_over_budget_history_advances_rolling_summary_boundary(
    tmp_path: Path,
) -> None:
    old_boundary = uuid4()
    messages = [
        _message("user", "already summarized", message_id=old_boundary),
        _message("assistant", "old answer " * 250),
        _message("user", "follow-up " * 250),
        _message("assistant", "newer answer " * 250),
        _message("user", "newer question " * 250),
    ]
    current = _message("user", "What should I inspect now?")
    fake = FakeModel({"content": "Inspect the trainer.", "citations": []})
    agent = CopilotAgent(
        model=fake,
        repo_resolver=lambda _: tmp_path,
        history_char_budget=2_000,
        context_char_budget=4_000,
    )

    result = asyncio.run(
        agent.answer(
            _paper(),
            _conversation(
                messages + [current],
                summary="Earlier durable facts.",
                boundary=old_boundary,
            ),
            current,
        )
    )

    assert len(fake.calls) == 2
    assert "Earlier durable facts." in fake.calls[0]["prompt"]
    assert result.summary == "Earlier: the user is tracing training."
    assert result.summarized_through_message_id == messages[3].id
    assert result.metadata.summarized_message_count == 3
    assert "DURABLE SUMMARY" in fake.calls[1]["prompt"]
    assert "What should I inspect now?" in fake.calls[1]["prompt"]


def test_packed_history_budget_includes_existing_summary(tmp_path: Path) -> None:
    current = _message("user", "What changed?")
    fake = FakeModel({"content": "The training flow changed.", "citations": []})
    agent = CopilotAgent(
        model=fake,
        repo_resolver=lambda _: tmp_path,
        history_char_budget=2_000,
        context_char_budget=4_000,
    )

    result = asyncio.run(
        agent.answer(
            _paper(),
            _conversation([current], summary="prior detail " * 500),
            current,
        )
    )

    answer_prompt = fake.calls[-1]["prompt"]
    packed = answer_prompt.split(
        "PACKED CONVERSATION HISTORY\n", 1
    )[1].split("\n\nCANONICAL EVIDENCE", 1)[0]
    assert len(packed) <= 2_000
    assert "[Earlier summary clipped at the packing limit.]" in packed
    assert result.summary == "prior detail " * 500


def test_invalid_canonical_citation_is_omitted(tmp_path: Path) -> None:
    current = _message("user", "Where is the missing section?")
    fake = FakeModel(
        {
            "content": "It is not present.",
            "citations": [
                {
                    "type": "paper_entity",
                    "entity_id": "made-up",
                    "entity_type": "section",
                    "label": "invented",
                }
            ],
        }
    )
    agent = CopilotAgent(model=fake, repo_resolver=lambda _: tmp_path)

    result = asyncio.run(agent.answer(_paper(), _conversation(), current))

    assert result.citations == []
    assert result.content == "It is not present."
    assert "We train an encoder and target encoder." in fake.calls[-1]["prompt"]
