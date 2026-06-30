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
        code_snippet: codeSnippet | null,
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
    result: codeSnippet | null
}


interface mapContentResponse {
    status: string;
    result: codeSnippet | null;
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
}
    