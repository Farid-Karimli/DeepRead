"""
Utility functions for file system operations and content analysis.
"""

import os
import re
from pathlib import Path
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
