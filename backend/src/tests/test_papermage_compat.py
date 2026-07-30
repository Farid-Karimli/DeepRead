import json
from pathlib import Path

import pytest

from src.agent_utils import (
    _merge_entities_into_matches,
    code_matches_schema,
    normalize_code_mapping_result,
    normalize_code_result_for_frontend,
    normalize_identify_result,
)
from src.papermage_compat import (
    filter_noise_spans_from_papermage,
    filter_sections_for_key_identification,
    hydrate_entity_contents,
    is_noise_span_text,
    normalize_papermage_result,
    prepare_papermage_result_for_llm,
)

FIXTURE_SPARSE = Path(__file__).resolve().parents[2] / "tmp" / (
    "d6d8b95f1981e7d714921baec9ae080cf7dc14f3e1f249b80a7129ba5cf4076d.papermage.json"
)


def test_is_noise_span_text():
    assert is_noise_span_text("05 0.")
    assert is_noise_span_text("ac.")
    assert is_noise_span_text("0 0 .")
    assert is_noise_span_text("40 Offline BC 0.")
    assert not is_noise_span_text(
        "However, their generalization ability remains unclear due to evaluations."
    )
    assert not is_noise_span_text("PMLR 235, 2024.")


def test_filter_noise_spans_from_papermage():
    papermage = {
        "paper_title": "T",
        "n_pages": 1,
        "equations": [],
        "sections": [
            {
                "entity_id": "sec_0",
                "section_header": "Method",
                "section_content": "body",
                "page_index": 0,
                "box": {"page": 0, "l": 0, "t": 0, "w": 1, "h": 1},
                "sentences": [
                    {"entity_id": "sen_0", "sentence_content": "10 0.", "page_index": 0,
                     "box": {"page": 0, "l": 0, "t": 0, "w": 1, "h": 1}},
                    {"entity_id": "sen_1", "sentence_content": "We train a ResNet encoder.",
                     "page_index": 0, "box": {"page": 0, "l": 0, "t": 0, "w": 1, "h": 1}},
                ],
                "paragraphs": [],
            }
        ],
    }
    filtered = filter_noise_spans_from_papermage(papermage)
    assert len(filtered["sections"][0]["sentences"]) == 1
    assert filtered["sections"][0]["sentences"][0]["entity_id"] == "sen_1"


def test_normalize_sparse_papermage_fixture():
    if not FIXTURE_SPARSE.exists():
        pytest.skip("sparse papermage fixture not present")
    raw = json.loads(FIXTURE_SPARSE.read_text(encoding="utf-8"))
    normalized = normalize_papermage_result(raw)
    assert "sections" in normalized
    assert isinstance(normalized["sections"], list)
    assert len(normalized["sections"]) > 0
    first = normalized["sections"][0]
    assert first["paragraphs"] == []
    assert first["sentences"] == []
    assert normalized["equations"] == []


def test_normalize_legacy_flat_entities():
    legacy = {
        "paper_title": "Legacy",
        "n_pages": 1,
        "entities": [
            {
                "entity_id": "sec_0",
                "section_header": "3. Method",
                "section_content": "We propose a method.",
                "page_index": 0,
                "box": {"page": 0, "l": 0.1, "t": 0.2, "w": 0.3, "h": 0.4},
            }
        ],
    }
    normalized = normalize_papermage_result(legacy)
    assert len(normalized["sections"]) == 1
    assert normalized["sections"][0]["entity_id"] == "sec_0"
    assert normalized["sections"][0]["section_header"] == "3. Method"


def test_filter_sections_excludes_introduction():
    papermage = {
        "paper_title": "T",
        "n_pages": 2,
        "equations": [],
        "sections": [
            {
                "entity_id": "abstract",
                "section_header": "abstract",
                "section_content": "abs",
                "page_index": 0,
                "box": {"page": 0, "l": 0, "t": 0, "w": 1, "h": 1},
                "paragraphs": [],
                "sentences": [],
            },
            {
                "entity_id": "sec_0",
                "section_header": "Introduction",
                "section_content": "intro",
                "page_index": 0,
                "box": {"page": 0, "l": 0, "t": 0, "w": 1, "h": 1},
                "paragraphs": [],
                "sentences": [],
            },
            {
                "entity_id": "sec_1",
                "section_header": "3. Method",
                "section_content": "method",
                "page_index": 1,
                "box": {"page": 1, "l": 0, "t": 0, "w": 1, "h": 1},
                "paragraphs": [],
                "sentences": [],
            },
        ],
    }
    filtered = filter_sections_for_key_identification(papermage)
    headers = [s["section_header"] for s in filtered["sections"]]
    assert "Introduction" not in headers
    assert "3. Method" in headers
    assert "abstract" in headers


def test_normalize_identify_result_legacy_sections():
    raw = {
        "sections": [
            {
                "section_id": "sec_1",
                "section_header": "Method",
                "description": "Core method",
            }
        ]
    }
    out = normalize_identify_result(raw)
    assert len(out["entities"]) == 1
    assert out["entities"][0]["entity_id"] == "sec_1"
    assert out["entities"][0]["content_type"] == "section"
    assert out["entities"][0]["content"] == "Core method"


def test_code_match_contract_requires_correspondence_reasoning():
    match_schema = code_matches_schema["properties"]["matches"]["items"]

    assert "reasoning" in match_schema["properties"]
    assert "reasoning" in match_schema["required"]


def test_normalize_code_mapping_result_legacy_sections():
    raw = {
        "paper_title": "Paper",
        "sections": [
            {
                "section_id": "sec_1",
                "section_header": "Method",
                "section_description": "Legacy correspondence explanation",
                "code_snippets": [
                    {
                        "content": "x = 1",
                        "filepath": "train.py",
                        "start_line": 1,
                        "end_line": 2,
                    }
                ],
            }
        ],
    }
    out = normalize_code_mapping_result(raw)
    assert out["paper_title"] == "Paper"
    assert len(out["matches"]) == 1
    assert out["matches"][0]["entity_id"] == "sec_1"
    assert out["matches"][0]["content_type"] == "section"
    assert out["matches"][0]["description"] == "Legacy correspondence explanation"
    assert len(out["matches"][0]["code_snippets"]) == 1


def test_normalize_code_mapping_result_preserves_explanations():
    raw = {
        "matches": [
            {
                "entity_id": "sen_1",
                "content_type": "sentence",
                "content": "We use ResNet.",
                "reasoning": "The constructor instantiates the paper's backbone.",
                "description": "Legacy explanation",
                "code_snippets": [],
            }
        ]
    }

    out = normalize_code_mapping_result(raw)

    assert out["matches"][0]["reasoning"] == (
        "The constructor instantiates the paper's backbone."
    )
    assert out["matches"][0]["description"] == "Legacy explanation"


def test_normalize_code_result_for_frontend_alias():
    legacy = {
        "sections": [
            {
                "section_id": "sec_0",
                "code_snippets": [],
            }
        ]
    }
    out = normalize_code_result_for_frontend(legacy)
    assert "matches" in out
    assert out["matches"][0]["entity_id"] == "sec_0"


def test_merge_entities_into_matches():
    entities_result = {
        "entities": [
            {
                "content_type": "sentence",
                "entity_id": "sen_1",
                "content": "We use ResNet.",
                "section_id": "sec_2",
                "description": "Architecture choice",
            }
        ]
    }
    code_result = {
        "paper_title": "Atari-PB",
        "matches": [
            {
                "entity_id": "sen_1",
                "content_type": "sentence",
                "content": "We use ResNet.",
                "reasoning": "The model constructor instantiates ResNet50.",
                "code_snippets": [
                    {
                        "content": "ResNet50()",
                        "filepath": "model.py",
                        "start_line": 10,
                        "end_line": 12,
                    }
                ],
            }
        ],
    }
    merged = _merge_entities_into_matches(entities_result, code_result)
    assert merged["paper_title"] == "Atari-PB"
    assert len(merged["matches"]) == 1
    row = merged["matches"][0]
    assert row["reasoning"] == "The model constructor instantiates ResNet50."
    assert row["description"] == "Architecture choice"
    assert row["section_id"] == "sec_2"
    assert len(row["code_snippets"]) == 1


def test_hydrate_entity_contents():
    papermage = {
        "paper_title": "T",
        "n_pages": 1,
        "equations": [
            {
                "entity_id": "eq_0",
                "equation_content": "L = x + y",
                "page_index": 1,
                "box": {"page": 1, "l": 0, "t": 0, "w": 1, "h": 1},
            }
        ],
        "sections": [
            {
                "entity_id": "sec_1",
                "section_header": "Method",
                "section_content": "We train a model. It uses ResNet.",
                "page_index": 0,
                "box": {"page": 0, "l": 0, "t": 0, "w": 1, "h": 1},
                "paragraphs": [],
                "sentences": [
                    {
                        "entity_id": "sen_1",
                        "sentence_content": "We train a model.",
                        "page_index": 0,
                        "box": {"page": 0, "l": 0, "t": 0, "w": 1, "h": 1},
                    },
                    {
                        "entity_id": "sen_2",
                        "sentence_content": "It uses ResNet.",
                        "page_index": 0,
                        "box": {"page": 0, "l": 0, "t": 0, "w": 1, "h": 1},
                    },
                ],
            }
        ],
    }
    entities = [
        {"content_type": "section", "entity_id": "sec_1"},
        {"content_type": "sentence", "entity_id": "sen_2", "section_id": "sec_1"},
        {"content_type": "equation", "entity_id": "eq_0"},
    ]
    hydrate_entity_contents(entities, papermage)
    assert entities[0]["content"] == "We train a model. It uses ResNet."
    assert entities[1]["content"] == "It uses ResNet."
    assert entities[1]["section_id"] == "sec_1"
    assert entities[2]["content"] == "L = x + y"


def test_hydrate_entity_contents_sentence_without_section_id():
    papermage = {
        "paper_title": "T",
        "n_pages": 1,
        "equations": [],
        "sections": [
            {
                "entity_id": "sec_1",
                "section_header": "Method",
                "section_content": "It uses ResNet.",
                "page_index": 0,
                "box": {"page": 0, "l": 0, "t": 0, "w": 1, "h": 1},
                "paragraphs": [],
                "sentences": [
                    {
                        "entity_id": "sen_2",
                        "sentence_content": "It uses ResNet.",
                        "page_index": 0,
                        "box": {"page": 0, "l": 0, "t": 0, "w": 1, "h": 1},
                    }
                ],
            }
        ],
    }
    entities = [{"content_type": "sentence", "entity_id": "sen_2"}]
    hydrate_entity_contents(entities, papermage)
    assert entities[0]["content"] == "It uses ResNet."
    assert entities[0]["section_id"] == "sec_1"


def test_prepare_papermage_result_for_llm_strips_boxes_and_parent_text():
    papermage = {
        "paper_title": "T",
        "n_pages": 1,
        "equations": [
            {
                "entity_id": "eq_0",
                "equation_content": "L = x",
                "page_index": 1,
                "box": {"page": 1, "l": 0, "t": 0, "w": 1, "h": 1},
            }
        ],
        "sections": [
            {
                "entity_id": "sec_1",
                "section_header": "Method",
                "section_content": "body",
                "page_index": 0,
                "box": {"page": 0, "l": 0, "t": 0, "w": 1, "h": 1},
                "paragraphs": [{"entity_id": "prg_0", "paragraph_content": "p", "page_index": 0,
                                "box": {"page": 0, "l": 0, "t": 0, "w": 1, "h": 1}}],
                "sentences": [
                    {
                        "entity_id": "sen_1",
                        "sentence_content": "Method We train.",
                        "page_index": 0,
                        "box": {"page": 0, "l": 0, "t": 0, "w": 1, "h": 1},
                    }
                ],
            }
        ],
    }
    llm_view = prepare_papermage_result_for_llm(papermage)
    section = llm_view["sections"][0]
    assert "section_content" not in section
    assert "paragraphs" not in section
    assert "box" not in section
    assert "box" not in section["sentences"][0]
    assert "box" not in llm_view["equations"][0]
