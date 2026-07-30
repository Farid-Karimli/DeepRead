import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

from src.types import (
    CodeToContentInputs,
    CodeToContentResult,
    ContentToCodeInputs,
    ContentToCodeMemorySnapshot,
    ContentToCodeResult,
    ConversationRecord,
    CopilotMessage,
    CopilotMessageMetadata,
    KeySectionsResult,
    PaperMappingRecord,
    PaperMageResult,
)

from celery import Celery
from pydantic import BaseModel
from io import BytesIO

from src.agent import Agent
from src.db import (
    ConversationConflictError,
    append_conversation_message,
    get_conversation_by_id,
    get_paper_record_by_id,
    get_recent_content_to_code_matches_by_paper_and_user,
    set_conversation_failed,
    set_conversation_idle,
    update_conversation_summary,
    upsert_mapping_result,
    upsert_paper,
)
from src.config import CONTENT_TO_CODE_MEMORY_MODE, REDIS_URL

logger = logging.getLogger(__name__)


def _papermage_process(file_input) -> PaperMageResult:
    """Defer papermage/OpenCV import until a PDF task runs."""
    from src.process_pdf import papermage_process

    return papermage_process(file_input=file_input)


def _new_copilot_agent():
    """Keep Copilot-only dependencies out of unrelated Celery task startup."""
    from src.copilot_agent import CopilotAgent

    return CopilotAgent()


def _retrieve_content_to_code_memory(
    *,
    paper_id: str,
    user_id: int,
) -> ContentToCodeMemorySnapshot:
    """Load the user's last three interactions; mapping agents stay DB-agnostic."""
    if CONTENT_TO_CODE_MEMORY_MODE != "recent":
        return ContentToCodeMemorySnapshot(strategy="off")

    try:
        from src.content_to_code_memory import retrieve_recent_prior_matches

        prior_matches = get_recent_content_to_code_matches_by_paper_and_user(
            paper_id,
            user_id,
        )
        snapshot = retrieve_recent_prior_matches(
            prior_matches=prior_matches,
        )
        return snapshot
    except Exception:
        # Mapping remains available if the experimental retrieval path fails.
        logger.exception(
            "content_to_code memory retrieval failed paper_id=%s user_id=%s",
            paper_id,
            user_id,
        )
        return ContentToCodeMemorySnapshot(strategy="recent")


celery = Celery(
    __name__,
    broker=REDIS_URL,
    backend=REDIS_URL,
)
    
class AgentTaskResult(BaseModel):
    paper_title: str | None = None
    github_repo_url: str | None = None
    code_result: dict | None = None


def _require_active_copilot_task(
    conversation: ConversationRecord,
    task_id: str,
) -> None:
    if (
        conversation.status != "processing"
        or conversation.active_task_id != task_id
    ):
        raise ConversationConflictError(
            "Copilot worker no longer owns the conversation: "
            f"conversation_id={conversation.id} task_id={task_id!r}"
        )


def _assistant_reply_for(
    conversation: ConversationRecord,
    user_message_id: UUID,
) -> CopilotMessage | None:
    return next(
        (
            message
            for message in conversation.messages
            if message.role == "assistant"
            and message.status == "complete"
            and message.in_reply_to == user_message_id
        ),
        None,
    )


def _copilot_result(
    *,
    conversation_id: int,
    user_message_id: UUID,
    assistant_message_id: UUID,
    idempotent: bool,
) -> dict[str, object]:
    return {
        "conversation_id": conversation_id,
        "user_message_id": str(user_message_id),
        "assistant_message_id": str(assistant_message_id),
        "status": "complete",
        "idempotent": idempotent,
    }


def _mark_copilot_failed(conversation_id: int, task_id: str) -> None:
    try:
        set_conversation_failed(conversation_id, task_id)
    except Exception:
        # Guarded updates deliberately reject stale workers. Preserve the
        # original task failure while retaining that rejection in worker logs.
        logger.warning(
            "Could not mark Copilot conversation failed "
            "conversation_id=%s task_id=%s",
            conversation_id,
            task_id,
            exc_info=True,
        )


@celery.task(bind=True, name="copilot_chat")
def copilot_chat_task(
    self,
    conversation_id: int,
    user_message_id: str,
) -> dict[str, object]:
    """Answer one queued user message while holding the conversation claim."""
    task_id = self.request.id
    if not task_id:
        raise RuntimeError("Copilot task requires a Celery task id")

    try:
        parsed_user_message_id = UUID(user_message_id)
        conversation = get_conversation_by_id(conversation_id)
        if conversation is None:
            raise ValueError(f"No conversation found for id {conversation_id}.")

        existing_reply = _assistant_reply_for(
            conversation,
            parsed_user_message_id,
        )
        if existing_reply is not None:
            if (
                conversation.status == "processing"
                and conversation.active_task_id == task_id
            ):
                set_conversation_idle(conversation_id, task_id)
            return _copilot_result(
                conversation_id=conversation_id,
                user_message_id=parsed_user_message_id,
                assistant_message_id=existing_reply.id,
                idempotent=True,
            )

        _require_active_copilot_task(conversation, task_id)

        paper = get_paper_record_by_id(conversation.paper_id)
        if paper is None:
            raise ValueError(
                f"No paper record found for id {conversation.paper_id}."
            )

        user_message = next(
            (
                message
                for message in conversation.messages
                if message.id == parsed_user_message_id
                and message.role == "user"
            ),
            None,
        )
        if user_message is None:
            raise ValueError(
                "No user message found for Copilot task: "
                f"conversation_id={conversation_id} "
                f"message_id={parsed_user_message_id}"
            )

        answer = asyncio.run(
            _new_copilot_agent().answer(paper, conversation, user_message)
        )

        # The agent call can be slow. Re-read before writing so a stale or
        # duplicate delivery cannot append after ownership has changed.
        latest = get_conversation_by_id(conversation_id)
        if latest is None:
            raise ValueError(f"No conversation found for id {conversation_id}.")
        _require_active_copilot_task(latest, task_id)

        existing_reply = _assistant_reply_for(
            latest,
            parsed_user_message_id,
        )
        if existing_reply is not None:
            set_conversation_idle(conversation_id, task_id)
            return _copilot_result(
                conversation_id=conversation_id,
                user_message_id=parsed_user_message_id,
                assistant_message_id=existing_reply.id,
                idempotent=True,
            )

        if (
            answer.summary is not None
            and answer.summarized_through_message_id is not None
        ):
            latest = update_conversation_summary(
                conversation_id,
                answer.summary,
                str(answer.summarized_through_message_id),
                task_id=task_id,
            )

        metadata = answer.metadata
        if isinstance(metadata, BaseModel):
            metadata_values = metadata.model_dump(exclude_none=True)
        elif isinstance(metadata, dict):
            metadata_values = dict(metadata)
        elif metadata is None:
            metadata_values = {}
        else:
            metadata_values = dict(metadata)
        metadata_values["task_id"] = task_id

        assistant_message = CopilotMessage(
            id=uuid4(),
            role="assistant",
            content=answer.content,
            created_at=datetime.now(UTC),
            status="complete",
            citations=answer.citations,
            in_reply_to=parsed_user_message_id,
            metadata=CopilotMessageMetadata.model_validate(metadata_values),
        )
        append_conversation_message(
            conversation_id,
            assistant_message,
            expected_version=latest.version,
        )
        set_conversation_idle(conversation_id, task_id)
        return _copilot_result(
            conversation_id=conversation_id,
            user_message_id=parsed_user_message_id,
            assistant_message_id=assistant_message.id,
            idempotent=False,
        )
    except Exception:
        _mark_copilot_failed(conversation_id, task_id)
        raise
    
@celery.task(name="test_task")
def test_task():
    print(f"Waiting for 5 seconds...")
    time.sleep(5)
    print(f"Done waiting")
    return "Done waiting"

@celery.task(name="process_pdf_papermage")
def process_pdf_task(
    file_raw: bytes | BytesIO,
):
    processed_pdf: PaperMageResult = _papermage_process(file_raw)
    return processed_pdf

@celery.task(name="analyze_paper")
def analyze_paper_task(
    paper_content: str,
    paper_raw: bytes | BytesIO,
    paper_id: str,
    original_filename: str | None = None,
):
    """
    Analyzes paper content for processing. Calls the agent to analyze the paper content and returns the result.

    Results are cached in Redis under ``paper_id`` (typically SHA-256 of raw file bytes from the upload).

    Args:
        paper_content: Normalized text extracted from the paper.
        paper_id: Stable identifier for the upload (e.g. hex SHA-256 of raw bytes).
        original_filename: Optional client filename for logs only (not used as cache key).
    Returns:
        A dictionary containing the analysis result.
    """
    label = original_filename or "(no filename)"
    # cached = get_cached_result(paper_id)
    # if cached is not None:
    #     logger.info("paper analysis cache hit paper_id=%s file=%s", paper_id, label)
    #     return cached

    #logger.info("paper analysis cache miss paper_id=%s file=%s", paper_id, label)

    logger.info("using papermage to process pdf")
    papermage_result: PaperMageResult = _papermage_process(paper_raw)
    logger.info("paper processed.")

    agent = Agent()
    analysis_result: KeySectionsResult = asyncio.run(agent.analyze_paper(file_input=paper_raw, papermage_process_result=papermage_result))

    title = None
    link = None
    if isinstance(analysis_result, dict):
        title = analysis_result.get("paper_title")
        link = analysis_result.get("github_repo_url")
        code_result = analysis_result.get("code_result")
        if not link and isinstance(code_result, dict):
            link = code_result.get("github_repo_url")
        if not title and isinstance(code_result, dict):
            ct = code_result.get("paper_title")
            if isinstance(ct, str):
                title = ct

    unified_result = {
        "analysis": analysis_result,
        "processed": papermage_result # Save the CANONICAL papermage result
    }

    upsert_paper(
        paper_id=paper_id,
        paper_title=title if isinstance(title, str) else None,
        github_link=link if isinstance(link, str) else None,
        analysis_result=analysis_result,
        papermage_result=papermage_result, # Save the CANONICAL papermage result
    )

    return unified_result

@celery.task(name='map_content_to_code')
def map_content_to_code_task(
    content: str | bytes | BytesIO,
    repo_url: str,
    context: str,
    cache_key: str,
    paper_id: str,
    box: dict,
    page_number: int,
    user_id: int,
):
    agent = Agent()
    memory_snapshot = _retrieve_content_to_code_memory(
        paper_id=paper_id,
        user_id=user_id,
    ) if isinstance(content, str) else ContentToCodeMemorySnapshot(strategy="off")
    memory_hints = (
        [hint.model_dump(mode="json") for hint in memory_snapshot.hints]
        if memory_snapshot.hints
        else None
    )
    if memory_hints:
        result = asyncio.run(agent.map_content_to_code(
            content=content,
            repo_url=repo_url,
            context=context,
            memory_hints=memory_hints,
        ))
    else:
        result = asyncio.run(agent.map_content_to_code(
            content=content,
            repo_url=repo_url,
            context=context,
        ))
    result["memory_snapshot"] = memory_snapshot.model_dump(mode="json")

    record = PaperMappingRecord(
        mapping_type="content_to_code",
        cache_key=cache_key,
        inputs=ContentToCodeInputs(
            content=content,
            repo_url=repo_url,
            context=context,
            box=box,
            page_number=page_number,
        ),
        outputs=ContentToCodeResult(
            code_snippets=result.get('code_snippets') or [],
            reasoning=result.get("reasoning"), 
            verdict=result.get("verdict"),
            memory_snapshot=memory_snapshot,
        ),
        paper_id=paper_id,
        created_by=user_id,
    )
    upsert_mapping_result(record)
    return result

@celery.task(name='map_code_to_content')
def map_code_to_content_task(
    code: str,
    paper_id: str,
    cache_key: str,
    start: int,
    end: int,
    filepath: str,
    user_id: int,
):
    agent = Agent()
    paper_record = get_paper_record_by_id(paper_id)
    if paper_record is None:
        raise ValueError(f"No paper record found for id {paper_id}.")

    result = asyncio.run(agent.map_code_to_content(
        code=code,
        paper_record=paper_record
    ))

    outputs = CodeToContentResult.model_validate(result) if isinstance(result, dict) else CodeToContentResult(
        verdict="Verdict not found",
        reasoning="Reasoning not found",
        matches=[],
    )
    record = PaperMappingRecord(
        mapping_type="code_to_content",
        cache_key=cache_key,
        paper_id=paper_id, 
        inputs=CodeToContentInputs(code=code, start=start, end=end, filepath=filepath),
        outputs=outputs,
        created_by=user_id,
    )
    upsert_mapping_result(record)
    return result
