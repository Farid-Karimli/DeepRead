import asyncio
import logging
import os
import time

from celery import Celery

from deepread.agent import Agent
from deepread.paper_analysis_cache import get_cached_result, set_cached_result
from deepread.config import REDIS_URL

logger = logging.getLogger(__name__)


celery = Celery(
    __name__,
    broker=REDIS_URL,
    backend=REDIS_URL,
)

@celery.task(name="test_task")
def test_task():
    print(f"Waiting for 5 seconds...")
    time.sleep(5)
    print(f"Done waiting")
    return "Done waiting"


@celery.task(name="analyze_paper")
def analyze_paper_task(
    paper_content: str,
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
    agent = Agent()
    result = asyncio.run(agent.analyze_paper(paper_content))
    set_cached_result(paper_id, result)
    return result