import argparse
import json
import logging
from pathlib import Path
from typing import List, Tuple

from papermage.magelib.box import Box
from papermage.magelib.entity import Entity
from papermage.magelib.names import ParagraphsFieldName, SentencesFieldName, TokensFieldName
from papermage.magelib.span import Span
from papermage.recipes import CoreRecipe

from src.papermage_compat import filter_noise_spans_from_papermage
from src.types import BoxModel, EquationEntity, PaperMageResult, ParagraphEntity, SectionEntity, SentenceEntity

logger = logging.getLogger("PAPERMAGE_PROCESSOR")


def compute_boxes_from_tokens(doc, entity) -> List[Box]:
    """Recover bounding boxes for an entity that has spans but no boxes.

    Some layers (notably `sentences`) are produced span-only by papermage, so
    they carry no boxes. We rebuild them by enclosing the boxes of the tokens
    the entity overlaps, grouping by page so we never construct a box that
    spans multiple pages (which `Box.create_enclosing_box` forbids).
    """
    boxes_by_page: dict[int, List[Box]] = {}
    for token in doc.intersect_by_span(entity, name=TokensFieldName):
        for box in token.boxes:
            boxes_by_page.setdefault(box.page, []).append(box)

    return [
        Box.create_enclosing_box(page_boxes)
        for _, page_boxes in sorted(boxes_by_page.items())
    ]


def entity_to_box_model(doc, entity) -> BoxModel | None:
    boxes = entity.boxes
    if len(boxes) == 0:
        boxes = compute_boxes_from_tokens(doc, entity)
    if len(boxes) == 0:
        return None
    box = boxes[0]
    return BoxModel(page=box.page, l=box.l, t=box.t, w=box.w, h=box.h)


def get_section_sentences_and_paragraphs(
    doc, body_start: int, body_end: int
) -> Tuple[List[SentenceEntity], List[ParagraphEntity]]:
    """Collect sentences and paragraphs whose spans fall within a section body."""
    if body_start >= body_end:
        return [], []

    body = Entity(spans=[Span(body_start, body_end)])

    sentences: List[SentenceEntity] = []
    for sent in doc.intersect_by_span(body, name=SentencesFieldName):
        box_model = entity_to_box_model(doc, sent)
        if box_model is None:
            logger.warning("No box found for sentence %s", sent.text[:80])
            continue
        sentences.append(
            SentenceEntity(
                entity_id=f"sen_{sent.id}",
                sentence_content=sent.text.strip(),
                page_index=box_model.page,
                box=box_model,
            )
        )

    paragraphs: List[ParagraphEntity] = []
    for para in doc.intersect_by_span(body, name=ParagraphsFieldName):
        box_model = entity_to_box_model(doc, para)
        if box_model is None:
            logger.warning("No box found for paragraph %s", para.text[:80])
            continue
        paragraphs.append(
            ParagraphEntity(
                entity_id=f"prg_{para.id}",
                paragraph_content=para.text.strip(),
                page_index=box_model.page,
                box=box_model,
            )
        )

    return sentences, paragraphs


def papermage_process(file_input: Path | bytes) -> PaperMageResult:
    recipe = CoreRecipe()
    doc = recipe.run(file_input, filetype="pdf")

    n_pages = len(doc.pages)

    result_payload = PaperMageResult(
        paper_title=doc.metadata.title or "Untitled",
        n_pages=n_pages,
        equations=[],
        sections=[],
    )

    sections = sorted(doc.sections, key=lambda s: s.start)
    skip_first_section = False
    abstract_body_start = 0
    abstract_body_end = 0

    if len(doc.abstracts) == 0:
        logger.warning("No abstract found directly, looking at the first section...")
        first_section = sections[0]
        if "abstract" in first_section.text.lower().replace(" ", ""):
            skip_first_section = True
            abstract_body_start = first_section.end
            abstract_body_end = (
                sections[1].start if len(sections) > 1 else len(doc.symbols)
            )
            abstract_content = doc.symbols[abstract_body_start:abstract_body_end].strip()
            abstract_box = entity_to_box_model(doc, first_section)
            if abstract_box is None:
                abstract_box = BoxModel(page=0, l=0, t=0, w=0, h=0)
        else:
            logger.warning("No abstract found!")
            abstract_content = "abstract not found"
            abstract_box = BoxModel(page=0, l=0, t=0, w=0, h=0)
    else:
        abstract = doc.abstracts[0]
        abstract_content = abstract.text
        abstract_body_start = abstract.start
        abstract_body_end = abstract.end
        abstract_box = entity_to_box_model(doc, abstract)
        if abstract_box is None:
            abstract_box = BoxModel(page=0, l=0, t=0, w=0, h=0)

    abstract_sentences, abstract_paragraphs = get_section_sentences_and_paragraphs(
        doc, abstract_body_start, abstract_body_end
    )
    result_payload.sections.append(
        SectionEntity(
            entity_id="abstract",
            section_header="abstract",
            section_content=abstract_content,
            page_index=abstract_box.page,
            box=abstract_box,
            paragraphs=abstract_paragraphs,
            sentences=abstract_sentences,
        )
    )

    for equation in sorted(doc.equations, key=lambda e: e.start):
        box_model = entity_to_box_model(doc, equation)
        if box_model is None:
            logger.warning("No box found for equation %s", equation.text[:80])
            continue
        result_payload.equations.append(
            EquationEntity(
                entity_id=f"eq_{equation.id}",
                equation_content=equation.text.strip(),
                page_index=box_model.page,
                box=box_model,
            )
        )

    for i, section in enumerate(sections):
        if skip_first_section and i == 0:
            continue

        body_start = section.end
        body_end = sections[i + 1].start if i + 1 < len(sections) else len(doc.symbols)

        box_model = entity_to_box_model(doc, section)
        if box_model is None:
            logger.warning("No box found for section %s", section.text[:80])
            continue

        sentences, paragraphs = get_section_sentences_and_paragraphs(doc, body_start, body_end)
        result_payload.sections.append(
            SectionEntity(
                entity_id=f"sec_{section.id}",
                section_header=section.text,
                section_content=doc.symbols[body_start:body_end].strip(),
                page_index=box_model.page,
                box=box_model,
                paragraphs=paragraphs,
                sentences=sentences,
            )
        )

    return filter_noise_spans_from_papermage(result_payload.model_dump())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", help="Input PDF path")
    parser.add_argument("--output", help="Output JSON path")

    args = parser.parse_args()

    with open(args.pdf, "rb") as f:
        result = papermage_process(f)

    with open(args.output, "w") as f:
        json.dump(result, f)
