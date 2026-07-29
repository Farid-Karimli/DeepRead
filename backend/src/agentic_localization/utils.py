from pydantic import BaseModel, Field
from typing import Any
import uuid

MODEL_ALIASES = {
    "sonnet": "claude-sonnet-4-5-20250929",
    "opus": "claude-opus-4-1-20250805",
    "haiku": "claude-haiku-4-5-20251001",
}

def resolve_model(model: str) -> str:
    key = (model or "").strip().lower()
    if key in MODEL_ALIASES:
        return MODEL_ALIASES[key]
    return model

class TreeSitterCodeChunk(BaseModel):
    language: str
    file_path: str
    node_type: str
    start_line: int
    end_line: int
    byte_start: int
    byte_end: int
    parent_context: str = ""
    content: str
    chunk_id: str
    parent_chunk_id: str | None = None
    references: list[Any] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    node_id: str
    file_id: str
    symbol_id: str
    parent_route: list[str] = Field(default_factory=list)
    qualified_route: list[str] = Field(default_factory=list)
    definition_id: str = ""

class CodeChunk(BaseModel):
    chunk_id: uuid.UUID
    file_path: str
    start_line: int
    end_line: int
    content: str

    def __repr__(self) -> str:
        return (
            f"CodeChunk(chunk_id={self.chunk_id!r}, "
            f"file_path={self.file_path!r}, "
            f"start_line={self.start_line}, "
            f"end_line={self.end_line})"
        )


"""
Utility functions for file system operations and content analysis.
"""

import os
import re
import shutil
from pathlib import Path
import subprocess
from typing import List, Set


def find_files_by_pattern(repo_path: str, patterns: List[str]) -> List[str]:
    """
    Find files matching any of the given patterns in the repository.

    Args:
        repo_path: Path to the repository
        patterns: List of glob patterns (e.g., ['*.py', 'train_*.py'])

    Returns:
        List of matching file paths relative to repo_path
    """
    repo = Path(repo_path)
    matches = []

    for pattern in patterns:
        matches.extend([str(p.relative_to(repo)) for p in repo.rglob(pattern)])

    return matches


def find_files_by_name(repo_path: str, names: List[str]) -> List[str]:
    """
    Find files with specific names (case-insensitive).

    Args:
        repo_path: Path to the repository
        names: List of file names to search for

    Returns:
        List of matching file paths relative to repo_path
    """
    repo = Path(repo_path)
    matches = []
    names_lower = [n.lower() for n in names]

    for root, dirs, files in os.walk(repo):
        # Skip hidden directories and common non-source directories
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'node_modules', '.git']]

        for file in files:
            if file.lower() in names_lower:
                rel_path = os.path.relpath(os.path.join(root, file), repo)
                matches.append(rel_path)

    return matches


def search_file_content(file_path: str, keywords: List[str], case_sensitive: bool = False) -> Set[str]:
    """
    Search for keywords in a file's content.

    Args:
        file_path: Path to the file
        keywords: List of keywords/patterns to search for
        case_sensitive: Whether to perform case-sensitive search

    Returns:
        Set of keywords that were found in the file
    """
    found = set()

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

            if not case_sensitive:
                content = content.lower()
                keywords = [k.lower() for k in keywords]

            for keyword in keywords:
                if keyword in content:
                    found.add(keyword)
    except Exception:
        pass

    return found


def search_regex_in_file(file_path: str, patterns: List[str]) -> bool:
    """
    Search for regex patterns in a file.

    Args:
        file_path: Path to the file
        patterns: List of regex patterns

    Returns:
        True if any pattern matches
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

            for pattern in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    return True
    except Exception:
        pass

    return False


def check_file_exists(repo_path: str, relative_paths: List[str]) -> List[str]:
    """
    Check which files exist from a list of relative paths.

    Args:
        repo_path: Path to the repository
        relative_paths: List of relative file paths to check

    Returns:
        List of existing file paths
    """
    repo = Path(repo_path)
    existing = []

    for rel_path in relative_paths:
        full_path = repo / rel_path
        if full_path.exists() and full_path.is_file():
            existing.append(rel_path)

    return existing


def get_all_python_files(repo_path: str) -> List[str]:
    """
    Get all Python files in the repository.

    Args:
        repo_path: Path to the repository

    Returns:
        List of Python file paths relative to repo_path
    """
    return find_files_by_pattern(repo_path, ['*.py'])


def read_file_safely(file_path: str, max_size_mb: int = 10) -> str:
    """
    Safely read a file with size limit.

    Args:
        file_path: Path to the file
        max_size_mb: Maximum file size to read in MB

    Returns:
        File content or empty string if file is too large or unreadable
    """
    try:
        file_size = os.path.getsize(file_path)
        if file_size > max_size_mb * 1024 * 1024:
            return ""

        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception:
        return ""

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

from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

def k_nearest_neighbors(query_embedding, documents_embeddings, k=5):
    # Convert to numpy array
    query_embedding = np.array(query_embedding)
    documents_embeddings = np.array(documents_embeddings)

    # Reshape the query vector embedding to a matrix of shape (1, n) to make it
    # compatible with cosine_similarity
    query_embedding = query_embedding.reshape(1, -1)

    # Calculate the similarity for each item in data
    cosine_sim = cosine_similarity(query_embedding, documents_embeddings)

    # Sort the data by similarity in descending order and take the top k items
    sorted_indices = np.argsort(cosine_sim[0])[::-1]

    # Take the top k related embeddings
    top_k_related_indices = sorted_indices[:k]
    top_k_related_embeddings = documents_embeddings[sorted_indices[:k]]
    top_k_related_embeddings = [
        list(row[:]) for row in top_k_related_embeddings
    ]  # convert to list

    return top_k_related_embeddings, top_k_related_indices