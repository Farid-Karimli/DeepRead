import time
import asyncio
from celery import Celery

from deepread.agent import Agent

celery = Celery(
    __name__,
    broker="redis://127.0.0.1:6379/0",
    backend="redis://127.0.0.1:6379/0"
)

@celery.task(name="test_task")
def test_task():
    print(f"Waiting for 5 seconds...")
    time.sleep(5)
    print(f"Done waiting")
    return "Done waiting"


@celery.task(name="analyze_paper")
def analyze_paper_task(paper_content: str):
    """
    Analyzes paper content for processing. Calls the agent to analyze the paper content and returns the result.
    Args:
        paper_content: The content of the paper to analyze.
    Returns:
        A dictionary containing the analysis result.
    """
    agent = Agent()
    result = asyncio.run(agent.analyze_paper(paper_content))
    return result