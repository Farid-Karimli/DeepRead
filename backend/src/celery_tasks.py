import asyncio
import logging
import time

from src import process_pdf
from celery import Celery
from pydantic import BaseModel
from io import BytesIO


from src.agent import Agent
from src.db import update_paper_metadata
from src.paper_analysis_cache import get_cached_result, set_cached_result
from src.config import REDIS_URL, SUPABASE_URL, SUPABASE_KEY
from src.process_pdf import ProcessedPdf, papermage_process

logger = logging.getLogger(__name__)

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
    processed_pdf: ProcessedPdf = papermage_process(file_input=file_raw)
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
    cached = get_cached_result(paper_id)
    if cached is not None:
        logger.info("paper analysis cache hit paper_id=%s file=%s", paper_id, label)
        return cached

    logger.info("paper analysis cache miss paper_id=%s file=%s", paper_id, label)

    logger.info("using papermage to process pdf")
    papermage_result: ProcessedPdf = papermage_process(file_input=paper_raw)
    logger.info("paper processed.")

    agent = Agent()
    analysis_result = asyncio.run(agent.analyze_paper(file_input=paper_raw, papermage_process_result=papermage_result))
    set_cached_result(paper_id, analysis_result, papermage_result=papermage_result)

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
        update_paper_metadata(
            paper_id,
            paper_title=title if isinstance(title, str) else None,
            github_link=link if isinstance(link, str) else None,
        )
    unified_result = {
        "analysis": analysis_result,
        "processed": papermage_result
    }
    return unified_result

@celery.task(name='map_content')
def map_content_task(
    content: str | bytes | BytesIO,
    repo_url: str,
    context: str
):
    agent = Agent()
    result = asyncio.run(agent.map_content_to_code(
        content=content,
        repo_url=repo_url,
        context=context
    ))
    return result

@celery.task(name='map_code_to_content')
def map_code_to_content_task(
    code: str,
    paper_id: str
):
    agent = Agent()
    result = asyncio.run(agent.map_code_to_content(
        code=code,
        paper_id=paper_id
    ))
    return result