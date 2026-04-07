const API_URL: string =
  import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

/**
 * One section row after `analyze_paper`: code mapping fields plus paper anchors merged
 * from identify_key_sections (`paper_*` may be absent if matching failed).
 * 
 */

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
}

const submitPaperAnalysis = async (formData: FormData): Promise<paperSubmitResponse> => {
    const URL: string = API_URL + "/analyze";

    // POST to http://127.0.0.1:8000/analyze_paper and get job id back
    const response: Response = await fetch(URL, {
        method: "POST", 
        body: formData,
    })

    if (!response.ok) {
        console.error(response);
        throw new Error("Failed to submit paper analysis");
    }

    const responseJSON: paperSubmitResponse = await response.json();
    return responseJSON;
}

const getPaperAnalysisStatus = async (taskId: string): Promise<paperAnalysisStatusResponse> => {
    const URL: string = API_URL + "/tasks/" + taskId;
    const response: Response = await fetch(URL);

    if (!response.ok) {
        console.error(response);
        throw new Error("Failed to get paper analysis status");
    }

    const responseJSON: paperAnalysisStatusResponse = await response.json();
    return responseJSON;
}

export { submitPaperAnalysis, getPaperAnalysisStatus, type paperSubmitResponse, type paperAnalysisStatusResponse, type codeSectionsResult };