import asyncio
import json
import os
from pathlib import Path
from claude_agent_sdk import ClaudeAgentOptions, query, ResultMessage
import pypdf

from src.utils import clone_repo_to_temp_dir, delete_temp_dir
from src.search import search_github
from src.agent_utils import extract_paper_info, key_section_schema, code_section_schema, _merge_key_sections_into_code_result, _parse_json_result, EventCallback

class Agent:
    """
    Early implementation of an agent that maps key sections of a research paper
    to specific code snippets in the associated repository.
    Powered by Claude Code.
    """ 
    def __init__(self, model: str = "claude-3-5-sonnet-20241022", 
                 stream_events: bool = False):
        self.model = model
        self.stream_events = stream_events

    async def _test_claude_code(self) -> None:
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
        return search_results[0].get("url")

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

        prompt = f"""
        Identify the key sections of the implementation content in the following research paper.
        Focus on sections that have a high likelihood of being implemented in the code repository. These sections
        should be ones that aid the reader in understanding the implementation and enable them to compare side-by-side.

        Ignore sections that are not implementation content, such as introduction, conclusion, figures, tables, etc.

        Also, extract the GitHub repository URL from the paper, if it is present.

        Provide JUST the section names, and start and end lines, short descriptions of the section, and the GitHub repository URL, no other text.

        IMPORTANT: Make sure that the section names are exact matches to the section names in the paper. Do not make up section names and do not add
        descriptive text to the section names. Sections should include subsections within sections, marked with a sub-section number. If there is no sub-section number, 
        append a sub-section number to the section name with a period.

        ### Paper Content ###
        {paper_content_to_analyze}
        ### End Paper Content ###

        ### GitHub Repository URL ###
        In case the repository URL is not present in the paper, it is provided here. Note that this may be empty is the URL is present in the paper already.
        {github_repository_url}
        ### End GitHub Repository URL ###

        Example:
        {{ "sections": [
            {{
                "section_name": "Section 1",
                "start_line": 10,
                "end_line": 20,
                "description": "A comprehensive description of the section", 
            }}
            ],
            "github_repo_url": "https://github.com/your-repo/your-repo.git"
        ]}}
        """

        tool_state = {
            "current_tool": None,
            "tool_input": "",
        }

        options = ClaudeAgentOptions(
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
        return parsed_result

    async def map_key_sections_to_code(
        self,
        key_sections: dict,
        code_path: str = None,
        code_content: str = None,
        on_event: EventCallback = None
    ) -> dict:
        if code_path is None and code_content is None:
            raise ValueError("Either code_path or code_content must be provided.")

        prompt = f"""
        Map the provided key sections of a research papers to the code in the corresponding repository (local path provided).

        ### Key Sections ###
        {key_sections}
        ### End Key Sections ###

        ### Code ###
        {code_path}
        ### End Code ###

        Provide the code snippets for each section, and the line numbers of the code snippets.
        Provide JUST the code snippets and the line numbers in a JSON object, no other text. 

        Return only a JSON object. First character must be {{ and last must be }}. No prose.

        IMPORTANT: Make sure that the section names are exact matches to the section names in the key sections. Do not make up section names and do not add
        descriptive text to the section names.

        Example:
        {{
            "paper_title": "The Title of the Paper",
            "github_repo_url": "https://github.com/your-repo/your-repo.git",
            "sections": [
                {{
                    "section_name": "Section 1",
                    "section_description": "A short description of the section",
                    "code_snippets": [
                        {{
                            "content": "print('Hello, world!')",
                            "filepath": "path/to/code/file.py",
                            "start_line": 10,
                            "end_line": 20
                        }},
                    ],
                }}
            ]
        }}
        """

        tool_state = {
            "current_tool": None,
            "tool_input": "",
        }

        options = ClaudeAgentOptions(
            allowed_tools=["Bash", "Search", "ReadFile"],
            include_partial_messages=True,
            cwd="." if code_path is None else os.path.dirname(code_path),
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
                    print("Error parsing JSON from map_key_sections_to_code result.")
                    print(f"Tried to parse: {cleaned}")
                    parsed_result = None
                    # Do not return here – keep consuming the generator so SDK cleans up correctly.

        return parsed_result


    async def analyze_paper(
        self,
        paper_content: str = None,
        paper_path: str = None,
        on_event: EventCallback = None
    ) -> dict:
        """
        Analyzes paper content for processing.
        """
        if paper_content is None and paper_path is None:
            raise ValueError("Either paper_content or paper_path must be provided.")
        
        paper_content_to_analyze = paper_content if paper_content is not None else Path(paper_path).read_text(encoding="utf-8")

        key_sections = await self.identify_key_sections(paper_content=paper_content_to_analyze, paper_path=paper_path, on_event=on_event)
        if key_sections is None:
            raise ValueError("No key sections found.")

        github_repo_url = key_sections.get('github_repo_url')
        if not github_repo_url:
            raise ValueError(
                "No GitHub repository URL found in this paper. "
                "DeepRead requires a paper that links to a public GitHub repository."
            )

        repo_local_dir = clone_repo_to_temp_dir(github_repo_url)

        code_result = await self.map_key_sections_to_code(key_sections=key_sections, code_path=repo_local_dir, on_event=on_event)
        if code_result is None:
            raise ValueError("No code result found.")

        delete_temp_dir(repo_local_dir)

        merged = _merge_key_sections_into_code_result(key_sections, code_result)
        paper_title = ""
        if isinstance(merged, dict):
            pt = merged.get("paper_title")
            if isinstance(pt, str) and pt.strip():
                paper_title = pt.strip()
        return {
            "paper_title": paper_title,
            "github_repo_url": key_sections.get("github_repo_url"),
            "code_result": merged,
        }


if __name__ == "__main__":
    agent = Agent()
    paper_path = "./papers/pretraining-rl.pdf"
    paper_content = "\n\n".join([page.extract_text() for page in pypdf.PdfReader(paper_path).pages])
    result = asyncio.run(agent.analyze_paper(paper_content=paper_content))
    
    with open("pretraining-rl.analyze_paper.json", "w") as f:
        json.dump(result, f, indent=4)

    