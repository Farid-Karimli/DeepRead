"""
Planner: agent 1 of the two-agent localization pipeline.

Generation (`get_candidates`): one Anthropic call over the minimal repo map.
Resolution (`resolve_anchors`): map (filepath, anchor_symbol) → line spans.

    python -m src.agentic_localization.planner
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic

from src.agent_utils import _parse_json_result, planner_schema
from src.config import ANTHROPIC_API_KEY
from src.observability import init_weave, log_summary, op
from src.prompts import build_planner_prompt
from src.types import ContentToCodeResult
from src.utils import clone_repo_to_temp_dir

from .repo_map import DEFAULT_CACHE_DIR, estimate_tokens, load_or_build, render_minimal_view
from .schema import FileRecord, RepoMap, SymbolRecord
from .utils import resolve_model

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

init_weave()

MAX_SNIPPET_LINES = 200

PLANNER_SYSTEM_PROMPT = (
    "You localize content from scientific papers to the code that implements it. "
    "You work from a serialized map of the repository, not from the repository itself. "
    "You reply with a single JSON object matching the requested schema and nothing else."
)

def _usage_dict(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage
    return {
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
    }


class Planner:
    def __init__(
        self,
        model: str = "sonnet",
        cache_dir: str | Path = DEFAULT_CACHE_DIR,
        max_candidates: int = 5,
        temperature: float = 0.0,
    ) -> None:
        self.model = model
        self.cache_dir = cache_dir
        self.max_candidates = max_candidates
        self.temperature = temperature
        self._client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    @op(name="planner_get_candidates")
    async def get_candidates(
        self,
        repo_map: RepoMap,
        content: str,
        context: str = "",
    ) -> dict[str, Any]:
        """LLM step: file + anchor hypotheses from the minimal map (no line spans)."""
        started_at = time.perf_counter()
        blob = render_minimal_view(repo_map)
        model_id = resolve_model(self.model)

        prompt = build_planner_prompt(
            content=content,
            context=context,
            repo_map_blob=blob,
            max_candidates=self.max_candidates,
        )
        logger.info(
            "get_candidates: chars=%d files=%d blob_tokens=~%d model=%s",
            len(prompt),
            len(repo_map.files),
            estimate_tokens(blob),
            model_id,
        )

        message = await self._client.messages.create(
            model=model_id,
            max_tokens=4096,
            temperature=self.temperature,
            system=PLANNER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            output_config={
                "format": {"type": "json_schema", "schema": planner_schema},
            },
        )

        raw_text = ""
        if isinstance(message.content, list) and message.content:
            raw_text = getattr(message.content[0], "text", "") or ""
        parsed = _parse_json_result(raw_text)
        if parsed is None and raw_text:
            logger.warning("get_candidates: failed to parse JSON raw=%s", raw_text[:500])
        if not isinstance(parsed, dict):
            parsed = {}

        usage = _usage_dict(message.usage)
        candidates = parsed.get("candidates")
        if not isinstance(candidates, list):
            candidates = []

        duration_s = round(time.perf_counter() - started_at, 3)
        generate_metrics = {
            "duration_s": duration_s,
            "model": model_id,
            "api": "anthropic",
            "repo_map_files": len(repo_map.files),
            "minimal_view_chars": len(blob),
            "minimal_view_est_tokens": estimate_tokens(blob),
            "usage": usage,
            "num_candidates": len(candidates),
            "verdict": parsed.get("verdict") or "",
        }
        log_summary("planner_generate", generate_metrics)
        logger.info(
            "get_candidates: done duration=%.2fs verdict=%s num_candidates=%s in=%s out=%s",
            duration_s,
            generate_metrics["verdict"],
            len(candidates),
            (usage or {}).get("input_tokens"),
            (usage or {}).get("output_tokens"),
        )

        return {
            "reasoning": parsed.get("reasoning") or "",
            "verdict": parsed.get("verdict") or "",
            "candidates": candidates,
            "generate_metrics": generate_metrics,
        }

    @op(name="planner_resolve_anchors")
    def resolve_anchors(
        self,
        candidates: list[Any],
        repo_map: RepoMap,
        repo_root: Path | str,
        top_k: int = 5,
    ) -> tuple[list[dict], dict[str, Any]]:
        """Map step: anchor symbols → snippet line ranges (whole symbol for now)."""
        started_at = time.perf_counter()
        snippets, resolution = self._resolve_candidates(
            candidates,
            repo_map,
            Path(repo_root),
            top_k=top_k,
        )
        duration_s = round(time.perf_counter() - started_at, 3)
        resolve_metrics = {
            "duration_s": duration_s,
            "num_snippets": len(snippets),
            **resolution,
        }
        log_summary("planner_resolve", resolve_metrics)
        logger.info(
            "resolve_anchors: done duration=%.2fs snippets=%s unresolved_files=%s unresolved_anchors=%s",
            duration_s,
            len(snippets),
            resolution["num_unresolved_files"],
            resolution["num_unresolved_anchors"],
        )
        return snippets, resolve_metrics

    @op(name="planner_localize")
    async def localize(
        self,
        content: str,
        repo_url: str,
        context: str = "",
        top_k: int = 5,
    ) -> dict:
        """Generate candidates, resolve anchors, return eval-shaped prediction."""
        started_at = time.perf_counter()

        local_code_path = clone_repo_to_temp_dir(repo_url)
        repo_map = load_or_build(local_code_path, repo_url=repo_url, cache_dir=self.cache_dir)

        gen = await self.get_candidates(repo_map, content, context)
        snippets, resolve_metrics = self.resolve_anchors(
            gen["candidates"], repo_map, local_code_path, top_k=top_k
        )

        final = ContentToCodeResult(
            reasoning=gen["reasoning"],
            verdict=gen["verdict"],
            code_snippets=snippets,
        )

        generate_metrics = gen["generate_metrics"]
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
            "api": generate_metrics.get("api"),
            "model": generate_metrics.get("model"),
            "repo_map_files": generate_metrics.get("repo_map_files"),
            "minimal_view_chars": generate_metrics.get("minimal_view_chars"),
            "minimal_view_est_tokens": generate_metrics.get("minimal_view_est_tokens"),
            "usage": generate_metrics.get("usage"),
            "planner_generate_duration_s": generate_metrics.get("duration_s"),
            "planner_resolve_duration_s": resolve_metrics.get("duration_s"),
            **{k: v for k, v in resolve_metrics.items() if k != "duration_s"},
        }

        result = final.model_dump()
        result["planner_candidates"] = gen["candidates"]
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
            "localize: done duration=%.2fs verdict=%s snippets=%s",
            duration_s,
            result.get("verdict"),
            len(result.get("code_snippets") or []),
        )
        return result

    async def map_content_to_code(
        self,
        content: str,
        repo_url: str,
        context: str = "",
        top_k: int = 5,
    ) -> dict:
        return await self.localize(
            content=content, repo_url=repo_url, context=context, top_k=top_k
        )

    def _resolve_candidates(
        self,
        candidates: list[Any],
        repo_map: RepoMap,
        repo_root: Path,
        top_k: int,
    ) -> tuple[list[dict], dict[str, int]]:
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
        planner.map_content_to_code(
            content=annotation["claim_text"],
            repo_url=paper["repo_path"].rstrip(". "),
            context=f"Paper title: {paper.get('title', '')}\nSection: {annotation.get('section_ref', '')}",
        )
    )

    print(json.dumps({k: v for k, v in prediction.items() if k != "tool_trace"}, indent=2))
    print("\nground truth:", json.dumps(annotation.get("locations"), indent=2))
