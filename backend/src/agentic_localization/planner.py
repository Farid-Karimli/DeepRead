"""
Planner: agent 1 of the two-agent localization pipeline.

Mirrors `src.agent.Agent.map_content_to_code`, with one deliberate difference:
the planner gets **no tools**. The repo map's minimal view is serialized into the
prompt, so picking a file and an anchor symbol is a single call instead of a
Search / ReadFile crawl. Line numbers come from the map's symbol table rather
than from the model, so the planner cannot hallucinate a span.

Output is `ContentToCodeResult`-shaped, so `src.evals.evaluate` scores it
unchanged. Until the resolver (agent 2) lands, each prediction's span is the
whole anchor symbol.

    python -m src.agentic_localization.planner        # smoke test on one annotation
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from src.agent_utils import _parse_json_result, planner_schema
from src.observability import ToolTraceCollector, init_weave, log_summary, op
from src.prompts import build_planner_prompt
from src.types import ContentToCodeResult
from src.utils import clone_repo_to_temp_dir

from .repo_map import DEFAULT_CACHE_DIR, estimate_tokens, load_or_build, render_minimal_view
from .schema import FileRecord, RepoMap, SymbolRecord

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

init_weave()

# Snippet bodies are for the resolver and for eyeballing predictions; the metrics
# only read line numbers, so there is no reason to carry a 600-line class.
MAX_SNIPPET_LINES = 200

PLANNER_SYSTEM_PROMPT = (
    "You localize content from scientific papers to the code that implements it. "
    "You work from a serialized map of the repository, not from the repository itself. "
    "You reply with a single JSON object matching the requested schema and nothing else."
)


class Planner:
    """Picks the file and anchor symbol for a piece of paper content, using a
    serialized repo map instead of repository tool calls."""

    def __init__(
        self,
        model: str = "sonnet",
        cache_dir: str | Path = DEFAULT_CACHE_DIR,
        max_candidates: int = 5,
    ) -> None:
        self.model = model
        self.cache_dir = cache_dir
        self.max_candidates = max_candidates

    @op
    async def localize(
        self,
        content: str,
        repo_url: str,
        context: str = "",
        top_k: int = 5,
    ) -> dict:
        """Map one piece of paper content to anchor symbols in the repository.

        Args:
            content: A piece of text from the paper.
            repo_url: The paper's GitHub repository.
            context: Surrounding context (nearby text, abstract, section header).
            top_k: Maximum number of candidates to keep.
        """
        started_at = time.perf_counter()

        local_code_path = clone_repo_to_temp_dir(repo_url)
        repo_map = load_or_build(local_code_path, repo_url=repo_url, cache_dir=self.cache_dir)
        blob = render_minimal_view(repo_map)

        prompt = build_planner_prompt(
            content=content,
            context=context,
            repo_map_blob=blob,
            max_candidates=self.max_candidates,
        )
        logger.info(
            "localize: prompt prepared chars=%d repo_map_files=%d blob_tokens=~%d tools=%s",
            len(prompt),
            len(repo_map.files),
            estimate_tokens(blob),
            [],
        )

        options = ClaudeAgentOptions(
            model=self.model,
            # `tools=[]` drops Claude Code's tool definitions from the request.
            # `allowed_tools=[]` alone only withholds permission — the schemas are
            # still sent, and they cost ~26k input tokens per call.
            tools=[],
            allowed_tools=[],
            max_turns=1,
            system_prompt=PLANNER_SYSTEM_PROMPT,
            setting_sources=[],
            cwd=local_code_path,
            output_format={
                "type": "json_schema",
                "json_schema": planner_schema,
            },
        )

        parsed_result = None
        usage: dict[str, Any] | None = None
        cost_usd = None
        trace = ToolTraceCollector()
        async for message in query(prompt=prompt, options=options):
            trace.ingest(message)
            if isinstance(message, ResultMessage):
                usage = message.usage if isinstance(message.usage, dict) else None
                cost_usd = message.total_cost_usd
                parsed_result = _parse_json_result(message.result)
                if parsed_result is None:
                    cleaned = message.result.replace("```json", "").replace("```", "").strip()
                    logger.warning("localize: failed to parse JSON result raw=%s", cleaned)

        if not isinstance(parsed_result, dict):
            parsed_result = {}

        candidates = parsed_result.get("candidates")
        snippets, resolution = self._resolve_candidates(
            candidates if isinstance(candidates, list) else [],
            repo_map,
            Path(local_code_path),
            top_k=top_k,
        )

        final = ContentToCodeResult(
            reasoning=parsed_result.get("reasoning") or "",
            verdict=parsed_result.get("verdict") or "",
            code_snippets=snippets,
        )

        process_metrics = trace.summarize()
        process_metrics.update(
            {
                "planner": True,
                "repo_map_files": len(repo_map.files),
                "minimal_view_chars": len(blob),
                "minimal_view_est_tokens": estimate_tokens(blob),
                "usage": usage,
                "total_cost_usd": cost_usd,
                **resolution,
            }
        )

        result = final.model_dump()
        result["planner_candidates"] = candidates if isinstance(candidates, list) else []
        result["tool_trace"] = trace.to_list()
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
            "localize: completed duration=%.2fs verdict=%s candidates=%s unresolved_files=%s "
            "unresolved_anchors=%s",
            time.perf_counter() - started_at,
            result.get("verdict"),
            len(result.get("code_snippets") or []),
            resolution["num_unresolved_files"],
            resolution["num_unresolved_anchors"],
        )
        return result

    async def map_content_to_code(
        self,
        content: str,
        repo_url: str,
        context: str,
        top_k: int = 5,
    ) -> dict:
        """Same signature as `Agent.map_content_to_code`, so `src.evals.run` can
        swap the planner in for the single-agent baseline."""
        return await self.localize(
            content=content, repo_url=repo_url, context=context, top_k=top_k
        )

    # ----------------------------------------------------------------------- #
    # anchor -> span
    # ----------------------------------------------------------------------- #

    def _resolve_candidates(
        self,
        candidates: list[Any],
        repo_map: RepoMap,
        repo_root: Path,
        top_k: int,
    ) -> tuple[list[dict], dict[str, int]]:
        """Turn (filepath, anchor_symbol) pairs into line ranges via the symbol
        table. Unresolved anchors are counted rather than silently dropped —
        they are the planner's hallucination rate."""
        snippets: list[dict] = []
        seen: set[tuple[str, int, int]] = set()
        unresolved_files = 0
        unresolved_anchors = 0

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            record = _match_file(repo_map, candidate.get("filepath") or "")
            if record is None:
                unresolved_files += 1
                continue

            anchor = (candidate.get("anchor_symbol") or "").strip()
            symbol = repo_map.symbol(anchor, filepath=record.filepath) if anchor else None
            if symbol is None:
                if anchor:
                    unresolved_anchors += 1
                symbol = _fallback_span(record)
            if symbol is None:
                continue

            key = (record.filepath, symbol.start_line, symbol.end_line)
            if key in seen:
                continue
            seen.add(key)
            snippets.append(
                {
                    "content": _read_span(repo_root / record.filepath, symbol),
                    "filepath": record.filepath,
                    "start_line": symbol.start_line,
                    "end_line": symbol.end_line,
                }
            )
            if len(snippets) >= top_k:
                break

        return snippets, {
            "num_planner_candidates": len(candidates),
            "num_unresolved_files": unresolved_files,
            "num_unresolved_anchors": unresolved_anchors,
        }


def _match_file(repo_map: RepoMap, filepath: str) -> FileRecord | None:
    """Exact match, then a forgiving suffix/basename match, so a planner that
    drops a leading directory is not scored as a miss."""
    filepath = (filepath or "").strip().lstrip("./")
    if not filepath:
        return None
    record = repo_map.file(filepath)
    if record is not None:
        return record

    suffix_hits = [f for f in repo_map.files if f.filepath.endswith("/" + filepath)]
    if len(suffix_hits) == 1:
        return suffix_hits[0]

    name = Path(filepath).name
    name_hits = [f for f in repo_map.files if Path(f.filepath).name == name]
    if len(name_hits) == 1:
        return name_hits[0]
    return None


def _fallback_span(record: FileRecord) -> SymbolRecord | None:
    """Span for a file the planner picked without a usable anchor: the largest
    module scope for a script-style file, otherwise the whole file."""
    if record.module_scopes:
        return max(record.module_scopes, key=lambda s: s.end_line - s.start_line)
    if not record.loc:
        return None
    return SymbolRecord(
        name="<file>",
        qualified_name=f"<file>:{record.filepath}",
        node_type="file",
        start_line=1,
        end_line=record.loc,
    )


def _read_span(path: Path, symbol: SymbolRecord) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    body = lines[symbol.start_line - 1 : symbol.end_line]
    if len(body) > MAX_SNIPPET_LINES:
        omitted = len(body) - MAX_SNIPPET_LINES
        body = body[:MAX_SNIPPET_LINES] + [f"# ... {omitted} more lines"]
    return "\n".join(body)


if __name__ == "__main__":
    annotations_path = Path(__file__).parents[1] / "evals" / "annotations" / "manual_v1.json"
    paper = json.loads(annotations_path.read_text())["papers"][0]
    annotation = paper["annotations"][0]

    planner = Planner()
    prediction = asyncio.run(
        planner.localize(
            content=annotation["claim_text"],
            repo_url=paper["repo_path"].rstrip(". "),
            context=f"Paper title: {paper.get('title', '')}\nSection: {annotation.get('section_ref', '')}",
        )
    )

    print(json.dumps({k: v for k, v in prediction.items() if k != "tool_trace"}, indent=2))
    print("\nground truth:", json.dumps(annotation.get("locations"), indent=2))
