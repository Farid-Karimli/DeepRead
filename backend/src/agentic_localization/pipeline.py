"""
Planner + optional resolver. Exposes the same `map_content_to_code` entry point as `Agent`.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Literal

from src.observability import init_weave, log_summary, op
from src.types import ContentToCodeResult
from src.utils import clone_repo_to_temp_dir

from .planner import Planner
from .repo_map import DEFAULT_CACHE_DIR, load_or_build
from .resolver import Resolver
from .utils import planner_verdict_skips_resolve

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

init_weave()

PipelineKind = Literal["planner_only", "planner_menu", "planner_crawl"]


class PlanResolvePipeline:
    """Planner (agent 1) plus optional resolver (agent 2)."""

    def __init__(
        self,
        model: str = "sonnet",
        stream_events: bool = False,
        temperature: float = 0.0,
        kind: PipelineKind = "planner_menu",
        resolve_model: str | None = None,
        cache_dir: str | Path = DEFAULT_CACHE_DIR,
    ) -> None:
        self.model = model
        self.stream_events = stream_events
        self.temperature = temperature
        self.kind = kind
        self.cache_dir = cache_dir
        self.planner = Planner(
            model=model, temperature=temperature, cache_dir=cache_dir
        )
        rmodel = resolve_model or model
        resolver_kind = (
            "menu" if kind == "planner_menu" else "guided-crawl"
        )
        self.resolver = Resolver(
            model=rmodel,
            temperature=temperature,
            cache_dir=cache_dir,
            kind=resolver_kind,
        )

    @op(name="pipeline_map_content_to_code")
    async def map_content_to_code(
        self,
        content: str | bytes,
        repo_url: str,
        context: str = "",
        top_k: int = 5,
        memory_hints: list[dict] | None = None,
    ) -> dict:
        if not isinstance(content, str):
            raise TypeError("PlanResolvePipeline only supports str content")

        if self.kind == "planner_only":
            return await self.planner.map_content_to_code(
                content=content,
                repo_url=repo_url,
                context=context,
                top_k=top_k,
                memory_hints=memory_hints,
            )

        started_at = time.perf_counter()
        local_code_path = clone_repo_to_temp_dir(repo_url)
        repo_map = load_or_build(
            local_code_path, repo_url=repo_url, cache_dir=self.cache_dir
        )

        gen = await self.planner.get_candidates(
            repo_map,
            content,
            context,
            memory_hints=memory_hints,
        )
        verdict = (gen.get("verdict") or "").strip()
        if planner_verdict_skips_resolve(verdict):
            logger.info("pipeline: skipping resolver verdict=%s", verdict)
            snippets = []
        else:
            snippets = await self.resolver.resolve(
                content=content,
                context=context,
                candidates=gen,
                repo_map=repo_map,
                repo_root=Path(local_code_path),
            )
            if top_k and len(snippets) > top_k:
                snippets = snippets[:top_k]

        final = ContentToCodeResult(
            reasoning=gen.get("reasoning") or "",
            verdict=verdict,
            code_snippets=snippets,
        )

        generate_metrics = gen.get("generate_metrics") or {}
        duration_s = round(time.perf_counter() - started_at, 3)
        process_metrics = {
            "num_tool_calls": 0,
            "tool_sequence": [],
            "num_searches": 0,
            "num_reads": 0,
            "num_unique_files_read": 0,
            "files_read": [],
            "search_patterns": [],
            "first_search_step": None,
            "first_read_step": None,
            "search_before_read": None,
            "duration_s": duration_s,
            "num_errors": 0,
            "planner": True,
            "pipeline_kind": self.kind,
            "api": generate_metrics.get("api"),
            "model": generate_metrics.get("model"),
            "resolve_model": self.resolver.model,
            "repo_map_files": generate_metrics.get("repo_map_files"),
            "minimal_view_chars": generate_metrics.get("minimal_view_chars"),
            "minimal_view_est_tokens": generate_metrics.get(
                "minimal_view_est_tokens"
            ),
            "usage": generate_metrics.get("usage"),
            "planner_generate_duration_s": generate_metrics.get("duration_s"),
        }
        last = getattr(self.resolver, "_last_metrics", None) or {}
        if last:
            process_metrics["num_tool_calls"] = last.get("tool_calls", 0)
            process_metrics["resolver_tool_turns"] = last.get("tool_turns")
            process_metrics["resolver_llm_duration_s"] = last.get("duration_s")

        result = final.model_dump()
        result["planner_candidates"] = gen.get("candidates") or []
        result["tool_trace"] = []
        result["process_metrics"] = process_metrics

        log_summary("process_metrics", process_metrics)
        log_summary(
            "prediction_summary",
            {
                "verdict": result.get("verdict"),
                "num_snippets": len(result.get("code_snippets") or []),
                "top_filepath": (
                    (result.get("code_snippets") or [{}])[0].get("filepath")
                    if result.get("code_snippets")
                    else None
                ),
            },
        )
        logger.info(
            "pipeline: done kind=%s duration=%.2fs verdict=%s snippets=%s",
            self.kind,
            duration_s,
            result.get("verdict"),
            len(result.get("code_snippets") or []),
        )
        return result
