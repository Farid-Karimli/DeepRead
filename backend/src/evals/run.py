"""
Runs the agent's `map_content_to_code` routine (the same routine used by the
user-driven "map content to code" selection pipeline) against the manually
annotated dataset in `annotations/manual_v1.json`.

For each annotation, the claim text is treated as the "content" the user
selected in the paper, and the agent is asked to map it to code snippets in
the paper's associated GitHub repository. No metrics are computed here -
this script only collects the raw predictions (plus timing and tool traces)
for later evaluation.

Usage:
    python -m src.evals.run [--limit N] [--output PATH] [--paper INDEX]
        [--memory off|recent]
"""

import argparse
import asyncio
import json
import os
import time
import traceback

from tqdm import tqdm

from src.agent import Agent
from src.agentic_localization.pipeline import PlanResolvePipeline, PipelineKind
from src.evals.memory import EvaluationMemory
from src.observability import attributes, init_weave, is_active, op
from src.types import ContentToCodeMemorySnapshot
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


@op(name="eval_run_annotation")
async def run_annotation(
    agent: Agent | PlanResolvePipeline,
    paper: dict,
    annotation: dict,
    repo_url: str,
    memory_snapshot: ContentToCodeMemorySnapshot | None = None,
) -> dict:
    record = {
        "paper_id": paper.get("paper_id"),
        "annotation_id": annotation.get("annotation_id"),
        "claim_text": annotation.get("claim_text"),
        "section_ref": annotation.get("section_ref"),
        "ground_truth_verdict": annotation.get("verdict"),
        "ground_truth_locations": annotation.get("locations", []),
        "prediction": None,
        "tool_trace": None,
        "process_metrics": None,
        "memory_snapshot": (
            memory_snapshot.model_dump(mode="json")
            if memory_snapshot is not None
            else None
        ),
        "error": None,
        "duration_seconds": None,
    }

    started_at = time.perf_counter()
    try:
        with attributes(
            {
                "paper_id": paper.get("paper_id"),
                "annotation_id": annotation.get("annotation_id"),
                "section_ref": annotation.get("section_ref"),
                "ground_truth_verdict": annotation.get("verdict"),
                "model": getattr(agent, "model", None),
            }
        ):
            kwargs = {
                "content": annotation.get("claim_text", ""),
                "repo_url": repo_url,
                "context": build_context(paper, annotation),
            }
            if memory_snapshot and memory_snapshot.hints:
                kwargs["memory_hints"] = [
                    hint.model_dump(mode="json") for hint in memory_snapshot.hints
                ]
            prediction = await agent.map_content_to_code(**kwargs)
        # Lift process instrumentation out of the prediction payload so
        # evaluate.py keeps seeing a clean ContentToCodeResult-shaped dict.
        if isinstance(prediction, dict):
            record["tool_trace"] = prediction.pop("tool_trace", None)
            record["process_metrics"] = prediction.pop("process_metrics", None)
        record["prediction"] = prediction
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        record["duration_seconds"] = time.perf_counter() - started_at

    return record


async def run(
    annotations_path: str,
    output_path: str,
    limit: int | None = None,
    model: str = "sonnet",
    paper_index: int | None = None,
    pipeline: PipelineKind | None = None,
    memory_mode: str = "off",
) -> None:
    init_weave()
    print(f"Weave tracing active={is_active()}")

    with open(annotations_path, "r") as f:
        data = json.load(f)

    papers = data.get("papers", [])

    if paper_index is not None:
        if paper_index < 1 or paper_index > len(papers):
            raise ValueError(
                f"--paper {paper_index} is out of range; annotations file has {len(papers)} paper(s)"
            )
        papers = [papers[paper_index - 1]]

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

    if pipeline:
        agent = PlanResolvePipeline(model=model, kind=pipeline)
    else:
        agent = Agent(model=model)
    memory = EvaluationMemory() if memory_mode == "recent" else None
    results = []
    processed_repo_urls = set()

    try:
        for paper, annotation, repo_url in tqdm(tasks, desc="Running agent on annotations"):
            paper_id = paper.get("paper_id", "")
            claim_text = annotation.get("claim_text", "")
            context = build_context(paper, annotation)
            memory_snapshot = (
                memory.retrieve(paper_id) if memory is not None else None
            )
            record = await run_annotation(
                agent,
                paper,
                annotation,
                repo_url,
                memory_snapshot=memory_snapshot,
            )
            results.append(record)
            if memory is not None:
                memory.remember(
                    paper_id=paper_id,
                    annotation_id=annotation.get("annotation_id", ""),
                    content=claim_text,
                    context=context,
                    repo_url=repo_url,
                    prediction=record.get("prediction"),
                )
            processed_repo_urls.add(repo_url)
            # Checkpoint after each annotation so a long run isn't lost on interrupt.
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w") as f:
                json.dump(results, f, indent=2)
    finally:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"Wrote {len(results)} predictions to {output_path}")

        # Quick process-metric rollup so you can see search-vs-read behavior without W&B.
        search_before = [
            r.get("process_metrics", {}).get("search_before_read")
            for r in results
            if isinstance(r.get("process_metrics"), dict)
        ]
        known = [v for v in search_before if isinstance(v, bool)]
        if known:
            n_search_first = sum(1 for v in known if v)
            print(
                f"Process: search_before_read={n_search_first}/{len(known)} "
                f"({100 * n_search_first / len(known):.0f}%)"
            )

        for repo_url in processed_repo_urls:
            repo_name = repo_url.split("/")[-1].replace(".git", "")
            delete_temp_dir(os.path.join(os.path.dirname(__file__), "..", "temp", repo_name))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", default=DEFAULT_ANNOTATIONS_PATH, help="Path to the annotations JSON file")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH, help="Path to write predictions JSON to")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of annotations processed (for smoke testing)")
    parser.add_argument("--model", type=str, default="sonnet", help="Model name (sonnet, opus, haiku, fable)")
    parser.add_argument(
        "--paper",
        type=int,
        default=None,
        help="Only run annotations for the paper at this 1-indexed position in the annotations file's papers list",
    )
    parser.add_argument(
        "--planner",
        action="store_true",
        help="Use the repo-map planner only (same as --pipeline planner_only)",
    )
    parser.add_argument(
        "--pipeline",
        choices=["planner_only", "planner_menu", "planner_crawl"],
        default=None,
        help="Two-agent pipeline: planner_only | planner_menu | planner_crawl",
    )
    parser.add_argument(
        "--memory",
        choices=["off", "recent"],
        default="off",
        help="Include the last three interactions from the same paper",
    )
    args = parser.parse_args()
    pipeline = args.pipeline
    if pipeline is None and args.planner:
        pipeline = "planner_only"

    asyncio.run(
        run(
            args.annotations,
            args.output,
            args.limit,
            args.model,
            args.paper,
            pipeline=pipeline,
            memory_mode=args.memory,
        )
    )


if __name__ == "__main__":
    main()
