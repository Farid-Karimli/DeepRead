interface codeSection {
    section_id: string;
    section_header: string;
    section_description: string;
    paper_start_line?: number;
    paper_end_line?: number;
    paper_section_description?: string;
    code_snippets: {
        content: string;
        filepath: string;
        start_line: number;
        end_line: number;
    }[];
  }
  /** Root object: `{ "sections": [ ... ] }` */
  interface codeSectionsResult {
    sections: codeSection[];
  }

interface paperSubmitResponse {
    status: 'complete' | 'pending';
    task_id?: string;
    paper_id: string;
    result?: codeSectionsResult;
}

interface paperAnalysisStatusResponse {
    status: string;
    /** Celery success payload: `{ github_repo_url, code_result }` or cached equivalent */
    result?: unknown;
    /** Set when status === 'FAILURE'; human-readable reason from the worker exception. */
    error?: string;
}

interface paperByIdResponse {
    paper_id: string;
    file_url: string;
    analysis_result: codeSectionsResult;
    papermage_result: processPDFResult;

}

interface cachedPaperSummary {
    paper_id: string;
    paper_title?: string | null;
    github_repo_url?: string | null;
    section_count: number;
    label?: string | null;
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
}
interface processPDFResult {
    paper_title: string,
    n_pages: number,
    sections: SectionEntity[];
}

export type { codeSection, 
    codeSectionsResult, 
    paperSubmitResponse, 
    paperAnalysisStatusResponse, 
    paperByIdResponse, 
    cachedPaperSummary, 
    listCachedPapersResponse, 
    githubRepoTreeResponse,
    processPDFResult,
};