import copy
import re
from typing import Any

from src.types import PaperMageResult

_EXCLUDE_HEADERS = re.compile(
    r"^(Introduction|Discussion|Acknowledgements?|References?|Conclusion|Related Work)s?$",
    re.IGNORECASE,
)

_DEFAULT_BOX = {"page": 0, "l": 0.0, "t": 0.0, "w": 0.0, "h": 0.0}


def is_noise_span_text(text: str) -> bool:
    """Drop chart ticks, table fragments, and other non-prose spans from PaperMage."""
    stripped = re.sub(r"\s+", " ", (text or "").strip())
    if not stripped or len(stripped) <= 3:
        return True

    alpha = [c for c in stripped if c.isalpha()]
    digits = sum(c.isdigit() for c in stripped)
    tokens = stripped.replace(".", "").split()

    if re.fullmatch(r"[\d\s.,+\-−%:;>]+", stripped):
        return True
    if len(stripped) <= 20 and digits > 0 and len(alpha) <= 3:
        return True
    if len(tokens) >= 3 and all(len(t) <= 2 for t in tokens):
        return True
    if len(stripped) <= 8 and stripped.endswith(".") and len(tokens) <= 2 and len(alpha) <= 3:
        return True
    if len(stripped) <= 40 and re.search(r"\s0\s*\.$", stripped) and digits >= 2:
        return True
    single_alpha = sum(1 for t in tokens if len(t) == 1 and t.isalpha())
    if len(stripped) <= 30 and single_alpha >= 3:
        return True
    return False


def filter_noise_spans_from_papermage(papermage: dict[str, Any]) -> dict[str, Any]:
    """Remove noisy sentences/paragraphs from each section."""
    for section in papermage.get("sections", []):
        if not isinstance(section, dict):
            continue
        section["sentences"] = [
            s for s in section.get("sentences", [])
            if isinstance(s, dict) and not is_noise_span_text(s.get("sentence_content", ""))
        ]
        section["paragraphs"] = [
            p for p in section.get("paragraphs", [])
            if isinstance(p, dict) and not is_noise_span_text(p.get("paragraph_content", ""))
        ]
    return papermage


def _default_nested_lists(section: dict) -> dict:
    out = dict(section)
    out.setdefault("paragraphs", [])
    out.setdefault("sentences", [])
    return out


def _legacy_entity_to_section(entity: dict) -> dict | None:
    header = entity.get("section_header")
    if not isinstance(header, str) or not header.strip():
        return None
    entity_id = entity.get("entity_id") or entity.get("section_id")
    if not isinstance(entity_id, str) or not entity_id:
        entity_id = f"sec_legacy_{hash(header) & 0xFFFF}"
    box = entity.get("box") if isinstance(entity.get("box"), dict) else _DEFAULT_BOX
    page_index = entity.get("page_index")
    if not isinstance(page_index, int):
        page_index = box.get("page", 0)
    return {
        "entity_id": entity_id,
        "section_header": header,
        "section_content": entity.get("section_content") or entity.get("content") or "",
        "page_index": page_index,
        "box": box,
        "paragraphs": entity.get("paragraphs") or [],
        "sentences": entity.get("sentences") or [],
    }


def normalize_papermage_result(raw: dict[str, Any]) -> dict[str, Any]:
    """Return PaperMageResult-shaped dict from new or legacy input."""
    if not isinstance(raw, dict):
        raise TypeError(f"Expected dict papermage result, got {type(raw).__name__}")

    payload: dict[str, Any]

    if isinstance(raw.get("sections"), list):
        payload = {
            "paper_title": raw.get("paper_title") or "Untitled",
            "n_pages": raw.get("n_pages") or 0,
            "equations": raw.get("equations") if isinstance(raw.get("equations"), list) else [],
            "sections": [_default_nested_lists(s) for s in raw["sections"] if isinstance(s, dict)],
        }
    elif isinstance(raw.get("entities"), list):
        sections = []
        for entity in raw["entities"]:
            if not isinstance(entity, dict):
                continue
            section = _legacy_entity_to_section(entity)
            if section is not None:
                sections.append(section)
        payload = {
            "paper_title": raw.get("paper_title") or "Untitled",
            "n_pages": raw.get("n_pages") or 0,
            "equations": raw.get("equations") if isinstance(raw.get("equations"), list) else [],
            "sections": sections,
        }
    else:
        payload = {
            "paper_title": raw.get("paper_title") or "Untitled",
            "n_pages": raw.get("n_pages") or 0,
            "equations": [],
            "sections": [],
        }

    validated = PaperMageResult.model_validate(payload)
    return filter_noise_spans_from_papermage(validated.model_dump())


def filter_sections_for_key_identification(papermage: dict[str, Any]) -> dict[str, Any]:
    """Return papermage copy with non-implementation sections removed from sections[]."""
    normalized = normalize_papermage_result(papermage)
    filtered = copy.deepcopy(normalized)
    kept = []
    for section in filtered.get("sections", []):
        if not isinstance(section, dict):
            continue
        header = section.get("section_header")
        if not isinstance(header, str):
            continue
        if _EXCLUDE_HEADERS.match(header.strip()):
            continue
        kept.append(section)
    filtered["sections"] = kept
    return filtered
