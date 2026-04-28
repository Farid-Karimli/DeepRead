#!/usr/bin/env python3
"""
Render a PDF as a self-contained HTML file using papermage's semantic extraction.

Approach:
  - Each page is rendered as a background image (72 DPI)
  - Detected figure regions are re-rasterized at high DPI and overlaid in place
  - All text tokens are positioned as transparent <span> elements for selection/search
  - Semantic structure (sections, paragraphs, equations, captions) is preserved as
    data attributes for potential JS interaction
"""

import argparse
import json
import sys
from pathlib import Path
from pydantic import BaseModel

from typing import List

from papermage.magelib.box import Box
from papermage.magelib.metadata import Metadata
from papermage.magelib.span import Span
from papermage.recipes import CoreRecipe
from papermage.rasterizers.rasterizer import PDF2ImageRasterizer

# Same as papermage.magelib.box.Box
class BoxModel(BaseModel):
    page: int
    l: float
    t: float
    w: float
    h: float

class SectionEntity(BaseModel):
    entity_id: str
    page_index: int
    box: BoxModel

class ProcessedPdf(BaseModel):
    paper_title: str
    n_pages: int
    sections: List[SectionEntity] # list of list of sections for each page

def render(pdf_path: str, output_path: str) -> ProcessedPdf:
    print("Parsing PDF with CoreRecipe...", file=sys.stderr)
    recipe = CoreRecipe()
    doc = recipe.run(pdf_path)
    display_width = 900

    n_pages = len(doc.pages)
    print(f"PDF has {n_pages} pages", file=sys.stderr)
    print(f"PDF metadata: {doc.metadata}", file=sys.stderr)

    result_payload = ProcessedPdf(
        paper_title=doc.metadata.title or "Untitled",
        n_pages=n_pages,
        sections=[],
    )

    # Build per-page lookup tables for each semantic layer
    def boxes_on_page(entities, page_idx):
        result = []
        for ent in entities:
            for box in ent.boxes:
                if box.page == page_idx:
                    result.append((ent, box))
        return result


    for page_idx, page_img_entity in enumerate(doc.images):
        page_img = page_img_entity.pilimage
        page_w, page_h = page_img.size
        aspect = page_h / page_w
        display_h = int(display_width * aspect)

        sections = []

        # Unused right now
        semantic_layers = [
            # ("equation", doc.equations),
            ("section", doc.sections),
            # ("paragraph", doc.paragraphs),
            # ('sentences', doc.sentences),
        ]
        for section in doc.sections:
            box = section.boxes[0]
            if box.page == page_idx:
                box_model = BoxModel(page=box.page, l=box.l, t=box.t, w=box.w, h=box.h)
                result_payload.sections.append(SectionEntity(entity_id=f"sec_{section.id}", page_index=page_idx, box=box_model))
    

    with open(output_path, "w") as f:
        json.dump(result_payload.model_dump(), f)




if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", help="Input PDF path")
    parser.add_argument("--output", help="Output JSON path")
    
    args = parser.parse_args()
    print(render(args.pdf, args.output))