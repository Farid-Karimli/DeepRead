from datetime import datetime
from typing import List, Literal
from pydantic import BaseModel

#############################
# Key Section Analysis and PaperMage Result
# These are 1:1 with the paper
#############################

class CodeSnippet(BaseModel):
    content: str
    filepath: str
    start_line: int
    end_line: int

class KeySectionsMappedSection(BaseModel):
    section_id: str
    section_header: str
    code_snippets: list[CodeSnippet]

class KeySectionsCodeResult(BaseModel):
    paper_title: str
    sections: list[KeySectionsMappedSection]

class KeySectionsResult(BaseModel):
    """
        Result of the initial paper analysis. 
        (1) Identify key sections, (2) Map key sections to code.
    """
    paper_title: str
    github_repo_url: str
    code_result: KeySectionsCodeResult

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

class PaperMageResult(BaseModel):
    paper_title: str
    n_pages: int
    sections: List[SectionEntity] # list of list of sections for each page


######################
# Ad-hoc User Selection Results
# (content->code and code->content)
# These get their own table as they can grow big for a paper and have 2 types. 
######################

class PaperContentBox(BaseModel):
    l: float
    t: float
    w: float
    h: float

class CodeToContentSection(BaseModel):
    section_id: str
    description: str


class ContentToCodeResult(BaseModel):
    reasoning: str
    verdict: str
    code_snippet: CodeSnippet | None # matches what we return today after rerank or if nothing was found

class CodeToContentResult(BaseModel):
    sections: list[CodeToContentSection]  # section_id + description


class ContentToCodeInputs(BaseModel):
    content: str            # paper content selected by the user
    repo_url: str
    context: str            # surrounding context of the user's selection (auto-selected)
    box: PaperContentBox
    page_number: int | None = None  # zero-based page index of the selection

class CodeToContentInputs(BaseModel):
    code: str                 # code snippet selected by the user

class PaperMappingRecord(BaseModel):
    paper_id: str
    mapping_type: Literal["content_to_code", "code_to_content"]
    cache_key: str
    inputs: ContentToCodeInputs | CodeToContentInputs
    outputs: ContentToCodeResult | CodeToContentResult

class PaperRecord(BaseModel):
    id: str
    paper_title: str
    github_link: str
    created_at: datetime
    papermage_result: PaperMageResult | None = None
    analysis_result: KeySectionsResult | None = None
