import type { 
    paperSubmitResponse, 
    paperAnalysisStatusResponse, 
    codeSectionsResult, 
    paperByIdResponse, 
    cachedPaperSummary, 
    listCachedPapersResponse 
} from './types';

const API_URL: string =
  import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

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

const listCachedPapers = async (): Promise<cachedPaperSummary[]> => {
    const response: Response = await fetch(`${API_URL}/papers`);
    if (!response.ok) {
        console.error(response);
        throw new Error("Failed to list cached papers");
    }
    const body: listCachedPapersResponse = await response.json();
    return body.papers ?? [];
};

interface Paper {
    result: codeSectionsResult;
    file: Uint8Array;
}

const getCachedPaperById = async (paperId: string): Promise<Paper> => {
    // Returns the cached paper result and the file URL
    const response: Response = await fetch(`${API_URL}/papers/${encodeURIComponent(paperId)}`);
    if (!response.ok) {
        console.error(response);
        throw new Error("Failed to load cached paper");
    }
    const responseJSON: paperByIdResponse = await response.json();
    const fileUrl = responseJSON.file_url;
    const file = await getFileByUrl(fileUrl);
    return { result: responseJSON.result, file: file };
};

const getFileByUrl = async (url: string): Promise<Uint8Array> => {
    const response: Response = await fetch(url);
    if (!response.ok) {
        console.error(response);
        throw new Error("Failed to get file by URL");
    }
    const responseBuffer: ArrayBuffer = await response.arrayBuffer();
    return new Uint8Array(responseBuffer);
};

export {
    submitPaperAnalysis,
    getPaperAnalysisStatus,
    listCachedPapers,
    getCachedPaperById,
    type paperSubmitResponse,
    type paperAnalysisStatusResponse,
    type codeSectionsResult,
    type cachedPaperSummary,
    type paperByIdResponse,
    type listCachedPapersResponse,
    type Paper,
};