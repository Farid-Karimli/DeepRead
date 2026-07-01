import json
import os
import subprocess
import shutil
import requests
import base64

from io import BytesIO
from urllib.parse import urlparse

from claude_agent_sdk.types import StreamEvent
from pprint import pprint

from pdf2image import convert_from_path, convert_from_bytes
from pdf2image.exceptions import (
    PDFInfoNotInstalledError,
    PDFPageCountError,
    PDFSyntaxError
)
from PIL import Image

async def print_event(event: StreamEvent, tool_state: dict) -> None:
    if isinstance(event, StreamEvent):
        event = event.event
        print(json.dumps(event, indent=4))
    return None

def clone_repo_to_temp_dir(repo_url: str) -> str:
    """
    Clones a GitHub repository to a temporary directory.
    """
    raw_repo_url = repo_url
    repo_url = normalize_github_repo_url(repo_url)
    if repo_url is None:
        raise ValueError(f"Invalid GitHub repository URL: {raw_repo_url}")

    repo_name = repo_url.split("/")[-1]
    repo_name = repo_name.replace(".git", "")
    repo_dir = os.path.join(os.path.dirname(__file__), "temp", repo_name)
    if not os.path.exists(repo_dir):
        os.makedirs(repo_dir)
        output = subprocess.run(["git", "clone", repo_url, repo_dir], check=True, capture_output=True)
        if output.returncode != 0:
            raise Exception(f"Failed to clone repository: {output.stderr.decode('utf-8')}")
    else:
        print(f"Repository already cloned to {repo_dir}")

    return repo_dir


def normalize_github_repo_url(repo_url: str | None) -> str | None:
    """
    Normalizes GitHub links (repo, blob, tree) to canonical clone URL.
    Example: https://github.com/org/repo/blob/main/a.py -> https://github.com/org/repo.git
    """
    if not isinstance(repo_url, str):
        return None

    raw = repo_url.strip()
    if not raw:
        return None

    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.netloc.lower() != "github.com":
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None

    owner = parts[0]
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        return None

    return f"https://github.com/{owner}/{repo}.git"

def get_repo_tree(repo_url: str) -> list:
    repo_name = repo_url.split("/")[-1]
    repo_name = repo_name.replace(".git", "")
    repo_owner = repo_url.split("/")[-2]

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
    }

    repo_info_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}"
    repo_info = requests.get(repo_info_url, headers=headers).json()
    default_branch = repo_info.get("default_branch")
    if not default_branch:
        raise Exception(
            f"Could not resolve default branch for {repo_owner}/{repo_name}: {repo_info}"
        )

    github_trees_api_url = (
        f"https://api.github.com/repos/{repo_owner}/{repo_name}/git/trees/{default_branch}"
    )

    response = requests.get(
        github_trees_api_url,
        params={"recursive": 1},
        headers=headers,
    )

    return response.json()

def get_file_content(file_github_url: str):

    try:
        github_blob = requests.get(file_github_url).json()
        base64_content = github_blob['content']

        decoded_content = base64.b64decode(base64_content)
        text = decoded_content.decode('utf-8')
        return text
    except Exception as e:
        print(F"Failed to retrieve github blob: {e}")
        return None

def download_file(url: str) -> bytes:
    """
    Downloads a file from a URL.
    """
    response = requests.get(url)
    return response.content


def delete_temp_dir(repo_dir: str) -> None:
    """
    Deletes a temporary directory.
    """
    if os.path.exists(repo_dir):
        shutil.rmtree(repo_dir) 

def get_pdf_thumbnail(file_content: bytes, size=(512, 512)):
    images = convert_from_bytes(file_content, poppler_path="C:\\Users\\karim\\Downloads\\poppler\\poppler-26.02.0\\Library\\bin")

    first_image = images[0]

    width, height = first_image.size
    first_image = first_image.crop((20, 20, width, height//2))

    first_image.thumbnail(size)

     # JPEG has no alpha channel
    if first_image.mode != "RGB":
        first_image = first_image.convert("RGB")

    buffer = BytesIO()
    first_image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue() 


if __name__=="__main__":
    with open("./papers/vjepa2.pdf", 'rb') as f:
        get_pdf_thumbnail(f)