import json
import os
import subprocess
import shutil
import requests
import base64

from claude_agent_sdk.types import StreamEvent
from pprint import pprint

async def print_event(event: StreamEvent, tool_state: dict) -> None:
    if isinstance(event, StreamEvent):
        event = event.event
        print(json.dumps(event, indent=4))
    return None

def clone_repo_to_temp_dir(repo_url: str) -> str:
    """
    Clones a GitHub repository to a temporary directory.
    """
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


if __name__=="__main__":
    github_url = 'https://github.com/dojeon-ai/Atari-PB'

    git_tree = get_repo_tree(github_url)

    pprint(git_tree)

    first_file = "https://api.github.com/repos/gnobitab/RectifiedFlow/git/blobs/4a5fd0eda4250faf218d6b65fd858de055956252"

    content = get_file_content(first_file)
    print(content)