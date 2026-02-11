from collections.abc import Awaitable
import json
from re import I
from typing import Callable
from claude_agent_sdk import ClaudeAgentOptions, query, ResultMessage
from claude_agent_sdk.types import StreamEvent

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

class Agent:
    """
    Early implementation of an agent that maps key sections of a research paper 
    to specific code snippets in the associated repository. Powered by Claude Code.
    """ 
    def __init__(self, model: str = "claude-3-5-sonnet-20241022", stream_events: bool = False):
        self.model = model
        self.stream_events = stream_events

    async def identify_key_sections(self, paper_path: str, on_event: EventCallback = None) -> dict:
        """
        Identify the key sections of a research paper.
        Returns a dictionary with the key sections, start and end lines, short descriptions, and the GitHub repository URL.
        """

        prompt = f"""
        Identify the key sections of the implementation content in the following research paper: {paper_path}.
        Focus on sections that have a high likelihood of being implemented in the code repository. These sections
        should be ones that aid the reader in understanding the implementation and enable them to compare side-by-side.

        Ignore sections that are not implementation content, such as introduction, conclusion, figures, tables, etc.

        Also, extract the GitHub repository URL from the paper, if it is present.

        Provide JUST the section names, and start and end lines, short descriptions of the section, and the GitHub repository URL, no other text.

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
            cwd="./papers",
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
                cleaned = message.result.replace("```json", "").replace("```", "")
                try:
                    parsed_result = json.loads(cleaned)
                except json.JSONDecodeError as e:
                    print(f"Error parsing JSON: {e}")
                    print(f"Tried to parse: {cleaned}")
                    parsed_result = None
                    # Do not return here – keep consuming the generator so SDK cleans up correctly.
        return parsed_result

    async def map_key_sections_to_code(self, key_sections: dict, code_path: str, on_event: EventCallback = None) -> dict:
        prompt = f"""
        Map the provided key sections of a research papers to the code in the corresponding repository (local path provided).

        ### Key Sections ###
        {key_sections}
        ### End Key Sections ###

        ### Code ###
        {code_path}
        ### End Code ###

        ### Output ###
        Provide the code snippets for each section, and the line numbers of the code snippets.
        Provide JUST the code snippets and the line numbers in a JSON object, no other text.

        Example:
        {{
            "sections": [
                {{
                    "section_name": "Section 1",
                    "section_description": "A short description of the section",
                    "code_snippet": "print('Hello, world!')",
                    "code_filepath": "path/to/code/file.py"
                    "code_start_line": 10,
                    "code_end_line": 20,
                }},
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
            cwd="./code",
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
                cleaned = message.result.replace("```json", "").replace("```", "")
                try:
                    parsed_result = json.loads(cleaned)
                except json.JSONDecodeError as e:
                    print(f"Error parsing JSON: {e}")
                    print(f"Tried to parse: {cleaned}")
                    parsed_result = None
                    # Do not return here – keep consuming the generator so SDK cleans up correctly.

        return parsed_result