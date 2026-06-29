interface AgentTaskResult {
    paper_title: string | null;
    github_repo_url: string | null;
    code_result: codeSectionsResult | null;
};

interface codeSnippet {
    content: string;
    filepath: string;
    start_line: number;
    end_line: number;
    ranking: number;
}

interface codeSection {
    section_id: string;
    section_header: string;
    section_description: string;
    paper_start_line?: number;
    paper_end_line?: number;
    paper_section_description?: string;
    code_snippets: codeSnippet[];
  }
  /** Root object: `{ "sections": [ ... ] }` */
interface codeSectionsResult {
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
interface SectionEntity {
    entity_id: string,
    page_index: number,
    box: PaperMageBox,
    section_content: string;
    section_header: string;
}
interface processPDFResult {
    paper_title: string,
    n_pages: number,
    sections: SectionEntity[];
}

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
        sections: { section_id: string; description: string }[];
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
    sections: { section_id: string; description: string }[];
}

interface mapCodeToContentResponse {
    status: string;
    result: { section_id: string; description: string }[] | null;
    task_id: string | null;
}

export type { codeSection, 
    codeSnippet,
    codeSectionsResult, 
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
}
    