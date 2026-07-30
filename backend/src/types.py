from datetime import datetime
from typing import Annotated, List, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class ContentEntity(BaseModel):
    content_type: Literal["section", "sentence", "equation"]
    entity_id: str
    content: str
    section_id: str | None = None


class CodeEntityMatch(BaseModel):
    entity_id: str
    content_type: Literal["section", "sentence", "equation"] = "section"
    content: str = ""
    section_id: str | None = None
    reasoning: str | None = None
    # Retained for cached analyses produced before reasoning became canonical.
    description: str | None = None
    code_snippets: list[CodeSnippet] = Field(default_factory=list)


class KeySectionsMappedSection(BaseModel):
    """Legacy section-centric match row (migrated to CodeEntityMatch)."""
    section_id: str
    section_header: str
    code_snippets: list[CodeSnippet]


class KeySectionsCodeResult(BaseModel):
    paper_title: str | None = None
    matches: list[CodeEntityMatch] = Field(default_factory=list)
    sections: list[KeySectionsMappedSection] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_sections(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if data.get("matches"):
            return data
        legacy = data.get("sections")
        if not isinstance(legacy, list):
            return data
        matches = []
        for item in legacy:
            if not isinstance(item, dict):
                continue
            section_id = item.get("section_id") or item.get("entity_id")
            if not isinstance(section_id, str):
                continue
            matches.append({
                "entity_id": section_id,
                "content_type": "section",
                "content": item.get("content")
                or item.get("section_content")
                or item.get("section_description")
                or "",
                "section_id": section_id,
                "reasoning": item.get("reasoning"),
                "description": item.get("section_description") or item.get("description"),
                "code_snippets": item.get("code_snippets") or [],
            })
        data["matches"] = matches
        return data


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
    entity_type: Literal["section", "sentence", "equation"] = "section"
    entity_id: str
    description: str
    section_id: str | None = None
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
        if data.get("section_id") == data.get("entity_id") and data.get("entity_type") == "section":
            data.setdefault("section_id", data.get("entity_id"))
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


class ContentToCodeMemoryHint(BaseModel):
    """One prior content-to-code interaction."""

    source_cache_key: str
    source_content: str
    verdict: str
    reasoning: str
    paths: list[str] = Field(default_factory=list)
    folders: list[str] = Field(default_factory=list)


class ContentToCodeMemorySnapshot(BaseModel):
    """The exact prior-mapping context used for one content-to-code request."""

    strategy: Literal["off", "recent"]
    version: Literal["v1"] = "v1"
    hints: list[ContentToCodeMemoryHint] = Field(default_factory=list)


class ContentToCodeResult(BaseModel):
    reasoning: str
    verdict: str
    code_snippets: list[CodeSnippet] = Field(
        default_factory=list
    )  # top-k snippets after rerank, ordered by relevance (empty if none found)
    memory_snapshot: ContentToCodeMemorySnapshot | None = None

    @model_validator(mode="before")
    @classmethod
    def discard_unknown_memory_snapshots(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        snapshot = data.get("memory_snapshot")
        if isinstance(snapshot, dict) and snapshot.get("strategy") not in {
            "off",
            "recent",
        }:
            data["memory_snapshot"] = None
        return data


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


######################
# Copilot Conversations
######################


class PaperEntityRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["paper_entity"] = "paper_entity"
    entity_id: str = Field(min_length=1)
    entity_type: Literal["section", "sentence", "equation"]
    section_id: str | None = None
    label: str = Field(min_length=1)


class CodeRangeRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["code_range"] = "code_range"
    filepath: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    label: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_line_range(self):
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class MappingRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["mapping"] = "mapping"
    mapping_type: Literal[
        "content_to_code", "code_to_content", "initial_analysis"
    ]
    cache_key: str | None = None
    entity_id: str | None = None
    filepath: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    label: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_optional_line_range(self):
        if (self.start_line is None) != (self.end_line is None):
            raise ValueError("start_line and end_line must be provided together")
        if (
            self.start_line is not None
            and self.end_line is not None
            and self.end_line < self.start_line
        ):
            raise ValueError("end_line must be greater than or equal to start_line")
        if self.start_line is not None and not self.filepath:
            raise ValueError("filepath is required when a line range is provided")
        return self


CopilotContextRef = Annotated[
    PaperEntityRef | CodeRangeRef | MappingRef,
    Field(discriminator="type"),
]

# Citations deliberately use the same stable references as user-attached context.
# The backend resolves context and validates agent-produced citations canonically.
CopilotCitation = Annotated[
    PaperEntityRef | CodeRangeRef | MappingRef,
    Field(discriminator="type"),
]


class CopilotMessageMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str | None = None
    prompt_version: str | None = None
    task_id: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    tool_calls: int | None = Field(default=None, ge=0)
    repo_commit_sha: str | None = None
    error: str | None = None


class CopilotMessage(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)
    created_at: datetime
    status: Literal["queued", "processing", "complete", "failed"] = "complete"
    context_refs: list[CopilotContextRef] = Field(default_factory=list)
    citations: list[CopilotCitation] = Field(default_factory=list)
    in_reply_to: UUID | None = None
    metadata: CopilotMessageMetadata | None = None


ConversationStatus = Literal["idle", "processing", "failed"]


class ConversationRecord(BaseModel):
    id: int
    paper_id: str
    user_id: int
    title: str | None = None
    messages: list[CopilotMessage] = Field(default_factory=list)
    summary: str | None = None
    summarized_through_message_id: UUID | None = None
    status: ConversationStatus = "idle"
    active_task_id: str | None = None
    version: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime


class SendCopilotMessageRequest(BaseModel):
    user_id: int = Field(gt=0)
    content: str = Field(min_length=1, max_length=20_000)
    context_refs: list[CopilotContextRef] = Field(default_factory=list)
    study_session_id: str | None = None


class StudySessionStartRequest(BaseModel):
    user_id: int = Field(gt=0)
    paper_id: str = Field(min_length=1)
    username: str | None = None
    paper_title: str | None = None
    client_meta: dict[str, object] | None = None


class StudyLogEvent(BaseModel):
    session_id: str = Field(min_length=1)
    group: Literal["ui", "navigation", "mapping", "copilot", "system"]
    event_type: str = Field(min_length=1)
    payload: dict[str, object] = Field(default_factory=dict)
    client_timestamp: datetime | None = None


class StudyLogBatchRequest(BaseModel):
    events: list[StudyLogEvent] = Field(min_length=1, max_length=100)


class StudySessionEndRequest(BaseModel):
    reason: str = "client_unload"
    duration_ms: int | None = Field(default=None, ge=0)


class CopilotTaskResult(BaseModel):
    conversation_id: int
    message_id: UUID
    task_id: str
    status: Literal["PENDING", "STARTED", "SUCCESS", "FAILURE"] = "PENDING"
