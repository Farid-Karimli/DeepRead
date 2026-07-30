"""Naive sequential prediction memory for warm content-to-code evaluations."""

from __future__ import annotations

from pydantic import ValidationError

from src.content_to_code_memory import retrieve_recent_prior_matches
from src.types import (
    ContentToCodeInputs,
    ContentToCodeMemorySnapshot,
    ContentToCodeResult,
    PaperContentBox,
    PaperMappingRecord,
)


class EvaluationMemory:
    def __init__(self) -> None:
        self._matches_by_paper: dict[str, list[PaperMappingRecord]] = {}

    def retrieve(self, paper_id: str) -> ContentToCodeMemorySnapshot:
        return retrieve_recent_prior_matches(
            prior_matches=self._matches_by_paper.get(paper_id, []),
        )

    def remember(
        self,
        *,
        paper_id: str,
        annotation_id: str,
        content: str,
        context: str,
        repo_url: str,
        prediction: dict | None,
    ) -> None:
        if not isinstance(prediction, dict):
            return
        try:
            result = ContentToCodeResult.model_validate(prediction)
        except ValidationError:
            return
        self._matches_by_paper.setdefault(paper_id, []).append(
            PaperMappingRecord(
                paper_id=paper_id,
                mapping_type="content_to_code",
                cache_key=f"eval:{annotation_id}",
                inputs=ContentToCodeInputs(
                    content=content,
                    context=context,
                    repo_url=repo_url,
                    box=PaperContentBox(l=0, t=0, w=0, h=0),
                ),
                outputs=result,
                created_by=0,
            )
        )
