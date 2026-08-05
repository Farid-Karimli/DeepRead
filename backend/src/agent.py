import asyncio
import json
import os
import time
from uuid import uuid4

from pathlib import Path
from pprint import pprint
from io import BufferedIOBase, BytesIO
from src.types import ContentToCodeResult, PaperRecord
from claude_agent_sdk import ClaudeAgentOptions, query, ResultMessage

from src.search import search_github, brave_find_github_repo, find_verified_github_repo
from src.utils import clone_repo_to_temp_dir, delete_temp_dir, normalize_github_repo_url, print_event
from src.agent_utils import (
    extract_github_urls_from_pdf, 
    extract_paper_info, 
    key_entities_schema, 
    code_matches_schema, 
    single_content_map_schema,
    single_code_map_schema,
    normalize_identify_result,
    normalize_code_mapping_result,
    hydrate_code_snippet_filepaths,
    _merge_entities_into_matches, 
    _parse_json_result, 
    EventCallback
)
from src.papermage_compat import hydrate_entity_contents, prepare_papermage_result_for_llm

from src.prompts import (
    build_identify_key_sections_prompt,
    build_map_key_sections_to_code_prompt,
    build_single_content_to_code_mapping_prompt,
    build_code_to_content_mapping_prompt
)

from src.rerank import Reranker
from src.observability import (
    ToolTraceCollector,
    init_weave,
    log_summary,
    op,
)

import logging
import warnings
logging.basicConfig(
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

init_weave()


def _summarize_entities(entities: list[dict], max_items: int = 8) -> list[dict]:
    summary = [
        {
            "entity_id": entity.get("entity_id") or entity.get("section_id"),
            "content_type": entity.get("content_type"),
        }
        for entity in entities[:max_items]
        if isinstance(entity, dict)
    ]
    if len(entities) > max_items:
        summary.append({"remaining_entities": len(entities) - max_items})
    return summary
class Agent:
    """
    Early implementation of an agent that maps key sections of a research paper
    to specific code snippets in the associated repository.
    Powered by Claude Code.
    """ 
    def __init__(self, model: str = "sonnet", 
                 stream_events: bool = False,
                 temperature: float = 0.0):
        self.model = model
        self.stream_events = stream_events
        self.temperature = temperature
        self.reranker = Reranker("cohere")

    async def _test(self) -> None:
        prompt = "What is the capital of France?"
        options = ClaudeAgentOptions(
            allowed_tools=["Bash", "Glob"],
            cwd=".",
        )
        result = None
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                result = message.result
        return result

    @op
    async def find_github_repo(self,
        paper_input: str | bytes,
    ) -> str:

        paper_info = extract_paper_info(paper_input)
        paper_info = extract_paper_info(paper_input)
        title = paper_info.get("title")
        authors = paper_info.get("authors")
        logger.info(f"Finding GitHub repository for paper: {title} by {authors}")
        return brave_find_github_repo(paper_title=title, paper_authors=authors, deep_search=True)

    @op
    async def identify_key_sections(
        self, 
        papermage_process_result: dict,
        on_event: EventCallback = None
    ):
        started_at = time.perf_counter()

        papermage_llm = prepare_papermage_result_for_llm(papermage_process_result)
        logger.info(
            "identify_key_sections: prepared candidate sections count=%d",
            len(papermage_llm.get("sections", [])),
        )

        papermage_result_path = f"./tmp/{uuid4()}.papermage.json"
        os.makedirs("./tmp", exist_ok=True)
        with open(papermage_result_path, "w") as f:
            json.dump(papermage_llm, f, ensure_ascii=False, indent=2)

        prompt = build_identify_key_sections_prompt(
            papermage_result_path=papermage_result_path,
        )

        agent_options = ClaudeAgentOptions(
            model=self.model,
            allowed_tools=["ReadFile", "Read", "Agent"],
            include_partial_messages=True,
            cwd=".",
            output_format={
                "type": "json_schema",
                "json_schema": key_entities_schema
                },
            )

        parsed_result = None
        async for message in query(prompt=prompt, options=agent_options):

            if isinstance(message, ResultMessage):
                parsed_result = _parse_json_result(message.result)
                if parsed_result is None:
                    cleaned = message.result.replace("```json", "").replace("```", "").strip()
                    logger.warning("identify_key_sections: failed to parse JSON result raw=%s", cleaned)
                    parsed_result = None

        parsed_result = normalize_identify_result(parsed_result)
        selected_entities = parsed_result.get("entities") if isinstance(parsed_result, dict) else None
        logger.info(
            "identify_key_sections: completed duration=%.2fs selected_entities_count=%s selected_entities_sample=%s",
            time.perf_counter() - started_at,
            len(selected_entities) if isinstance(selected_entities, list) else None,
            _summarize_entities(selected_entities) if isinstance(selected_entities, list) else None,
        )
        os.remove(papermage_result_path)
        return parsed_result

    @op
    async def map_key_sections_to_code(
        self,
        entities: list | dict,
        code_path: str = None,
        on_event: EventCallback = None,
        limit: int = None
    ) -> dict:
        started_at = time.perf_counter()
        if code_path is None:
            raise ValueError("code_path must be provided.")

        if isinstance(entities, dict):
            entity_list = entities.get("entities")
            if not isinstance(entity_list, list):
                entity_list = entities.get("sections")
        else:
            entity_list = entities

        if not isinstance(entity_list, list):
            entity_list = []

        if limit is not None:
            entity_list = entity_list[:limit]
        entity_count = len(entity_list)
        logger.info(
            "map_key_sections_to_code: starting repo=%s entity_count=%s entities=%s",
            code_path,
            entity_count,
            _summarize_entities(entity_list),
        )

        prompt = build_map_key_sections_to_code_prompt(
            entities=entity_list,
            code_path=code_path,
        )
        logger.info(
            "map_key_sections_to_code: prompt prepared chars=%d cwd=%s tools=%s",
            len(prompt),
            code_path,
            ["Search", "ReadFile"],
        )

        tool_state = {
            "current_tool": None,
            "tool_input": "",
        }
        trace = ToolTraceCollector()

        options = ClaudeAgentOptions(
            model=self.model,
            allowed_tools=["Search", "ReadFile"],
            include_partial_messages=True,
            cwd=code_path,
            output_format={
                "type": "json_schema",
                "json_schema": code_matches_schema
            }
        )

        parsed_result = None
        async for message in query(prompt=prompt, options=options):
            trace.ingest(message)
            if on_event is not None and self.stream_events:
                await on_event(message, tool_state)
            if isinstance(message, ResultMessage):
                parsed_result = _parse_json_result(message.result)
                if parsed_result is None:
                    cleaned = message.result.replace("```json", "").replace("```", "").strip()
                    logger.warning("map_key_sections_to_code: failed to parse JSON result raw=%s", cleaned)
                    parsed_result = None

        parsed_result = normalize_code_mapping_result(parsed_result)
        parsed_result = hydrate_code_snippet_filepaths(parsed_result, code_path)
        matching_results = parsed_result.get("matches") if isinstance(parsed_result, dict) else None
        process_metrics = trace.summarize()
        log_summary("process_metrics", process_metrics)
        log_summary("tool_trace", {"num_events": len(trace.events), "events": trace.to_list()})
        logger.info(
            "map_key_sections_to_code: completed duration=%.2fs matching_results_count=%s process=%s",
            time.perf_counter() - started_at,
            len(matching_results) if isinstance(matching_results, list) else None,
            process_metrics,
        )
        return parsed_result


    @op
    async def map_content_to_code(
        self,
        content: str | bytes,
        repo_url: str,
        context: str,
        top_k: int = 5,
        memory_hints: list[dict] | None = None,
    ) -> ContentToCodeResult:
        """
            Maps a small piece of content to relevant code snippets. 
            Same as map_key_sections_to_code but on a smaller scale. 

            Args:
                content: A piece of text from the paper, or an image of content like formulas. 
                repo_path: Path to the repository of the code. 
                context: Optional context about the content - surrounding text, paper abstract, caption (for figures).
                top_k: Maximum number of reranked code snippets to return.
        """

        if isinstance(content, str):
            content_input = content
        else:
            with open(f'./temp/{uuid4()}.png') as image_file:
                image_file.write(content)
            content_input = image_file

        local_code_path = clone_repo_to_temp_dir(repo_url)
        prompt = build_single_content_to_code_mapping_prompt(
            content=content_input,
            repo_path=local_code_path,
            context=context,
            memory_hints=memory_hints,
        )
        logger.info(
            "map_content_to_code: prompt prepared chars=%d cwd=%s tools=%s",
            len(prompt),
            repo_url,
            ["Search", "ReadFile"],
        )

        options = ClaudeAgentOptions(
            model=self.model,
            allowed_tools=["Search", "ReadFile"],
            include_partial_messages=True,
            cwd=local_code_path,
            output_format={
                "type": "json_schema",
                "json_schema": single_content_map_schema
            }
        )

        started_at = time.perf_counter()
        parsed_result = None
        usage = None
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
                    logger.warning("map_content_to_code: failed to parse JSON result raw=%s", cleaned)
                    parsed_result = None

        if not isinstance(parsed_result, dict):
            parsed_result = {}
        code_snippets = parsed_result.get("code_snippets")

        final = ContentToCodeResult(
            reasoning=parsed_result.get("reasoning") or "",
            verdict=parsed_result.get("verdict") or "",
            code_snippets=[]
        )

        process_metrics = trace.summarize()
        # Recorded so token load is comparable with the two-agent planner.
        process_metrics["usage"] = usage
        process_metrics["total_cost_usd"] = cost_usd
        logger.info(
            "map_content_to_code: completed duration=%.2fs mapped_count=%s process=%s",
            time.perf_counter() - started_at,
            len(code_snippets) if isinstance(code_snippets, list) else None,
            process_metrics,
        )

        if isinstance(code_snippets, list) and len(code_snippets) > 0:
            code_contents = [snippet.get("content") for snippet in code_snippets]
            # Rerank against the selected paper content (+ context), not the full prompt.
            reranking_query = f"{content}\n\n{context}" if context else f"{content}"
            reranked_results = self.reranker.rerank(query=reranking_query, documents=code_contents)

            logger.info(
                "map_content_to_code: reranked results count=%d",
                len(reranked_results),
            )

            ranked_indices = [
                result.get("index")
                for result in sorted(
                    reranked_results, key=lambda x: x.get("relevance_score"), reverse=True
                )
            ]
            final.code_snippets = [code_snippets[index] for index in ranked_indices[:top_k]]

        result = final.model_dump()
        hydrate_code_snippet_filepaths(result, local_code_path)
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
        return result

    @op
    async def map_code_to_content(
        self, 
        code: str,
        paper_record: PaperRecord = None,
    ):
        papermage_result = paper_record.papermage_result
        if papermage_result is None:
            raise ValueError("paper_record has no papermage_result")

        papermage_llm = prepare_papermage_result_for_llm(papermage_result)

        os.makedirs("./tmp", exist_ok=True)
        path = f"./tmp/{paper_record.id}.papermage.json"

        with open(path, "w") as f:
            json.dump(papermage_llm, f, indent=4)

        try:
            prompt = build_code_to_content_mapping_prompt(
                code=code,
                papermage_result_path=path,
            )

            options = ClaudeAgentOptions(
                model=self.model,
                allowed_tools=["ReadFile", "Read"],
                include_partial_messages=True,
                cwd=".",
                output_format={
                    "type": "json_schema",
                    "json_schema": single_code_map_schema
                }
            )

            parsed_result = None
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, ResultMessage):
                    parsed_result = _parse_json_result(message.result)
                    if parsed_result is None:
                        cleaned = message.result.replace("```json", "").replace("```", "").strip()
                        logger.warning("map_code_to_content: failed to parse JSON result raw=%s", cleaned)
                        parsed_result = None

            if isinstance(parsed_result, dict):
                from src.types import CodeToContentResult
                return CodeToContentResult.model_validate(parsed_result).model_dump()
            return parsed_result
        finally:
            if os.path.exists(path):
                os.remove(path)


    @op
    async def analyze_paper(
        self,
        file_input: bytes | str | Path | BufferedIOBase,
        papermage_process_result: dict = None,
        on_event: EventCallback = None
    ) -> dict:
        """
        Analyzes paper content for processing.
        """
        started_at = time.perf_counter()
        logger.info("analyze_paper: starting file_input_type=%s", type(file_input).__name__)
        if isinstance(file_input, (str, Path)):
            paper_raw = Path(file_input).read_bytes()
        elif isinstance(file_input, bytes):
            paper_raw = file_input
        elif isinstance(file_input, BufferedIOBase):
            file_input.seek(0)
            paper_raw = file_input.read()
            file_input.seek(0)
        else:
            raise TypeError(f"Unsupported file_input type: {type(file_input)}")
        if papermage_process_result is None:
            from src.process_pdf import papermage_process

            papermage_started_at = time.perf_counter()
            papermage_result = papermage_process(file_input)
            logger.info(
                "analyze_paper: papermage completed duration=%.2fs section_count=%d",
                time.perf_counter() - papermage_started_at,
                len(papermage_result.get("sections", [])) if isinstance(papermage_result, dict) else 0,
            )
        else:
            papermage_result = papermage_process_result

        key_sections_started_at = time.perf_counter()
        entities_result = await self.identify_key_sections(papermage_process_result=papermage_result)
        if entities_result is None:
            raise ValueError("No key sections found.")

        entities = entities_result.get("entities") if isinstance(entities_result, dict) else None
        if not isinstance(entities, list) or len(entities) == 0:
            raise ValueError("No key entities found.")
        
        logger.info("analyze_paper: key sections completed duration=%.2fs", time.perf_counter() - key_sections_started_at)
        logger.info("analyze_paper: selected key entities count=%d", len(entities))

        hydrate_entity_contents(entities, papermage_result)

        try:
            github_candidates = extract_github_urls_from_pdf(paper_raw)
        except ValueError:
            github_candidates = []

        github_repo_url = None
        for candidate_url in github_candidates:
            normalized_url = normalize_github_repo_url(candidate_url)
            if normalized_url:
                github_repo_url = normalized_url
                logger.info("analyze_paper: using github URL=%s", github_repo_url)
                break

        if not github_repo_url:
            github_repo_url = find_verified_github_repo(paper_raw)
            logger.info("analyze_paper: using github URL (brave fallback)=%s", github_repo_url)

        if github_repo_url:
            entities_result["github_repo_url"] = github_repo_url
        else:
            raise ValueError("No GitHub repository URL found.")

        clone_started_at = time.perf_counter()
        repo_local_dir = clone_repo_to_temp_dir(github_repo_url)
        logger.info(
            "analyze_paper: repo ready duration=%.2fs path=%s",
            time.perf_counter() - clone_started_at,
            repo_local_dir,
        )

        code_mapping_started_at = time.perf_counter()
        
        code_result = await self.map_key_sections_to_code(entities=entities, code_path=repo_local_dir, on_event=on_event, limit=100)
        if code_result is None:
            raise ValueError("No code result found.")

        # Stage-2 hydration: models often return absolute checkout paths; GitHub
        # API fetches require paths relative to the repository root.
        hydrate_code_snippet_filepaths(code_result, repo_local_dir)
        
        logger.info("analyze_paper: code mapping completed duration=%.2fs", time.perf_counter() - code_mapping_started_at)

        cleanup_started_at = time.perf_counter()
        delete_temp_dir(repo_local_dir)
        logger.info("analyze_paper: repo cleanup completed duration=%.2fs", time.perf_counter() - cleanup_started_at)

        merged = _merge_entities_into_matches(entities_result, code_result)
        paper_title = ""
        if isinstance(merged, dict):
            pt = merged.get("paper_title")
            if isinstance(pt, str) and pt.strip():
                paper_title = pt.strip()
        logger.info(
            "analyze_paper: completed duration=%.2fs paper_title=%s github_repo_url=%s",
            time.perf_counter() - started_at,
            paper_title or None,
            github_repo_url,
        )
        return {
            "paper_title": paper_title,
            "github_repo_url": entities_result.get("github_repo_url"),
            "code_result": merged,
        }


if __name__ == "__main__":
    agent = Agent()

    with open(f"./pretraining-papermage.json", 'r') as papermage_file:
        papermage_result = json.load(papermage_file)
        
    with open(f"./papers/pretraining-rl.pdf", 'rb') as paper_file:
        paper_raw = paper_file.read()

    final_result = asyncio.run(agent.analyze_paper(file_input=paper_raw, papermage_process_result=papermage_result))
        
    with open(f"./pretraining-rl.analyze_paper.final-result.json", 'w') as f:
        json.dump(final_result, f, indent=4)
