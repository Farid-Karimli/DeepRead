import asyncio
import json
import os
import re
import time
from uuid import uuid4

from pathlib import Path
from pprint import pprint
from io import BufferedIOBase
from claude_agent_sdk import ClaudeAgentOptions, query, ResultMessage

from src.search import search_github
from src.utils import clone_repo_to_temp_dir, delete_temp_dir, normalize_github_repo_url, print_event
from src.agent_utils import (
    extract_github_urls_from_pdf, 
    extract_paper_info, 
    key_section_schema, 
    key_section_schema_v2, 
    code_section_schema, 
    single_content_map_schema,
    _merge_key_sections_into_code_result, 
    _parse_json_result, 
    EventCallback
)

from src.prompts import (
    build_identify_key_sections_prompt,
    build_identify_key_sections_prompt_v2,
    build_map_key_sections_to_code_prompt,
    build_single_content_mapping_prompt
)
from src.process_pdf import papermage_process

import logging
import warnings
logging.basicConfig(
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _summarize_sections(sections: list[dict], max_items: int = 8) -> list[dict]:
    summary = [
        {
            "section_id": section.get("section_id") or section.get("entity_id"),
            "section_header": section.get("section_header"),
        }
        for section in sections[:max_items]
        if isinstance(section, dict)
    ]
    if len(sections) > max_items:
        summary.append({"remaining_sections": len(sections) - max_items})
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

    async def find_github_repo(self,
        paper_content: str = None,
        paper_path: str = None,
    ) -> str:

        paper_info = extract_paper_info(paper_content)
        if paper_info is None:
            raise ValueError("No paper info found.")
        title = paper_info.get("title")
        if title is None:
            raise ValueError("No title found in paper info.")
        authors = paper_info.get("authors")
        if authors is None:
            raise ValueError("No authors found in paper info.")

        search_results = search_github(query=f"{title} {authors}")
        if len(search_results) == 0:
            raise ValueError("No search results found.")
        for result in search_results:
            normalized = normalize_github_repo_url(result.get("url"))
            if normalized:
                return normalized
        raise ValueError("No valid GitHub repository URLs found in search results.")

    async def identify_key_sections(
        self,
        paper_content: str = None,
        paper_path: str = None,
        on_event: EventCallback = None
    ) -> dict:
        """
        Identify the key sections of a research paper.
        Returns a dictionary with the key sections, start and end lines, short descriptions, and the GitHub repository URL.
        """
        if paper_content is None and paper_path is None:
            raise ValueError("Either paper_content or paper_path must be provided.")

        paper_content_to_analyze = paper_content if paper_content is not None else Path(paper_path).read_text(encoding="utf-8")

        # What if link not present in the paper?
        github_repository_url = None
        github_link_present = "https://github.com/" in paper_content_to_analyze
        if not github_link_present:
            github_repository_url = await self.find_github_repo(paper_content=paper_content_to_analyze, paper_path=paper_path)

        prompt = build_identify_key_sections_prompt(
            paper_content_to_analyze=paper_content_to_analyze,
            github_repository_url=github_repository_url,
        )

        tool_state = {
            "current_tool": None,
            "tool_input": "",
        }

        options = ClaudeAgentOptions(
            model=self.model,
            allowed_tools=["Bash", "Search", "ReadFile"],
            include_partial_messages=True,
            cwd="." if paper_path is None else os.path.dirname(paper_path),
            output_format={
                "type": "json_schema",
                "json_schema": key_section_schema # BUG with CC, this is ignored. https://github.com/anthropics/claude-code/issues/18536
                }
            )


        parsed_result = None
        async for message in query(prompt=prompt, options=options):

            if on_event is not None and self.stream_events:
                await on_event(message, tool_state)

            if isinstance(message, ResultMessage):
                # Don't break early – let the async generator finish to avoid
                # known anyio/claude_agent_sdk cancellation issues.
                parsed_result = _parse_json_result(message.result)
                if parsed_result is None:
                    cleaned = message.result.replace("```json", "").replace("```", "").strip()
                    print("Error parsing JSON from identify_key_sections result.")
                    print(f"Tried to parse: {cleaned}")
                    parsed_result = None
                    # Do not return here – keep consuming the generator so SDK cleans up correctly.
        if isinstance(parsed_result, dict):
            normalized = normalize_github_repo_url(parsed_result.get("github_repo_url"))
            if normalized:
                parsed_result["github_repo_url"] = normalized
        return parsed_result

    async def identify_key_sections_v2(
        self, 
        papermage_process_result: dict,
        on_event: EventCallback = None
    ):
        started_at = time.perf_counter()
       
        exclude_headers = re.compile(r"^(Introduction|Discussion|Acknowledgements?|References?|Conclusion|Related Work)s?$", re.IGNORECASE)
        relevant_sections = [
            sec for sec in papermage_process_result['sections']
            if sec.get('section_header') and not exclude_headers.match(sec['section_header'].strip())
        ]
        logger.info(
            "identify_key_sections: prepared candidate sections count=%d sample=%s",
            len(relevant_sections),
            _summarize_sections(relevant_sections),
        )
        sections_json = json.dumps(relevant_sections, ensure_ascii=False, indent=2)
        prompt = build_identify_key_sections_prompt_v2(
            relevant_sections=sections_json,
        )

        agent_options = ClaudeAgentOptions(
            model=self.model,
            allowed_tools=["ReadFile", "Read", "Agent"],
            include_partial_messages=True,
            cwd=".",
            output_format={
                "type": "json_schema",
                "json_schema": key_section_schema_v2
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

        selected_sections = parsed_result.get("sections") if isinstance(parsed_result, dict) else None
        logger.info(
            "identify_key_sections: completed duration=%.2fs selected_count=%s selected_sample=%s",
            time.perf_counter() - started_at,
            len(selected_sections) if isinstance(selected_sections, list) else None,
            _summarize_sections(selected_sections) if isinstance(selected_sections, list) else None,
        )
        return parsed_result

    async def map_key_sections_to_code(
        self,
        key_sections: dict,
        code_path: str = None,
        on_event: EventCallback = None,
        limit: int = None
    ) -> dict:
        started_at = time.perf_counter()
        if code_path is None:
            raise ValueError("code_path must be provided.")

        sections = key_sections.get("sections") if isinstance(key_sections, dict) else key_sections
        if limit is not None:
            sections = sections[:limit]
        section_count = len(sections) if isinstance(sections, list) else None
        logger.info(
            "map_key_sections_to_code: starting repo=%s section_count=%s sections=%s",
            code_path,
            section_count,
            _summarize_sections(sections) if isinstance(sections, list) else None,
        )

        prompt = build_map_key_sections_to_code_prompt(
            key_sections=key_sections,
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

        options = ClaudeAgentOptions(
            model=self.model,
            allowed_tools=["Search", "ReadFile"],
            include_partial_messages=True,
            cwd=code_path,
            output_format={
                "type": "json_schema",
                "json_schema": code_section_schema
            }
        )

        parsed_result = None
        async for message in query(prompt=prompt, options=options):
            if on_event is not None and self.stream_events:
                await on_event(message, tool_state)
            if isinstance(message, ResultMessage):
                # Again, avoid returning from inside the loop so the generator
                # can shut down cleanly.
                parsed_result = _parse_json_result(message.result)
                if parsed_result is None:
                    cleaned = message.result.replace("```json", "").replace("```", "").strip()
                    logger.warning("map_key_sections_to_code: failed to parse JSON result raw=%s", cleaned)
                    parsed_result = None
                    # Do not return here – keep consuming the generator so SDK cleans up correctly.

        mapped_sections = parsed_result.get("sections") if isinstance(parsed_result, dict) else None
        logger.info(
            "map_key_sections_to_code: completed duration=%.2fs mapped_count=%s",
            time.perf_counter() - started_at,
            len(mapped_sections) if isinstance(mapped_sections, list) else None,
        )
        return parsed_result


    async def map_content_to_code(
        self,
        content: str | bytes,
        repo_url: str,
        context: str
    ):
        """
            Maps a small piece of content to relevant code snippets. 
            Same as map_key_sections_to_code but on a smaller scale. 

            Args:
                content: A piece of text from the paper, or an image of content like formulas. 
                repo_path: Path to the repository of the code. 
                context: Optional context about the content - surrounding text, paper abstract, caption (for figures).
        """

        if isinstance(content, str):
            content_input = content
        else:
            with open(f'./temp/{uuid4()}.png') as image_file:
                image_file.write(content)
            content_input = image_file

        local_code_path = clone_repo_to_temp_dir(repo_url)
        prompt = build_single_content_mapping_prompt(content=content_input, repo_path=local_code_path, context=context)
        logger.info(
            "map_key_sections_to_code: prompt prepared chars=%d cwd=%s tools=%s",
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
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                parsed_result = _parse_json_result(message.result)
                if parsed_result is None:
                    cleaned = message.result.replace("```json", "").replace("```", "").strip()
                    logger.warning("map_content_to_code: failed to parse JSON result raw=%s", cleaned)
                    parsed_result = None

        result = parsed_result.get("code_snippets") if isinstance(parsed_result, dict) else None
        logger.info(
            "map_content_to_code: completed duration=%.2fs mapped_count=%s",
            time.perf_counter() - started_at,
            len(result) if isinstance(result, list) else None,
        )
        return parsed_result



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
        key_sections = await self.identify_key_sections_v2(papermage_process_result=papermage_result)
        if key_sections is None:
            raise ValueError("No key sections found.")
        
        logger.info("analyze_paper: key sections completed duration=%.2fs", time.perf_counter() - key_sections_started_at)
        logger.info("analyze_paper: selected key sections count=%d", len(key_sections['sections']))

        url_started_at = time.perf_counter()
        github_candidates = extract_github_urls_from_pdf(paper_raw)
        logger.info(
            "analyze_paper: extracted github URL candidates duration=%.2fs count=%d candidates=%s",
            time.perf_counter() - url_started_at,
            len(github_candidates),
            github_candidates,
        )
        github_repo_url = None
        for candidate_url in github_candidates:
            normalized_url = normalize_github_repo_url(candidate_url)
            if normalized_url:
                github_repo_url = normalized_url
                logger.info("analyze_paper: using github URL=%s", github_repo_url)
                break
        if github_repo_url:
            key_sections["github_repo_url"] = github_repo_url

        if not github_repo_url:
            raise ValueError(
                "No GitHub repository URL found in this paper. "
                "DeepRead requires a paper that links to a public GitHub repository."
            )

        clone_started_at = time.perf_counter()
        repo_local_dir = clone_repo_to_temp_dir(github_repo_url)
        logger.info(
            "analyze_paper: repo ready duration=%.2fs path=%s",
            time.perf_counter() - clone_started_at,
            repo_local_dir,
        )

        code_mapping_started_at = time.perf_counter()
        
        code_result = await self.map_key_sections_to_code(key_sections=key_sections['sections'], code_path=repo_local_dir, on_event=on_event, limit=20)
        if code_result is None:
            raise ValueError("No code result found.")
        
        logger.info("analyze_paper: code mapping completed duration=%.2fs", time.perf_counter() - code_mapping_started_at)

        cleanup_started_at = time.perf_counter()
        delete_temp_dir(repo_local_dir)
        logger.info("analyze_paper: repo cleanup completed duration=%.2fs", time.perf_counter() - cleanup_started_at)

        merged = _merge_key_sections_into_code_result(key_sections, code_result)
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
            "github_repo_url": key_sections.get("github_repo_url"),
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

    