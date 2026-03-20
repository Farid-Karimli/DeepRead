import os
import shutil
import subprocess


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


def delete_temp_dir(repo_dir: str) -> None:
    """
    Deletes a temporary directory.
    """
    if os.path.exists(repo_dir):
        shutil.rmtree(repo_dir) 