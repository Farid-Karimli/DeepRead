import asyncio
import json
import logging
import time
from pathlib import Path
from claude_agent_sdk import ClaudeAgentOptions, query, ResultMessage
from anthropic import AsyncAnthropic



from src.agent_utils import _parse_json_result, resolver_schema
from src.config import ANTHROPIC_API_KEY
from src.observability import init_weave, log_summary, op
from src.prompts import build_planner_prompt, build_resolver_menu_prompt
from src.types import CodeSnippet, ContentToCodeResult
from src.utils import clone_repo_to_temp_dir

from .schema import CandidateSpan, FileRecord, RepoMap, SymbolRecord
from .repo_map import DEFAULT_CACHE_DIR, estimate_tokens, load_or_build
from .utils import resolve_model
from .planner import Planner, _usage_dict

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

init_weave()

RESOLVER_SYSTEM_PROMPT = (
    "You localize content from scientific papers to the code that implements it. "
    "You work from a candidate set of symbols, not from the repository itself. "
    "You reply with a single JSON object matching the requested schema and nothing else."
)

def _read_span(path: Path, span: CandidateSpan) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    body = lines[span.start_line - 1 : span.end_line]
    return "\n".join(body)

class Resolver:
    def __init__(
        self, 
        model: str = "sonnet",
        temperature: float = 0.0,
        cache_dir: str | Path = DEFAULT_CACHE_DIR,
        kind: str = 'menu' # Either menu or guided-crawl
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.cache_dir = cache_dir
        self.kind = kind
        self._client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

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

    @op(name="resolver_resolve_menu")
    async def resolve(
        self,
        content: str,
        context: str,
        candidates: dict,
        repo_map: RepoMap,
        repo_root: Path,
    ):
        if self.kind == "menu": 
            # Single API call. 
            # Get candidate_spans() from the Planner's output.candidates
            # and supply in prompt. Narrow down line ranges from there. 
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
                "prompt_chars": len(prompt),
                "prompt_est_tokens": estimate_tokens(prompt),
                "usage": usage,
                "num_symbols": len(symbols),
                "planner_candidates": len(candidates.get("candidates", [])),
            }
            log_summary("resolver_resolve_menu", menu_metrics)
            logger.info(
                "resolve_menu: done duration=%.2fs symbols=%s in=%s out=%s",
                llm_duration_s,
                len(symbols),
                (usage or {}).get("input_tokens"),
                (usage or {}).get("output_tokens"),
            )

            snippets = self.resolve_spans(symbols, repo_map=repo_map, repo_root=repo_root)

            log_summary(
                "prediction_summary",
                {
                    "num_snippets": len(snippets),
                    "top_filepath": snippets[0]["filepath"] if snippets else None,
                },
            )
            logger.info("resolve: done snippets=%s", len(snippets))

            return snippets

        else:
            pass


if __name__ == "__main__":
    # Test the whole pipeline but targeted on the Resolver.
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
    snippets = asyncio.run(
        resolver.resolve(
            content=annotation["claim_text"],
            context=f"Paper title: {paper.get('title', '')}\nSection: {annotation.get('section_ref', '')}",
            candidates=candidates,
            repo_map=repo_map,
            repo_root=Path(local_code_path),
        )
    )
    print(snippets)