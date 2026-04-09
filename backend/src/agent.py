import json
import os
from pathlib import Path
from typing import Callable
from claude_agent_sdk import ClaudeAgentOptions, query, ResultMessage
from claude_agent_sdk.types import StreamEvent

from src.utils import clone_repo_to_temp_dir, delete_temp_dir

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
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {
                                    "type": "string",
                                },
                                "filepath": {
                                    "type": "string",
                                },
                                "start_line": {
                                    "type": "integer",
                                },
                                "end_line": {
                                    "type": "integer",
                                },
                            },
                            "required": ["content", "filepath", "start_line", "end_line"],
                        },
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


def _normalize_section_title(name: str) -> str:
    return " ".join(name.split()) if isinstance(name, str) else ""


_LEGACY_SECTION_SNIPPET_KEYS = (
    "code_snippet",
    "code_filepath",
    "code_start_line",
    "code_end_line",
)


def _normalize_snippet_dict(snip: dict) -> dict | None:
    """One code_snippets entry: content, filepath, start_line, end_line."""
    content = snip.get("content")
    if content is None:
        content = snip.get("code_snippet")
    filepath = snip.get("filepath")
    if filepath is None:
        filepath = snip.get("code_filepath")
    sl = snip.get("start_line")
    if sl is None:
        sl = snip.get("code_start_line")
    el = snip.get("end_line")
    if el is None:
        el = snip.get("code_end_line")
    row: dict = {}
    if isinstance(content, str):
        row["content"] = content
    if isinstance(filepath, str):
        row["filepath"] = filepath
    if isinstance(sl, int):
        row["start_line"] = sl
    if isinstance(el, int):
        row["end_line"] = el
    return row if row else None


def _normalize_section_to_code_shape(section: dict) -> dict:
    """
    Canonical shape for map_key_sections_to_code / frontend:
    section_name, section_description, code_snippets[{content, filepath, start_line, end_line}].
    Accepts legacy flat code_* fields or per-snippet aliases.
    """
    out = dict(section)
    for k in _LEGACY_SECTION_SNIPPET_KEYS:
        out.pop(k, None)

    raw_list = section.get("code_snippets")
    normalized: list[dict] = []
    if isinstance(raw_list, list):
        for snip in raw_list:
            if isinstance(snip, dict):
                row = _normalize_snippet_dict(snip)
                if row is not None:
                    normalized.append(row)
        out["code_snippets"] = normalized
    else:
        row = _normalize_snippet_dict(section)
        out["code_snippets"] = [row] if row is not None else []

    return out


def _merge_key_sections_into_code_result(
    key_sections: dict | None, code_result: dict | None
) -> dict | None:
    """
    Normalize each section to code_snippets[] shape, then copy paper-side fields
    from identify_key_sections onto each section row.
    Matches by normalized section_name, or by index when both lists have the same length.
    """
    if code_result is None:
        return None
    raw_sections = code_result.get("sections")
    if not isinstance(raw_sections, list):
        return code_result

    ks_list: list[dict] = []
    if isinstance(key_sections, dict):
        ks_raw = key_sections.get("sections")
        if isinstance(ks_raw, list):
            ks_list = [x for x in ks_raw if isinstance(x, dict)]

    by_norm: dict[str, dict] = {}
    for row in ks_list:
        sn = row.get("section_name")
        if isinstance(sn, str):
            norm = _normalize_section_title(sn)
            if norm and norm not in by_norm:
                by_norm[norm] = row

    merged: list[dict] = []
    for i, item in enumerate(raw_sections):
        if not isinstance(item, dict):
            merged.append(item)
            continue
        out = _normalize_section_to_code_shape(item)
        name = out.get("section_name")
        matched: dict | None = None
        if isinstance(name, str):
            matched = by_norm.get(_normalize_section_title(name))
        if matched is None and len(ks_list) == len(raw_sections) and i < len(ks_list):
            matched = ks_list[i]
        if isinstance(matched, dict):
            sl = matched.get("start_line")
            el = matched.get("end_line")
            if isinstance(sl, int):
                out["paper_start_line"] = sl
            if isinstance(el, int):
                out["paper_end_line"] = el
            desc = matched.get("description")
            if isinstance(desc, str) and desc.strip():
                out["paper_section_description"] = desc
        merged.append(out)

    return {**code_result, "sections": merged}


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

        # What if link not present in the paper

        github_link_present = "https://github.com/" in paper_content_to_analyze

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