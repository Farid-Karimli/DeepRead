from __future__ import annotations

from pathlib import PurePosixPath
from typing import Sequence

from src.types import (
    ContentToCodeInputs,
    ContentToCodeMemoryHint,
    ContentToCodeMemorySnapshot,
    ContentToCodeResult,
    PaperMappingRecord,
)


def retrieve_recent_prior_matches(
    *,
    prior_matches: Sequence[PaperMappingRecord],
    limit: int = 3,
) -> ContentToCodeMemorySnapshot:
    """Return the last interactions in their original chronological order."""
    candidates = [
        match for match in prior_matches if _is_content_to_code_interaction(match)
    ]
    return ContentToCodeMemorySnapshot(
        strategy="recent",
        hints=[_to_hint(match) for match in candidates[-limit:]]
        if limit > 0
        else [],
    )


def _is_content_to_code_interaction(match: PaperMappingRecord) -> bool:
    return (
        match.mapping_type == "content_to_code"
        and isinstance(match.inputs, ContentToCodeInputs)
        and isinstance(match.outputs, ContentToCodeResult)
    )


def _to_hint(match: PaperMappingRecord) -> ContentToCodeMemoryHint:
    assert isinstance(match.inputs, ContentToCodeInputs)
    assert isinstance(match.outputs, ContentToCodeResult)

    locations = sorted(
        {
            (
                _normalize_filepath(snippet.filepath),
                snippet.start_line,
                snippet.end_line,
            )
            for snippet in match.outputs.code_snippets
        }
    )
    files = sorted({filepath for filepath, _, _ in locations})
    folders = sorted(
        {
            str(PurePosixPath(filepath).parent)
            for filepath in files
            if str(PurePosixPath(filepath).parent) != "."
        }
    )

    return ContentToCodeMemoryHint(
        source_cache_key=match.cache_key,
        source_content=_excerpt(match.inputs.content),
        verdict=match.outputs.verdict,
        reasoning=_excerpt(match.outputs.reasoning),
        paths=[
            f"{filepath}:{start_line}-{end_line}"
            for filepath, start_line, end_line in locations
        ],
        folders=folders,
    )


def _excerpt(value: str, limit: int = 280) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1].rstrip()}…"


def _normalize_filepath(filepath: str) -> str:
    return str(PurePosixPath(filepath.replace("\\", "/")))
