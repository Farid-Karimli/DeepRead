import json
import os
from pathlib import Path
from typing import Callable
from claude_agent_sdk import ClaudeAgentOptions, query, ResultMessage
from claude_agent_sdk.types import StreamEvent

from deepread.utils import clone_repo_to_temp_dir, delete_temp_dir

async def _print_event(event: StreamEvent, tool_state: dict) -> None:
    if isinstance(event, StreamEvent):
        event = event.event
        event_type = event.get("type")
        if event_type == "content_block_delta":
            delta = event.get("delta", {})
            if delta.get("type") == "text_delta":
                print(delta.get("text", ""), end="", flush=True)
        if event_type == "content_block_start":
            print("\n")
            content_block = event.get("content_block", {})
            if content_block.get("type") == "tool_use":
                tool_state["current_tool"] = content_block.get("name")
                tool_state["tool_input"] = ""
                print(f"Starting tool: {tool_state['current_tool']}\n")
        elif event_type == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "input_json_delta":
                    # Accumulate JSON input as it streams in
                    chunk = delta.get("partial_json", "")
                    tool_state["tool_input"] += chunk
        elif event_type == "content_block_stop":
                # Tool call complete - show final input
                if tool_state["current_tool"]:
                    print(f"Tool {tool_state['current_tool']} called with: {tool_state['tool_input']}")
                    tool_state["current_tool"] = None



# Currently unused, output format is ignored by Claude Code. https://github.com/anthropics/claude-code/issues/18536
key_section_schema = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section_name": {
                        "type": "string",
                    },
                    "start_line": {
                        "type": "integer",
                    },
                    "end_line": {
                        "type": "integer",
                    }
                },
                "required": ["section_name", "start_line", "end_line"]
            }
        },
        "github_repo_url": {
            "type": "string",
            "format": "uri",
        }
    },
    "required": ["sections", "github_repo_url"]
}

code_section_schema = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section_name": {
                        "type": "string",
                    },
                    "section_description": {
                        "type": "string",
                    },
                    "code_snippet": {
                        "type": "string",
                    },
                    "code_filepath": {
                        "type": "string",
                    },
                    "code_start_line": {
                        "type": "integer",
                    },
                    "code_end_line": {
                        "type": "integer",
                    },
                },
                "required": ["section_name", "section_description", "code_snippet", "code_filepath", "code_start_line", "code_end_line"]
            }
        },
        
    },
    "required": ["sections"]
}


EventCallback = Callable[[StreamEvent], None]


def _extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:idx + 1]

    return None


def _parse_json_result(raw_text: str) -> dict | None:
    cleaned = raw_text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        candidate = _extract_first_json_object(cleaned)
        if candidate is None:
            return None
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None

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

        prompt = f"""
        Identify the key sections of the implementation content in the following research paper.
        Focus on sections that have a high likelihood of being implemented in the code repository. These sections
        should be ones that aid the reader in understanding the implementation and enable them to compare side-by-side.

        Ignore sections that are not implementation content, such as introduction, conclusion, figures, tables, etc.

        Also, extract the GitHub repository URL from the paper, if it is present.

        Provide JUST the section names, and start and end lines, short descriptions of the section, and the GitHub repository URL, no other text.

        ### Paper Content ###
        {paper_content_to_analyze}
        ### End Paper Content ###

        Example:
        {{ "sections": [
            {{
                "section_name": "Section 1",
                "start_line": 10,
                "end_line": 20,
                "description": "A short description of the section"
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
    
        Example:
        {{
            "sections": [
                {{
                    "section_name": "Section 1",
                    "section_description": "A short description of the section",
                    "code_snippet": "print('Hello, world!')",
                    "code_filepath": "path/to/code/file.py",
                    "code_start_line": 10,
                    "code_end_line": 20
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

        repo_local_dir = clone_repo_to_temp_dir(key_sections['github_repo_url'])

        code_result = await self.map_key_sections_to_code(key_sections=key_sections, code_path=repo_local_dir, on_event=on_event)
        if code_result is None:
            raise ValueError("No code result found.")

        delete_temp_dir(repo_local_dir)

        return {
            "key_sections": key_sections,
            "code_result": code_result
        }