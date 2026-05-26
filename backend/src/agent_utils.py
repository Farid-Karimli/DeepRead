import io
import re

import pypdf
import anthropic
import json
import pdfplumber


from typing import Callable
from pathlib import Path
from claude_agent_sdk.types import StreamEvent

from src.config import ANTHROPIC_API_KEY

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
    },
    "required": ["sections", "github_repo_url"]
}

key_section_schema_v2 = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section_id": {
                        "type": "string",
                    },
                    "section_header": {
                        "type": "string",
                    },
                    "description": {
                        "type": "string",
                    }
                },
                "required": ["section_id", "section_header", "description"]
            }
        },
    },
    "required": ["sections"]
}

code_section_schema = {
    "type": "object",
    "properties": {
        "paper_title": {
            "type": "string",
        },
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section_id": {
                        "type": "string",
                    },
                    "section_name": {
                        "type": "string",
                    },
                    "section_header": {
                        "type": "string",
                    },
                    "code_snippets": {
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
                "required": ["section_id", "section_header", "code_snippets"]
            }
        },
        
    },
    "required": ["sections"]
}

single_content_map_schema = {
    "type": "object",
    "properties": {
        "code_snippets": {
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
    "required": ['code_snippets']
}


EventCallback = Callable[[StreamEvent], None]


GITHUB_URL_RE = re.compile(r"https?://(?:www\.)?github\.com/[^\s<>()\[\]{}\"']+", re.IGNORECASE)


def _clean_extracted_url(url: str) -> str:
    return url.strip().rstrip(".,;:)]}>")


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
    Matches by stable section_id first, then by normalized section_header/name, then
    by index when both lists have the same length.
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

    by_id: dict[str, dict] = {}
    by_norm: dict[str, dict] = {}
    for row in ks_list:
        sid = row.get("section_id")
        if isinstance(sid, str) and sid and sid not in by_id:
            by_id[sid] = row

        for title_key in ("section_header", "section_name"):
            title = row.get(title_key)
            if isinstance(title, str):
                norm = _normalize_section_title(title)
                if norm and norm not in by_norm:
                    by_norm[norm] = row

    merged: list[dict] = []
    for i, item in enumerate(raw_sections):
        if not isinstance(item, dict):
            merged.append(item)
            continue
        out = _normalize_section_to_code_shape(item)
        matched: dict | None = None
        sid = out.get("section_id")
        if isinstance(sid, str):
            matched = by_id.get(sid)
        if matched is None:
            for title_key in ("section_header", "section_name"):
                title = out.get(title_key)
                if isinstance(title, str):
                    matched = by_norm.get(_normalize_section_title(title))
                    if matched is not None:
                        break
        if matched is None and len(ks_list) == len(raw_sections) and i < len(ks_list):
            matched = ks_list[i]
        if isinstance(matched, dict):
            desc = matched.get("description")
            if isinstance(desc, str):
                out["section_description"] = desc
            matched_id = matched.get("section_id")
            if isinstance(matched_id, str):
                out["section_id"] = matched_id
            matched_header = matched.get("section_header")
            if isinstance(matched_header, str):
                out["section_header"] = matched_header
            sl = matched.get("start_line")
            el = matched.get("end_line")
            if isinstance(sl, int):
                out["paper_start_line"] = sl
            if isinstance(el, int):
                out["paper_end_line"] = el
        merged.append(out)

    return {**code_result, "sections": merged}


def _combine_section_mapping_results(
    partials: list[dict | None],
    key_sections: dict | None,
) -> dict | None:
    """
    Merge per-section code-mapping dicts (each with sections length 1) into one
    result in the same order as key_sections["sections"].
    """
    if key_sections is None or not isinstance(key_sections, dict):
        return None
    ks_sections = key_sections.get("sections")
    if not isinstance(ks_sections, list):
        return None
    if len(partials) != len(ks_sections):
        return None

    combined_sections: list[dict] = []
    paper_title = ""
    for p in partials:
        if not isinstance(p, dict):
            return None
        secs = p.get("sections")
        if not isinstance(secs, list) or len(secs) == 0:
            return None
        row = secs[0]
        if not isinstance(row, dict):
            return None
        combined_sections.append(row)
        pt = p.get("paper_title")
        if isinstance(pt, str) and pt.strip() and not paper_title:
            paper_title = pt.strip()

    return {
        "paper_title": paper_title,
        "github_repo_url": key_sections.get("github_repo_url"),
        "sections": combined_sections,
    }


def extract_paper_info(paper_content: str) -> dict:
    client = anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY
    )
    system_prompt = f"""
    You're a PDF extractor agent. You'll be given a PDF file and asked to extract information. Respond only with the requested information in a structured JSON format: \n\n{{ \n\"attribute1\": <value1>,\n...\n}}"
    """

    prompt_text = f"Give me the title and authors of this paper: \n\n {paper_content}"
    fallback_prompt_text = (
        "Return ONLY valid JSON with keys title and authors (both strings). "
        "No markdown fences and no extra commentary.\n\n"
        f"Paper:\n{paper_content}"
    )

    for attempt in range(2):
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            temperature=0 if attempt > 0 else 1,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt_text if attempt == 0 else fallback_prompt_text
                        }
                    ]
                }
            ],
            thinking={
                "type": "disabled"
            },
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "authors": {"type": "string"}
                        },
                        "required": ["title", "authors"],
                        "additionalProperties": False,
                    }
                },
            }
        )

        response_text = ""
        if isinstance(message.content, list) and len(message.content) > 0:
            first_block = message.content[0]
            response_text = getattr(first_block, "text", "") or ""

        parsed = _parse_json_result(response_text)
        if isinstance(parsed, dict):
            title = parsed.get("title")
            authors = parsed.get("authors")
            if isinstance(title, str) and isinstance(authors, str):
                return {"title": title, "authors": authors}

    raise ValueError("Failed to parse title/authors JSON from model response.")

def extract_github_urls_from_pdf(raw: bytes) -> list[str]:
    urls: set[str] = set()

    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            urls.update(_clean_extracted_url(match.group(0)) for match in GITHUB_URL_RE.finditer(text))

            # Hyperlinks are often stored as annotations rather than visible text.
            for link in getattr(page, "hyperlinks", []):
                uri = link.get("uri")
                if isinstance(uri, str):
                    urls.update(_clean_extracted_url(match.group(0)) for match in GITHUB_URL_RE.finditer(uri))

    return sorted(urls)

if __name__ == "__main__":
    reader = pypdf.PdfReader("./papers/linear_bandits.pdf")
    paper_content = reader.pages[0].extract_text()
    response = extract_paper_info(paper_content)
    print(response)