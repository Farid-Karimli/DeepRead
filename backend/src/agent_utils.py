import io
import re
from urllib.parse import urlparse

import pypdf
import anthropic
import json
import pdfplumber
import requests
from bs4 import BeautifulSoup


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

single_code_map_schema = {
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
                    "description": {
                        "type": "string",
                    },
                },
                "required": ["section_id", "description"],
            }
        },
    },
    "required": ["sections"]
}


EventCallback = Callable[[StreamEvent], None]


GITHUB_URL_RE = re.compile(r"https?://(?:www\.)?github\.com/[^\s<>()\[\]{}\"']+", re.IGNORECASE)
GITHUB_IO_URL_RE = re.compile(r"https?://(?:[a-z0-9-]+\.)*[a-z0-9-]+\.github\.io(?:/[^\s<>()\[\]{}\"']*)?", re.IGNORECASE)


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


def extract_paper_info(paper_input: str | bytes) -> dict:
    
    if isinstance(paper_input, bytes):
        paper_content = ""

        with pdfplumber.open(io.BytesIO(paper_input)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    paper_content += text
    else:
        paper_content = paper_input
                
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

def _extract_annotation_uris(raw: bytes) -> list[str]:
    """
    Pull URIs from PDF link annotations. Project-page links are frequently
    embedded as link annotations on visible text (e.g. "Project Page") rather
    than appearing as raw URLs, and pdfplumber's `hyperlinks` list does not
    reliably surface them, so we read the annotation `/A /URI` entries directly.
    """
    uris: list[str] = []
    try:
        reader = pypdf.PdfReader(io.BytesIO(raw))
    except Exception:
        return uris

    for page in reader.pages:
        annots = page.get("/Annots")
        if not annots:
            continue
        for annot in annots:
            try:
                obj = annot.get_object()
            except Exception:
                continue
            action = obj.get("/A")
            if not action:
                continue
            uri = action.get("/URI")
            if isinstance(uri, str) and uri:
                uris.append(uri)
    return uris


def _extract_pdf_text(raw: bytes) -> str:
    """Concatenate the visible text of every page in the PDF."""
    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _find_github_urls(text: str) -> list[str]:
    """All github.com URLs appearing in `text`, de-duplicated."""
    return sorted({_clean_extracted_url(m.group(0)) for m in GITHUB_URL_RE.finditer(text)})


def _find_io_urls(text: str) -> list[str]:
    """All *.github.io URLs appearing in `text`, de-duplicated."""
    return sorted({_clean_extracted_url(m.group(0)) for m in GITHUB_IO_URL_RE.finditer(text)})


def _find_repo_from_io_page(page_url: str) -> str | None:
    """
    Visit a *.github.io project page and return the most likely github.com
    repository link on it (typically behind a "Code" button), or None.
    """
    try:
        repo_links = extract_github_repo_links(page_url)
    except Exception:
        return None
    if not repo_links:
        return None
    ranked = rank_candidates(repo_links, page_url)
    return ranked[0] if ranked else None


def extract_github_urls_from_pdf(raw: bytes) -> list[str]:
    """
    Find the GitHub repository URL for a paper, trying in order:
      1. github.com links in the PDF text
      2. github.com links in the PDF link annotations
      3. *.github.io links in the PDF text, resolved to a repo on that page
      4. *.github.io links in the PDF annotations, resolved to a repo on that page

    Returns a list of candidate github.com URLs (so the caller can normalize and
    pick the first valid one). Raises ValueError if every stage fails.
    """
    pdf_text = _extract_pdf_text(raw)
    annotation_text = "\n".join(_extract_annotation_uris(raw))

    # 1 & 2: direct github.com links, text first then annotations.
    for source in (pdf_text, annotation_text):
        github_urls = _find_github_urls(source)
        if github_urls:
            return github_urls

    # 3 & 4: github.io project pages, text first then annotations. Visit each and
    # extract the backing repository (usually a "Code" button).
    for source in (pdf_text, annotation_text):
        for io_url in _find_io_urls(source):
            repo = _find_repo_from_io_page(io_url)
            if repo:
                return [repo]

    raise ValueError("No GitHub repository URL found in the PDF.")


def extract_github_repo_links(page_url: str) -> list[str]:
    resp = requests.get(page_url, timeout=(5, 8))
    soup = BeautifulSoup(resp.text, "html.parser")
    
    seen = set()
    candidates = []
    
    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        # Normalize relative URLs
        if href.startswith("/"):
            parsed = urlparse(page_url)
            href = f"{parsed.scheme}://{parsed.netloc}{href}"
        
        # Only keep github.com/owner/repo shaped URLs
        match = re.match(r'https://github\.com/([^/]+)/([^/?#]+)', href)
        if match and href not in seen:
            seen.add(href)
            candidates.append(href)

    return candidates

def rank_candidates(candidates: list[str], page_url: str) -> list[str]:
    def score(url: str) -> int:
        s = 0
        path = urlparse(url).path.lower().strip("/")
        parts = path.split("/")
        
        # Penalize non-repo links
        if len(parts) != 2:           return -100  # e.g. github.com/org
        if parts[1] in ("issues", "pulls", "wiki", "releases"): return -50
        
        # Prefer links in prominent positions (Code button, etc.)
        # (you'd pass tag context here — see note below)
        
        # Prefer if owner matches page domain
        page_domain = urlparse(page_url).netloc  # e.g. mylab.github.io
        if parts[0] in page_domain:
            s += 10
        
        # Prefer links with "code" or "github" anchor text
        # (also requires tag context)
        
        return s
    
    return sorted(candidates, key=score, reverse=True)

if __name__ == "__main__":
    with open("./papers/mistakes.pdf", "rb") as f:
        paper_content = f.read()
    urls = extract_github_urls_from_pdf(paper_content)
    print(urls)
