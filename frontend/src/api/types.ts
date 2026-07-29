interface AgentTaskResult {
    paper_title: string | null;
    github_repo_url: string | null;
    code_result: codeMatchesResult | codeSectionsResult | null;
};

interface codeSnippet {
    content: string;
    filepath: string;
    start_line: number;
    end_line: number;
    ranking?: number;
}

type ContentEntityType = "section" | "paragraph" | "sentence" | "equation";

interface codeEntityMatch {
    entity_id: string;
    content_type: ContentEntityType;
    content: string;
    section_id?: string | null;
    description?: string;
    code_snippets: codeSnippet[];
}

interface codeMatchesResult {
    paper_title?: string;
    matches: codeEntityMatch[];
}

/** @deprecated Legacy section-centric match row; migrated to codeEntityMatch at read time. */
interface codeSection {
    section_id: string;
    section_header: string;
    section_description: string;
    paper_start_line?: number;
    paper_end_line?: number;
    paper_section_description?: string;
    code_snippets: codeSnippet[];
}

/** @deprecated Use codeMatchesResult; sections[] is migrated to matches[] at read time. */
interface codeSectionsResult {
    paper_title?: string;
    matches?: codeEntityMatch[];
    sections: codeSection[];
}

interface paperAnalysisPayload {
    analysis: AgentTaskResult;
    processed: processPDFResult;
}

interface paperSubmitResponse {
    status: string,
    task_id?: string;
    paper_id: string;
    result?: paperAnalysisPayload;
}

interface paperAnalysisStatusResponse {
    status: string;
    /** Celery success payload: `{ github_repo_url, code_result }` or cached equivalent */
    result?: paperAnalysisPayload;
    /** Set when status === 'FAILURE'; human-readable reason from the worker exception. */
    error?: string;
}

interface paperByIdResponse {
    paper_id: string;
    file_url: string;
    analysis_result: AgentTaskResult;
    papermage_result: processPDFResult;

}

interface PaperMetadataSummary {
    paper_id: string;
    paper_title?: string | null;
    github_repo_url?: string | null;
    section_count: number;
    label?: string | null;
    thumbnail_url?: string | null;
}

interface PaperMetadata {
    analysis_result: AgentTaskResult,
    papermage_result: processPDFResult;
    file_url: string,
    paper_id: string
}

interface listCachedPapersResponse {
    papers: PaperMetadataSummary[];
}

interface githubRepoTreeResponse {
    sha: string;
    url: string;
    tree: {
        path: string;
        mode: string; // 100644 for file, 40000 for directory
        url: string;
    }[];
    truncated: boolean;
}

interface PaperMageBox {
    page: number, 
    l: number, 
    t: number, 
    h: number, 
    w: number
}
interface ParagraphEntity {
    entity_id: string;
    paragraph_content: string;
    page_index: number;
    box: PaperMageBox;
}

interface SentenceEntity {
    entity_id: string;
    sentence_content: string;
    page_index: number;
    box: PaperMageBox;
}

interface EquationEntity {
    entity_id: string;
    equation_content: string;
    page_index: number;
    box: PaperMageBox;
}

interface SectionEntity {
    entity_id: string,
    page_index: number,
    box: PaperMageBox,
    section_content: string;
    section_header: string;
    paragraphs?: ParagraphEntity[];
    sentences?: SentenceEntity[];
}
interface processPDFResult {
    paper_title: string,
    n_pages: number,
    equations?: EquationEntity[];
    sections: SectionEntity[];
}

type PaperContentMatch = {
    entity_id: string;
    description: string;
    entity_type: ContentEntityType;
    section_id?: string | null;
    paragraph_id: string | null;
    sentence_id: string | null;
};

// This defines a content area (or selection) on the paper
interface paperContentBox {
    l: number, 
    t: number, 
    w: number, 
    h: number,
}

interface paperContentToCodeMatch {
    cache_key: string,
    paper_id: string,
    mapping_type: string,
    created_by?: number | null,
    inputs: {
        content: string,
        repo_url: string,
        context: string,
        box: paperContentBox,
        page_number?: number,
    },
    outputs: {
        verdict: string,
        reasoning: string,
        code_snippets: codeSnippet[],
    }
}

interface codeToContentMatch {
    cache_key: string,
    paper_id: string,
    mapping_type: string,
    created_by?: number | null,
    inputs: {
        code: string,
        filepath: string,
        start: number,
        end: number,
    },
    outputs: {
        verdict: string,
        reasoning: string,
        matches: PaperContentMatch[];
    }
}

interface mapContentTaskResponse {
    status: string;
    task_id: string | null;
    result: codeSnippet[] | null
}


interface mapContentResponse {
    status: string;
    result: codeSnippet[] | null;
}

interface codeToContentMappingResult {
    matches: codeToContentMatch[];
}

interface mapCodeToContentResponse {
    status: string;
    result?: {
        verdict: string,
        reasoning: string,
        matches: PaperContentMatch[];
    } | null,
    task_id: string | null;
}

type PaperEntityRef = {
    type: "paper_entity";
    entity_id: string;
    entity_type: "section" | "sentence" | "equation";
    section_id?: string | null;
    label: string;
};

type CodeRangeRef = {
    type: "code_range";
    filepath: string;
    start_line: number;
    end_line: number;
    label: string;
};

type MappingRef = {
    type: "mapping";
    mapping_type: "content_to_code" | "code_to_content" | "initial_analysis";
    cache_key?: string | null;
    entity_id?: string | null;
    filepath?: string | null;
    start_line?: number | null;
    end_line?: number | null;
    label: string;
};

type CopilotContextRef = PaperEntityRef | CodeRangeRef | MappingRef;
type CopilotCitation = CopilotContextRef;
type CopilotMessageStatus = "queued" | "processing" | "complete" | "failed";
type CopilotConversationStatus = "idle" | "processing" | "failed";

interface CopilotMessageMetadata {
    model?: string | null;
    prompt_version?: string | null;
    task_id?: string | null;
    duration_seconds?: number | null;
    input_tokens?: number | null;
    output_tokens?: number | null;
    tool_calls?: number | null;
    repo_commit_sha?: string | null;
    error?: string | null;
    [key: string]: unknown;
}

interface CopilotMessage {
    id: string;
    role: "user" | "assistant";
    content: string;
    created_at: string;
    status: CopilotMessageStatus;
    context_refs: CopilotContextRef[];
    citations: CopilotCitation[];
    in_reply_to?: string | null;
    metadata?: CopilotMessageMetadata | null;
}

interface CopilotConversation {
    id: number;
    paper_id: string;
    user_id: number;
    title?: string | null;
    messages: CopilotMessage[];
    summary?: string | null;
    summarized_through_message_id?: string | null;
    status: CopilotConversationStatus;
    active_task_id?: string | null;
    version: number;
    created_at: string;
    updated_at: string;
}

interface GetCopilotConversationResponse {
    conversation: CopilotConversation;
}

interface SendCopilotMessageRequest {
    user_id: number;
    content: string;
    context_refs: CopilotContextRef[];
}

interface SendCopilotMessageResponse {
    conversation: CopilotConversation;
    task_id: string;
    message_id: string;
    status: "PENDING";
}

export type { codeSection, 
    codeSnippet,
    codeEntityMatch,
    codeMatchesResult,
    codeSectionsResult,
    ContentEntityType,
    PaperMageBox,
    ParagraphEntity,
    SentenceEntity,
    EquationEntity,
    SectionEntity,
    paperSubmitResponse, 
    paperAnalysisStatusResponse, 
    paperByIdResponse, 
    PaperMetadataSummary, 
    PaperMetadata,
    listCachedPapersResponse, 
    githubRepoTreeResponse,
    processPDFResult,
    AgentTaskResult,
    mapContentTaskResponse,
    mapContentResponse,
    codeToContentMappingResult,
    mapCodeToContentResponse,
    paperContentToCodeMatch,
    paperContentBox,
    codeToContentMatch,
    PaperContentMatch,
    PaperEntityRef,
    CodeRangeRef,
    MappingRef,
    CopilotContextRef,
    CopilotCitation,
    CopilotMessageStatus,
    CopilotConversationStatus,
    CopilotMessageMetadata,
    CopilotMessage,
    CopilotConversation,
    GetCopilotConversationResponse,
    SendCopilotMessageRequest,
    SendCopilotMessageResponse,
}
