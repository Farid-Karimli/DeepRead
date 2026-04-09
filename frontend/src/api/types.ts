interface codeSection {
    section_name: string;
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
    result: codeSectionsResult;
    file_url: string;
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

export type { codeSection, codeSectionsResult, paperSubmitResponse, paperAnalysisStatusResponse, paperByIdResponse, cachedPaperSummary, listCachedPapersResponse };