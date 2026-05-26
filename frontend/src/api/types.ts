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
    status: 'complete' | 'pending';
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

interface cachedPaperSummary {
    paper_id: string;
    paper_title?: string | null;
    github_repo_url?: string | null;
    section_count: number;
    label?: string | null;
}

interface CachedPaper {
    analysisResult: AgentTaskResult;
    papermageResult: processPDFResult;
    file: Uint8Array;
}

interface listCachedPapersResponse {
    papers: cachedPaperSummary[];
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

interface mapContentTaskResponse {
    task_id: string;
}

interface mapContentResponse {
    status: string;
    result?: codeSnippet;
}

export type { codeSection, 
    codeSnippet,
    codeSectionsResult, 
    paperSubmitResponse, 
    paperAnalysisStatusResponse, 
    paperByIdResponse, 
    cachedPaperSummary, 
    listCachedPapersResponse, 
    githubRepoTreeResponse,
    processPDFResult,
    AgentTaskResult,
    CachedPaper,
    mapContentTaskResponse,
    mapContentResponse,
};