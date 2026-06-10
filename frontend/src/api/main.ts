import type { 
    paperSubmitResponse, 
    paperAnalysisStatusResponse, 
    codeSectionsResult, 
    paperByIdResponse, 
    cachedPaperSummary, 
    listCachedPapersResponse,
    githubRepoTreeResponse,
    CachedPaper,
    mapContentResponse,
    mapContentTaskResponse,
    mapCodeToContentResponse,
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

const getAvailPapers = async (): Promise<listCachedPapersResponse> => {
    const response: Response = await fetch(`${API_URL}/papers`);
    if (!response.ok) {
        throw new Error('Failed to get available papers from database.')
    }
    return response.json();
};

const getCachedPaperById = async (paperId: string): Promise<CachedPaper> => {
    // Returns the cached paper result and the file URL
    const response: Response = await fetch(`${API_URL}/papers/${encodeURIComponent(paperId)}`);
    if (!response.ok) {
        console.error(response);
        throw new Error("Failed to load cached paper");
    }
    const responseJSON: paperByIdResponse = await response.json();
    const fileUrl = responseJSON.file_url;
    const file = await getFileByUrl(fileUrl);
    return { analysisResult: responseJSON.analysis_result, file: file , papermageResult: responseJSON.papermage_result};
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

const downloadFile = async (link: string): Promise<Blob> => {
    const response: Response = await fetch(`${API_URL}/download_file?link=${link}`);
    if (!response.ok) {
        console.error(response);
        throw new Error("Failed to download file");
    }
    return response.blob();
};

const getGithubRepoTree = async (githubRepoUrl: string): Promise<githubRepoTreeResponse> => {
    const response: Response = await fetch(`${API_URL}/repos/tree?url=${githubRepoUrl}`);
    if (!response.ok) {
        console.error(response);
        throw new Error("Failed to get github repo tree");
    }
    const responseJSON: githubRepoTreeResponse = await response.json();
    return responseJSON;
};

const getGithubFileFromBlobUrl = async (githubBlobUrl: string): Promise<string> => {
    const response: Response = await fetch(`${API_URL}/repos/file?github_blob_url=${githubBlobUrl}`);
    if (!response.ok) {
        console.error(response);
        throw new Error("Failed to get github file from blob url");
    }
    const responseJSON: string = await response.text();
    return responseJSON;
};

const mapContentToCode = async (content: string | Blob, repoUrl: string, context: string, paperId: string): Promise<mapContentTaskResponse> => {
    const formData = new FormData();
    formData.append("content", content);
    formData.append("repo_url", repoUrl);
    formData.append("context", context);
    formData.append("paper_id", paperId);
    
    console.log(`Submitting content to code mapping: ${content} to ${repoUrl} with context ${context}`);

    const response: Response = await fetch(`${API_URL}/map_content_to_code`, {
        method: "POST",
        body: formData,
    });
    if (!response.ok) {
        console.error(response);
        throw new Error("Failed to map content to code");
    }
    const responseJSON: mapContentTaskResponse = await response.json();
    return responseJSON;
};

const getContentMappingStatus = async (taskId: string): Promise<mapContentResponse> => {
    const response: Response = await fetch(`${API_URL}/tasks/${taskId}`);
    if (!response.ok) {
        console.error(response);
        throw new Error("Failed to get content mapping status");
    }
    const responseJSON: mapContentResponse = await response.json();
    return responseJSON;
};

const mapCodeToContent = async (code: string, paperId: string): Promise<mapCodeToContentResponse> => {
    const formData = new FormData();
    formData.append("code", code);
    formData.append("paper_id", paperId);

    const response: Response = await fetch(`${API_URL}/map_code_to_content`, {
        method: "POST",
        body: formData,
    });
    if (!response.ok) {
        console.error(response);
        throw new Error("Failed to map code to content");
    }
    const responseJSON: mapCodeToContentResponse = await response.json();
    return responseJSON;
};

const getCodeMappingStatus = async (taskId: string): Promise<mapCodeToContentResponse> => {
    const response: Response = await fetch(`${API_URL}/tasks/${taskId}`);
    if (!response.ok) {
        console.error(response);
        throw new Error("Failed to get code mapping status");
    }
    const responseJSON: mapCodeToContentResponse = await response.json();
    return responseJSON;
};

export {
    submitPaperAnalysis,
    getPaperAnalysisStatus,
    getAvailPapers,
    getCachedPaperById,
    downloadFile,
    type paperSubmitResponse,
    type paperAnalysisStatusResponse,
    type codeSectionsResult,
    type cachedPaperSummary,
    type paperByIdResponse,
    type listCachedPapersResponse,
    type CachedPaper,
    type githubRepoTreeResponse,
    getGithubRepoTree,
    getGithubFileFromBlobUrl,
    mapContentToCode,
    getContentMappingStatus,
    mapCodeToContent,
    getCodeMappingStatus,
};