import argparse
import json
from pprint import pprint
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
    section_header: str
    section_content: str
    page_index: int
    box: BoxModel

class ProcessedPdf(BaseModel):
    paper_title: str
    n_pages: int
    sections: List[SectionEntity] # list of list of sections for each page

def papermage_process(file_input: Path | bytes) -> ProcessedPdf:
    print("Parsing PDF with CoreRecipe...", file=sys.stderr)
    recipe = CoreRecipe()
    doc = recipe.run(file_input, filetype="pdf")
    display_width = 900

    n_pages = len(doc.pages)
    #print(f"PDF has {n_pages} pages", file=sys.stderr)
    #print(f"PDF metadata: {doc.metadata}", file=sys.stderr)

    result_payload = ProcessedPdf(
        paper_title=doc.metadata.title or "Untitled",
        n_pages=n_pages,
        sections=[],
    )

    # Add abstract for model context
    content = doc.symbols
    abstract = [abstract for abstract in doc.abstracts if len(abstract.text) > 5][0]
    abstract_content = abstract.text
    abstract_box = abstract.boxes[0]
    result_payload.sections.append(
        SectionEntity(entity_id=f"abstract", 
                section_header="abstract", 
                section_content=abstract_content,
                page_index=0,
                box=BoxModel(page=abstract_box.page, l=abstract_box.l, t=abstract_box.t, w=abstract_box.w, h=abstract_box.h)
        )
    )

    # Unused right now
    semantic_layers = [
        # ("equation", doc.equations),
        ("section", doc.sections),
        # ("paragraph", doc.paragraphs),
        # ('sentences', doc.sentences),
    ]

    # Go through sections
    sections = sorted(doc.sections, key=lambda s: s.start)

    for i, section in enumerate(sections):
        body_start = section.end
        body_end = sections[i + 1].start if i + 1 < len(sections) else len(doc.symbols)

        box = section.boxes[0]
        rows = section.rows
        
        section_header = section.text
        section_content = doc.symbols[body_start:body_end].strip()

        box_model = BoxModel(page=box.page, l=box.l, t=box.t, w=box.w, h=box.h)
        result_payload.sections.append(
                SectionEntity(entity_id=f"sec_{section.id}", 
                section_header=section_header, 
                section_content=section_content,
                page_index=box.page, 
                box=box_model)
            )

    result = result_payload.model_dump()
    return result




if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", help="Input PDF path")
    parser.add_argument("--output", help="Output JSON path")

    args = parser.parse_args()
    
    with open(args.pdf, 'rb') as f:
       result = papermage_process(f)

    with open(args.output, 'w') as f:
        json.dump(result, f)