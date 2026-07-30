from __future__ import annotations

from src.content_to_code_memory import retrieve_recent_prior_matches
from src.types import (
    CodeSnippet,
    ContentToCodeInputs,
    ContentToCodeResult,
    PaperContentBox,
    PaperMappingRecord,
)


def mapping(
    cache_key: str,
    content: str,
    *,
    verdict: str = "implemented",
    snippets: list[CodeSnippet] | None = None,
) -> PaperMappingRecord:
    return PaperMappingRecord(
        paper_id="paper-1",
        mapping_type="content_to_code",
        cache_key=cache_key,
        created_by=7,
        inputs=ContentToCodeInputs(
            content=content,
            context=f"Context for {content}",
            repo_url="https://github.com/example/repo",
            box=PaperContentBox(l=0, t=0, w=1, h=1),
            page_number=0,
        ),
        outputs=ContentToCodeResult(
            verdict=verdict,
            reasoning=f"Reasoning for {content}",
            code_snippets=snippets
            if snippets is not None
            else [
                CodeSnippet(
                    content="pass",
                    filepath=f"src/{cache_key}.py",
                    start_line=1,
                    end_line=2,
                )
            ],
        ),
    )


def test_cold_path_returns_empty_recent_snapshot() -> None:
    snapshot = retrieve_recent_prior_matches(prior_matches=[])

    assert snapshot.model_dump() == {
        "strategy": "recent",
        "version": "v1",
        "hints": [],
    }


def test_returns_last_three_interactions_in_chronological_order() -> None:
    candidates = [
        mapping("first", "first interaction"),
        mapping("second", "second interaction"),
        mapping("failed", "third interaction", verdict="not_implemented", snippets=[]),
        mapping("fourth", "fourth interaction"),
    ]

    snapshot = retrieve_recent_prior_matches(prior_matches=candidates)

    assert [hint.source_cache_key for hint in snapshot.hints] == [
        "second",
        "failed",
        "fourth",
    ]
    assert [hint.verdict for hint in snapshot.hints] == [
        "implemented",
        "not_implemented",
        "implemented",
    ]
    assert snapshot.hints[1].paths == []


def test_interaction_is_compact_and_deduplicates_code_locations() -> None:
    long_content = "  ".join(["training objective"] * 40)
    prior = mapping(
        "training",
        long_content,
        snippets=[
            CodeSnippet(
                content="loss = objective(x)",
                filepath=r"src\train.py",
                start_line=10,
                end_line=12,
            ),
            CodeSnippet(
                content="loss = objective(x)",
                filepath="src/train.py",
                start_line=10,
                end_line=12,
            ),
            CodeSnippet(
                content="class Encoder: ...",
                filepath="src/models/encoder.py",
                start_line=3,
                end_line=20,
            ),
        ],
    )

    hint = retrieve_recent_prior_matches(prior_matches=[prior]).hints[0]

    assert len(hint.source_content) == 280
    assert hint.source_content.endswith("…")
    assert hint.paths == [
        "src/models/encoder.py:3-20",
        "src/train.py:10-12",
    ]
    assert hint.folders == ["src", "src/models"]
