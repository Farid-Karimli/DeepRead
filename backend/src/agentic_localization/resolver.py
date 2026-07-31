import asyncio
import json
import logging
import time
from pathlib import Path
from typing import TypedDict

from anthropic import AsyncAnthropic

from src.agent_utils import _parse_json_result, resolver_schema
from src.config import ANTHROPIC_API_KEY
from src.observability import init_weave, log_summary, op
from src.prompts import build_resolver_crawl_prompt, build_resolver_menu_prompt
from src.types import CodeSnippet
from src.utils import clone_repo_to_temp_dir

from .schema import CandidateSpan, RepoMap
from .repo_map import DEFAULT_CACHE_DIR, estimate_tokens, load_or_build
from .repo_map_tools import REPO_MAP_TOOL_SPECS, RepoMapToolRunner
from .utils import finalize_resolver_verdict, resolve_model
from .planner import Planner, _usage_dict

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

init_weave()

RESOLVER_SYSTEM_PROMPT = (
    "You localize content from scientific papers to the code that implements it. "
    "You work from a candidate set of symbols, not from the repository itself. "
    "You reply with a single JSON object matching the requested schema and nothing else."
)

RESOLVER_CRAWL_SYSTEM_PROMPT = (
    "You localize paper content to code. A Planner already proposed files and anchor symbols. "
    "Use the repo-map tools to confirm and narrow line ranges efficiently—start from those "
    "candidates before searching broadly. You will then return structured JSON with symbol "
    "span indices from lookup_symbol."
)

CRAWL_MAX_TOOL_TURNS = 12


class ResolverResult(TypedDict):
    verdict: str
    reasoning: str
    code_snippets: list[CodeSnippet]


def _pack_resolver_result(parsed: dict, snippets: list[CodeSnippet]) -> ResolverResult:
    verdict, reasoning = finalize_resolver_verdict(
        snippets=snippets,
        model_verdict=parsed.get("verdict"),
        model_reasoning=parsed.get("reasoning"),
    )
    return {
        "verdict": verdict,
        "reasoning": reasoning,
        "code_snippets": snippets,
    }


def _read_span(path: Path, span: CandidateSpan) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    body = lines[span.start_line - 1 : span.end_line]
    return "\n".join(body)


def _add_usage(
    total: dict[str, int] | None, usage: dict[str, int] | None
) -> dict[str, int] | None:
    if not usage:
        return total
    if not total:
        return dict(usage)
    merged = dict(total)
    for key, val in usage.items():
        if val is None:
            continue
        merged[key] = (merged.get(key) or 0) + val
    return merged


class Resolver:
    def __init__(
        self,
        model: str = "sonnet",
        temperature: float = 0.0,
        cache_dir: str | Path = DEFAULT_CACHE_DIR,
        kind: str = "menu",  # menu | guided-crawl
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.cache_dir = cache_dir
        self.kind = kind
        self._client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        self._last_metrics: dict | None = None

    @op(name="resolver_resolve_spans")
    def resolve_spans(
        self,
        symbols: list[dict],
        repo_map: RepoMap,
        repo_root: Path,
    ) -> list[CodeSnippet]:
        started_at = time.perf_counter()
        snippets = []
        for symbol in symbols or []:
            filepath = symbol["filepath"]
            name = symbol["name"]
            spans = symbol["spans"]
            record = repo_map.symbol(name, filepath=filepath)
            if record is None:
                continue
            menu = list(record.candidate_spans())
            for span_index in spans:
                if span_index == -1:
                    full_span = menu[-1]
                else:
                    full_span = menu[span_index]
                start, end = full_span.start_line, full_span.end_line
                content = _read_span(repo_root / filepath, full_span)
                snippets.append(
                    {
                        "content": content,
                        "filepath": filepath,
                        "start_line": int(start),
                        "end_line": int(end),
                    }
                )
        duration_s = round(time.perf_counter() - started_at, 3)
        num_symbols = len(symbols or [])
        log_summary(
            "resolver_resolve_spans",
            {
                "duration_s": duration_s,
                "num_snippets": len(snippets),
                "num_symbols": num_symbols,
            },
        )
        logger.info(
            "resolve_spans: done duration=%.2fs snippets=%s symbols=%s",
            duration_s,
            len(snippets),
            num_symbols,
        )
        return snippets

    async def resolve(
        self,
        content: str,
        context: str,
        candidates: dict,
        repo_map: RepoMap,
        repo_root: Path,
    ):
        if self.kind == "menu":
            return await self._resolve_menu(
                content, context, candidates, repo_map, repo_root
            )
        if self.kind == "guided-crawl":
            return await self._resolve_guided_crawl(
                content, context, candidates, repo_map, repo_root
            )
        raise ValueError(f"unknown resolver kind: {self.kind}")

    @op(name="resolver_resolve_menu")
    async def _resolve_menu(
        self,
        content: str,
        context: str,
        candidates: dict,
        repo_map: RepoMap,
        repo_root: Path,
    ):
        for candidate in candidates.get("candidates", []):
            anchor = candidate.get("anchor_symbol", "")
            fp = candidate.get("filepath", "")
            symbol_record = repo_map.symbol(anchor, filepath=fp) if anchor else None
            if symbol_record:
                candidate["spans"] = [
                    {"index": i, **s.model_dump()}
                    for i, s in enumerate(symbol_record.candidate_spans())
                ]
            else:
                candidate["spans"] = []

        prompt = build_resolver_menu_prompt(
            content=content,
            context=context,
            candidates=candidates.get("candidates", []),
            max_snippets=5,
        )

        model_id = resolve_model(self.model)
        logger.info(
            "resolve_menu: chars=%d est_tokens=~%d planner_candidates=%d model=%s",
            len(prompt),
            estimate_tokens(prompt),
            len(candidates.get("candidates", [])),
            model_id,
        )

        started_at = time.perf_counter()
        message = await self._client.messages.create(
            model=model_id,
            max_tokens=4096,
            temperature=self.temperature,
            system=RESOLVER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            output_config={
                "format": {"type": "json_schema", "schema": resolver_schema},
            },
        )

        raw_text = ""
        if isinstance(message.content, list) and message.content:
            raw_text = getattr(message.content[0], "text", "") or ""
        parsed = _parse_json_result(raw_text)
        if parsed is None and raw_text:
            logger.warning("resolve_menu: failed to parse JSON raw=%s", raw_text[:500])
        if not isinstance(parsed, dict):
            parsed = {}

        usage = _usage_dict(message.usage)
        symbols = parsed.get("symbols")
        if not isinstance(symbols, list):
            symbols = []

        llm_duration_s = round(time.perf_counter() - started_at, 3)
        menu_metrics = {
            "duration_s": llm_duration_s,
            "model": model_id,
            "api": "anthropic",
            "kind": "menu",
            "tool_calls": 0,
            "prompt_chars": len(prompt),
            "prompt_est_tokens": estimate_tokens(prompt),
            "usage": usage,
            "num_symbols": len(symbols),
            "planner_candidates": len(candidates.get("candidates", [])),
        }
        log_summary("resolver_resolve_menu", menu_metrics)
        self._last_metrics = menu_metrics
        logger.info(
            "resolve_menu: done duration=%.2fs symbols=%s in=%s out=%s",
            llm_duration_s,
            len(symbols),
            (usage or {}).get("input_tokens"),
            (usage or {}).get("output_tokens"),
        )

        snippets = self.resolve_spans(symbols, repo_map=repo_map, repo_root=repo_root)
        self._log_prediction_summary(snippets)
        return _pack_resolver_result(parsed, snippets)

    @op(name="resolver_resolve_crawl")
    async def _resolve_guided_crawl(
        self,
        content: str,
        context: str,
        candidates: dict,
        repo_map: RepoMap,
        repo_root: Path,
    ):
        model_id = resolve_model(self.model)
        planner_list = candidates.get("candidates") or []
        prefer_fps = [c.get("filepath", "") for c in planner_list if c.get("filepath")]
        prompt = build_resolver_crawl_prompt(
            content=content,
            context=context,
            planner_output=candidates,
            max_snippets=5,
        )
        runner = RepoMapToolRunner(
            repo_map, repo_root, prefer_filepaths=prefer_fps
        )

        logger.info(
            "resolve_crawl: chars=%d est_tokens=~%d planner_candidates=%d model=%s",
            len(prompt),
            estimate_tokens(prompt),
            len(planner_list),
            model_id,
        )

        started_at = time.perf_counter()
        messages: list[dict] = [{"role": "user", "content": prompt}]
        usage_total = None
        tool_calls = 0
        turns = 0

        for _ in range(CRAWL_MAX_TOOL_TURNS):
            turns += 1
            message = await self._client.messages.create(
                model=model_id,
                max_tokens=4096,
                temperature=self.temperature,
                cache_control={ "type": "ephemeral", "ttl": "1h" },
                system=RESOLVER_CRAWL_SYSTEM_PROMPT,
                messages=messages,
                tools=REPO_MAP_TOOL_SPECS,
            )
            usage_total = _add_usage(usage_total, _usage_dict(message.usage))
            messages.append({"role": "assistant", "content": message.content})
            tool_blocks = [
                b for b in message.content if getattr(b, "type", None) == "tool_use"
            ]
            if not tool_blocks:
                break
            tool_results = []
            for block in tool_blocks:
                tool_calls += 1
                inp = block.input if isinstance(block.input, dict) else {}
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": runner.dispatch(block.name, inp),
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        messages.append(
            {
                "role": "user",
                "content": (
                    "Return your final localization as JSON only: reasoning, verdict "
                    "(implemented | not_implemented | not_applicable), and symbols "
                    "(filepath, name, span indices from lookup_symbol). "
                    "Use not_implemented with empty symbols when investigation found no "
                    "genuine implementation."
                ),
            }
        )
        final = await self._client.messages.create(
            model=model_id,
            max_tokens=4096,
            temperature=self.temperature,
            system=RESOLVER_SYSTEM_PROMPT,
            messages=messages,
            output_config={
                "format": {"type": "json_schema", "schema": resolver_schema},
            },
        )
        usage_total = _add_usage(usage_total, _usage_dict(final.usage))

        raw_text = ""
        if isinstance(final.content, list) and final.content:
            raw_text = getattr(final.content[0], "text", "") or ""
        parsed = _parse_json_result(raw_text)
        if parsed is None and raw_text:
            logger.warning("resolve_crawl: failed to parse JSON raw=%s", raw_text[:500])
        if not isinstance(parsed, dict):
            parsed = {}
        symbols = parsed.get("symbols")
        if not isinstance(symbols, list):
            symbols = []

        duration_s = round(time.perf_counter() - started_at, 3)
        crawl_metrics = {
            "duration_s": duration_s,
            "model": model_id,
            "api": "anthropic",
            "kind": "guided-crawl",
            "prompt_chars": len(prompt),
            "prompt_est_tokens": estimate_tokens(prompt),
            "usage": usage_total,
            "num_symbols": len(symbols),
            "planner_candidates": len(planner_list),
            "tool_calls": tool_calls,
            "tool_turns": turns,
        }
        log_summary("resolver_resolve_crawl", crawl_metrics)
        self._last_metrics = crawl_metrics
        logger.info(
            "resolve_crawl: done duration=%.2fs symbols=%s tool_calls=%s in=%s out=%s",
            duration_s,
            len(symbols),
            tool_calls,
            (usage_total or {}).get("input_tokens"),
            (usage_total or {}).get("output_tokens"),
        )

        snippets = self.resolve_spans(symbols, repo_map=repo_map, repo_root=repo_root)
        self._log_prediction_summary(snippets)
        return _pack_resolver_result(parsed, snippets)

    def _log_prediction_summary(self, snippets: list[CodeSnippet]) -> None:
        log_summary(
            "prediction_summary",
            {
                "num_snippets": len(snippets),
                "top_filepath": snippets[0]["filepath"] if snippets else None,
            },
        )
        logger.info("resolve: done snippets=%s", len(snippets))


if __name__ == "__main__":
    annotations_path = Path(__file__).parents[1] / "evals" / "annotations" / "manual_v1.json"
    paper = json.loads(annotations_path.read_text())["papers"][0]
    annotation = paper["annotations"][0]
    repo_path = paper["repo_path"].rstrip(". ")

    local_code_path = clone_repo_to_temp_dir(repo_path)
    repo_map = load_or_build(local_code_path, repo_url=repo_path, cache_dir=DEFAULT_CACHE_DIR)

    planner = Planner()
    candidates = asyncio.run(
        planner.get_candidates(
            repo_map=repo_map,
            content=annotation["claim_text"],
            context=f"Paper title: {paper.get('title', '')}\nSection: {annotation.get('section_ref', '')}",
        )
    )

    resolver = Resolver()
    print(asyncio.run(
        resolver.resolve(
            content=annotation["claim_text"],
            context=f"Paper title: {paper.get('title', '')}\nSection: {annotation.get('section_ref', '')}",
            candidates=candidates,
            repo_map=repo_map,
            repo_root=Path(local_code_path),
        )
    ))
