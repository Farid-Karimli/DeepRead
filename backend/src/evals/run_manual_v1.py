"""
Runs the agent's `map_content_to_code` routine (the same routine used by the
user-driven "map content to code" selection pipeline) against the manually
annotated dataset in `annotations/manual_v1.json`.

For each annotation, the claim text is treated as the "content" the user
selected in the paper, and the agent is asked to map it to code snippets in
the paper's associated GitHub repository. No metrics are computed here -
this script only collects the raw predictions (plus timing) for later
evaluation.

Usage:
    python -m src.evals.run_manual_v1 [--limit N] [--output PATH]
"""

import argparse
import asyncio
import json
import os
import time
import traceback

from tqdm import tqdm

from src.agent import Agent
from src.utils import delete_temp_dir, normalize_github_repo_url

DEFAULT_ANNOTATIONS_PATH = os.path.join(
    os.path.dirname(__file__), "annotations", "manual_v1.json"
)
DEFAULT_OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "results", "manual_v1_predictions.json"
)


def build_context(paper: dict, annotation: dict) -> str:
    """Mirrors what a user would have available as surrounding context
    when selecting a claim in the paper (title, abstract, section)."""
    return (
        f"Paper title: {paper.get('title', '')}\n"
        f"Paper abstract: {paper.get('abstract', '')}\n"
        f"Section: {annotation.get('section_ref', '')}"
    )


async def run_annotation(agent: Agent, paper: dict, annotation: dict, repo_url: str) -> dict:
    record = {
        "paper_id": paper.get("paper_id"),
        "annotation_id": annotation.get("annotation_id"),
        "claim_text": annotation.get("claim_text"),
        "section_ref": annotation.get("section_ref"),
        "ground_truth_verdict": annotation.get("verdict"),
        "ground_truth_locations": annotation.get("locations", []),
        "prediction": None,
        "error": None,
        "duration_seconds": None,
    }

    started_at = time.perf_counter()
    try:
        prediction = await agent.map_content_to_code(
            content=annotation.get("claim_text", ""),
            repo_url=repo_url,
            context=build_context(paper, annotation),
        )
        record["prediction"] = prediction
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        record["duration_seconds"] = time.perf_counter() - started_at

    return record


async def run(annotations_path: str, output_path: str, limit: int | None = None) -> None:
    with open(annotations_path, "r") as f:
        data = json.load(f)

    papers = data.get("papers", [])

    tasks = []
    for paper in papers:
        repo_url = normalize_github_repo_url((paper.get("repo_path") or "").rstrip(". "))
        if repo_url is None:
            print(f"Skipping paper {paper.get('paper_id')}: invalid repo_path {paper.get('repo_path')!r}")
            continue
        for annotation in paper.get("annotations", []):
            tasks.append((paper, annotation, repo_url))

    if limit is not None:
        tasks = tasks[:limit]

    agent = Agent()
    results = []
    processed_repo_urls = set()

    try:
        for paper, annotation, repo_url in tqdm(tasks, desc="Running agent on annotations"):
            record = await run_annotation(agent, paper, annotation, repo_url)
            results.append(record)
            processed_repo_urls.add(repo_url)
    finally:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"Wrote {len(results)} predictions to {output_path}")

        for repo_url in processed_repo_urls:
            repo_name = repo_url.split("/")[-1].replace(".git", "")
            delete_temp_dir(os.path.join(os.path.dirname(__file__), "..", "temp", repo_name))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", default=DEFAULT_ANNOTATIONS_PATH, help="Path to the annotations JSON file")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH, help="Path to write predictions JSON to")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of annotations processed (for smoke testing)")
    args = parser.parse_args()

    asyncio.run(run(args.annotations, args.output, args.limit))


if __name__ == "__main__":
    main()
