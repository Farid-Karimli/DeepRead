import re
import json
import requests
from pprint import pprint

import anthropic

from src.config import BRAVE_SEARCH_API_KEY, BRAVE_ANSWERS_API_KEY, ANTHROPIC_API_KEY
from src.agent_utils import extract_paper_info
from src.utils import normalize_github_repo_url


GITHUB_REPO_RE = re.compile(
    r"https?://(?:www\.)?github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
    re.IGNORECASE,
)

# Owner paths that are never an actual code repository.
_NON_REPO_OWNERS = {"sponsors", "topics", "search", "marketplace", "settings", "about"}


def search_github(query: str) -> list[dict]:
    url = "https://api.search.brave.com/res/v1/web/search"

    if "site:github.com" not in query:
        query += " site:github.com"
    
    params = {
        "q": query, 
        "extra_snippets": "true"
    }
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_SEARCH_API_KEY
    }

    response = requests.get(url, params=params, headers=headers).json()
    result = response.get("web", {}).get("results", [])

    result = [{
        "title": item.get("title"),
        "url": item.get("url"),
        "snippet": item.get("snippet")
    } for item in result]

    return result

def brave_find_github_repo(paper_title: str, paper_authors, deep_search: bool = False) -> str:
    authors_str = paper_authors if isinstance(paper_authors, str) else ", ".join(paper_authors)
    url = "https://api.search.brave.com/res/v1/chat/completions"
    data = {
        "stream": False, 
        "messages": [
            {
                "role": "user", 
                "content": 
                
                f"""
                What is the GitHub repository URL for the following paper: {paper_title} by {authors_str}? 
                Return only the GitHub repository URL, no other text.
                """
            }
        ],
        "extra_body": {
            "enable_research": deep_search
        }
    }

    headers = {
        "Content-Type": "application/json",
        "X-Subscription-Token": BRAVE_ANSWERS_API_KEY
    }

    response = requests.post(url, json=data, headers=headers).json()
    return response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()


def _extract_repo_url(text: str) -> str | None:
    """Pull the first github.com/owner/repo URL out of arbitrary answer text."""
    if not text:
        return None
    match = GITHUB_REPO_RE.search(text)
    if not match:
        return None
    url = match.group(0).rstrip(".,);]}>'\"")
    parsed = _parse_owner_repo(url)
    if parsed is None or parsed[0].lower() in _NON_REPO_OWNERS:
        return None
    return url


def _parse_owner_repo(repo_url: str) -> tuple[str, str] | None:
    parts = [p for p in repo_url.split("github.com/", 1)[-1].split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        return None
    return owner, repo


def _fetch_repo_context(repo_url: str) -> dict | None:
    """
    Fetch repo metadata + README via the GitHub API. Returns None when the repo
    does not exist (a strong signal that the candidate is wrong).
    """
    parsed = _parse_owner_repo(repo_url)
    if parsed is None:
        return None
    owner, repo = parsed

    base_headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        meta_resp = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers=base_headers,
            timeout=10,
        )
    except requests.RequestException:
        return None
    if meta_resp.status_code != 200:
        return None
    meta = meta_resp.json()

    readme_text = ""
    try:
        readme_resp = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/readme",
            headers={**base_headers, "Accept": "application/vnd.github.raw"},
            timeout=10,
        )
        if readme_resp.status_code == 200:
            readme_text = readme_resp.text
    except requests.RequestException:
        readme_text = ""

    return {
        "url": repo_url,
        "full_name": meta.get("full_name") or f"{owner}/{repo}",
        "description": meta.get("description") or "",
        "homepage": meta.get("homepage") or "",
        "readme": readme_text,
    }


def _first_heading(readme: str) -> str:
    for line in readme.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def _title_overlap(title: str, blob: str) -> float:
    tokens = [t for t in re.findall(r"[a-z0-9]+", title.lower()) if len(t) > 2]
    if not tokens:
        return 0.0
    hits = sum(1 for t in set(tokens) if t in blob)
    return hits / len(set(tokens))


def _llm_verify_repo(title: str, authors: str, context: dict) -> bool:
    """Single-shot LLM judge: does this repo correspond to the paper?"""
    if not ANTHROPIC_API_KEY:
        return False

    readme_excerpt = context["readme"][:3000]
    heading = _first_heading(context["readme"])
    prompt = f"""Decide whether this GitHub repository is the official (or directly associated) code release for the given paper.

Paper title: {title}
Paper authors: {authors}

Repository: {context['full_name']}
Repository description: {context['description']}
Repository homepage: {context['homepage']}
README top-level heading: {heading}
README excerpt:
{readme_excerpt}

A repository matches only if its README/description clearly corresponds to THIS paper (same paper title, the paper's method name, or the same authors). A merely related project, a reimplementation by someone else, or a different paper does NOT match."""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            temperature=0,
            system="You verify whether a GitHub repository is the official code release for a research paper. Respond only with the requested JSON.",
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            thinking={"type": "disabled"},
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "match": {"type": "boolean"},
                            "reason": {"type": "string"},
                        },
                        "required": ["match", "reason"],
                        "additionalProperties": False,
                    },
                }
            },
        )
    except Exception:
        return False

    response_text = ""
    if isinstance(message.content, list) and message.content:
        response_text = getattr(message.content[0], "text", "") or ""
    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError:
        return False
    return bool(parsed.get("match"))


def _verify_repo_matches_paper(context: dict, title: str, authors: str) -> bool:
    """
    Confirm the candidate repo actually belongs to the paper. Accepts on a strong
    deterministic signal (paper title largely present in repo text), otherwise
    defers to a single LLM judge that reads the README heading/excerpt.
    """
    blob = " ".join(
        [context["full_name"], context["description"], context["readme"][:4000]]
    ).lower()
    if _title_overlap(title, blob) >= 0.8:
        return True
    return _llm_verify_repo(title, authors, context)


def find_verified_github_repo(paper_raw: bytes) -> str:
    """
    Final fallback for locating a paper's GitHub repo when PDF extraction fails.

    Uses Brave Answers to propose a repository (escalating to deep research if the
    quick answer is unusable), verifies the candidate against the paper, and
    returns a normalized github.com URL. Raises ValueError if nothing verifies.
    """
    info = extract_paper_info(paper_raw)
    title = (info.get("title") or "").strip()
    authors = info.get("authors") or ""
    if not title:
        raise ValueError("Could not extract paper title for Brave repo search.")

    tried: set[str] = set()
    for deep_search in (False, True):
        answer = brave_find_github_repo(title, authors, deep_search=deep_search)
        repo_url = _extract_repo_url(answer)
        if not repo_url or repo_url in tried:
            continue
        tried.add(repo_url)

        context = _fetch_repo_context(repo_url)
        if context is None:
            continue
        if _verify_repo_matches_paper(context, title, authors):
            return normalize_github_repo_url(repo_url) or repo_url

    raise ValueError(f"Brave fallback could not find a verified GitHub repo for paper: {title!r}")


if __name__ == "__main__":
    import sys

    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "./papers/3d.pdf"
    with open(pdf_path, "rb") as f:
        raw = f.read()
    pprint(find_verified_github_repo(raw))
