const API_URL: string =
  import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

/** Matches backend `code_section_schema` in agent.py (map_key_sections_to_code output shape). */
interface codeSection {
    section_name: string;
    section_description: string;
    code_snippet: string;
    code_filepath: string;
    code_start_line: number;
    code_end_line: number;
  }
  /** Root object: `{ "sections": [ ... ] }` */
  interface codeSectionsResult {
    sections: codeSection[];
  }

interface paperSubmitResponse {
    task_id: string;
    paper_id?: string;
}

interface paperAnalysisStatusResponse {
    status: string;
    /** Celery success payload: full agent dict `{ key_sections, code_result }` or cached equivalent */
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