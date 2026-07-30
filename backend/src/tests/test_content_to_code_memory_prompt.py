from pathlib import Path

from src.prompts import (
    build_planner_prompt,
    build_single_content_to_code_mapping_prompt,
)


def test_content_to_code_prompt_omits_memory_section_without_history():
    prompt = build_single_content_to_code_mapping_prompt(
        content="The encoder is updated with a contrastive objective.",
        repo_path=Path("/tmp/repo"),
        context="Method section",
    )

    assert "Recent Personal Mapping History" not in prompt


def test_content_to_code_prompt_labels_memory_as_chronological_history():
    prompt = build_single_content_to_code_mapping_prompt(
        content="The encoder is updated with a contrastive objective.",
        repo_path=Path("/tmp/repo"),
        context="Method section",
        memory_hints=[
            {
                "source_cache_key": "prior-1",
                "source_content": "A similar objective updates the target network.",
                "verdict": "implemented",
                "reasoning": "The loss is implemented here.",
                "paths": ["src/loss.py:10-12"],
                "folders": ["src"],
            }
        ],
    )

    assert "Recent Personal Mapping History" in prompt
    assert "ordered from oldest to newest" in prompt
    assert "not a relevance" in prompt
    assert "src/loss.py" in prompt


def test_planner_prompt_receives_the_same_recent_history():
    prompt = build_planner_prompt(
        content="The encoder is updated with a contrastive objective.",
        context="Method section",
        repo_map_blob="src/loss.py role=loss symbols=contrastive_loss",
        memory_hints=[
            {
                "source_cache_key": "eval:prior-1",
                "source_content": "A similar objective.",
                "verdict": "implemented",
                "reasoning": "Implemented by the loss function.",
                "paths": ["src/loss.py:10-12"],
                "folders": ["src"],
            }
        ],
    )

    assert "Recent Personal Mapping History" in prompt
    assert "src/loss.py:10-12" in prompt
    assert prompt.index("Recent Personal Mapping History") < prompt.index("Repository Map")
