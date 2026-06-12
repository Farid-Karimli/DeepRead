import asyncio
import json
import logging
import time

from src.types import (
    CodeToContentInputs,
    CodeToContentResult,
    ContentToCodeInputs,
    ContentToCodeResult,
    KeySectionsResult,
    PaperMappingRecord,
    PaperMageResult,
)

from celery import Celery
from pydantic import BaseModel
from io import BytesIO

from src.agent import Agent
from src.db import get_paper_record_by_id, upsert_mapping_result, upsert_paper
from src.config import REDIS_URL

logger = logging.getLogger(__name__)


def _papermage_process(file_input) -> PaperMageResult:
    """Defer papermage/OpenCV import until a PDF task runs."""
    from src.process_pdf import papermage_process

    return papermage_process(file_input=file_input)

celery = Celery(
    __name__,
    broker=REDIS_URL,
    backend=REDIS_URL,
)
    
class AgentTaskResult(BaseModel):
    paper_title: str | None = None
    github_repo_url: str | None = None
    code_result: dict | None = None
    
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
        "processed": papermage_result
    }

    upsert_paper(
        paper_id=paper_id,
        paper_title=title if isinstance(title, str) else None,
        github_link=link if isinstance(link, str) else None,
        analysis_result=analysis_result,
        papermage_result=papermage_result
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
):
    agent = Agent()
    result = asyncio.run(agent.map_content_to_code(
        content=content,
        repo_url=repo_url,
        context=context
    ))

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
            code_snippet=result.get('code_snippet'), 
            reasoning=result.get("reasoning"), 
            verdict=result.get("verdict"),
        ),
        paper_id=paper_id
    )
    upsert_mapping_result(record)
    return result

@celery.task(name='map_code_to_content')
def map_code_to_content_task(
    code: str,
    paper_id: str,
    cache_key: str,
):
    agent = Agent()
    paper_record = get_paper_record_by_id(paper_id)
    if paper_record is None:
        raise ValueError(f"No paper record found for id {paper_id}.")

    result = asyncio.run(agent.map_code_to_content(
        code=code,
        paper_record=paper_record
    ))

    sections = result.get("sections", []) if isinstance(result, dict) else []
    record = PaperMappingRecord(
        mapping_type="code_to_content",
        cache_key=cache_key,
        paper_id=paper_id, 
        inputs=CodeToContentInputs(code=code),
        outputs=CodeToContentResult(sections=sections),
    )
    upsert_mapping_result(record)
    return sections