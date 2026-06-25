from datetime import datetime
from typing import List, Literal

from pydantic import BaseModel, Field, model_validator


class UserRecord(BaseModel):
    id: int
    username: str
    created_at: datetime | None = None


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

class ParagraphEntity(BaseModel):
    entity_id: str
    paragraph_content: str
    page_index: int
    box: BoxModel

class EquationEntity(BaseModel):
    entity_id: str
    equation_content: str
    page_index: int
    box: BoxModel

class SentenceEntity(BaseModel):
    entity_id: str
    sentence_content: str
    page_index: int
    box: BoxModel

class SectionEntity(BaseModel):
    entity_id: str
    section_header: str
    section_content: str # Full section content
    paragraphs: List[ParagraphEntity] = Field(default_factory=list)
    sentences: List[SentenceEntity] = Field(default_factory=list)
    page_index: int
    box: BoxModel

class PaperMageResult(BaseModel):
    paper_title: str
    n_pages: int
    equations: List[EquationEntity] = Field(default_factory=list)
    sections: List[SectionEntity]  # list of list of sections for each page


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


class CodeToContentMatch(BaseModel):
    entity_type: Literal["section", "paragraph", "sentence", "equation"] = "section"
    entity_id: str
    description: str
    paragraph_id: str | None = None
    sentence_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_fields(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if "entity_id" not in data and "section_id" in data:
            data["entity_id"] = data["section_id"]
        data.setdefault("entity_type", "section")
        return data


class CodeToContentResult(BaseModel):
    verdict: str
    reasoning: str
    matches: list[CodeToContentMatch] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_sections(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if not data.get("matches") and data.get("sections"):
            data["matches"] = [
                {
                    "entity_type": "section",
                    "entity_id": item["section_id"],
                    "description": item["description"],
                }
                for item in data["sections"]
                if isinstance(item, dict) and "section_id" in item
            ]
        data.setdefault("matches", [])
        return data


class ContentToCodeResult(BaseModel):
    reasoning: str
    verdict: str
    code_snippet: (
        CodeSnippet | None
    )  # matches what we return today after rerank or if nothing was found


class ContentToCodeInputs(BaseModel):
    content: str  # paper content selected by the user
    repo_url: str
    context: str  # surrounding context of the user's selection (auto-selected)
    box: PaperContentBox
    page_number: int | None = None  # zero-based page index of the selection


class CodeToContentInputs(BaseModel):
    code: str  # code snippet selected by the user
    start: int
    end: int
    filepath: str


class PaperMappingRecord(BaseModel):
    paper_id: str
    mapping_type: Literal["content_to_code", "code_to_content"]
    cache_key: str
    inputs: ContentToCodeInputs | CodeToContentInputs
    outputs: ContentToCodeResult | CodeToContentResult
    created_by: int | None = None  # foreign key to UserRecord.id


class PaperRecord(BaseModel):
    id: str
    paper_title: str
    github_link: str
    created_at: datetime
    papermage_result: PaperMageResult | None = None
    analysis_result: KeySectionsResult | None = None
