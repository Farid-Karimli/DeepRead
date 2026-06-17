import type { 
    paperSubmitResponse, 
    paperAnalysisStatusResponse, 
    PaperMetadata,
    listCachedPapersResponse,
    githubRepoTreeResponse,
    mapContentResponse,
    mapContentTaskResponse,
    mapCodeToContentResponse,
    paperContentToCodeMatch,
    paperContentBox,
    codeToContentMatch,
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

    return response.json();
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

const getPaperById = async (paperId: string): Promise<PaperMetadata> => {
    return fetch(`${API_URL}/papers/${encodeURIComponent(paperId)}`).then(r => r.json());
  };

const getPaperFile = async (fileUrl: string): Promise<Blob> => {
    return fetch(fileUrl).then(r => r.blob());
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
    return response.json();
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

const getContentToCodeMatches = async (paperId: string): Promise<paperContentToCodeMatch[]> => {
    const response = await fetch(`${API_URL}/get_content_to_code_matches?paper_id=${paperId}`);
    if (!response.ok) {
        throw new Error(`Error retrieving content to code matches for ${paperId}`)
    }
    const responseJSON: { matches: paperContentToCodeMatch[] } = await response.json();
    return responseJSON.matches;
}

const mapContentToCode = async (content: string | Blob, repoUrl: string, context: string, paperId: string, box: paperContentBox, pageNumber: number): Promise<mapContentTaskResponse> => {
    const formData = new FormData();
    formData.append("content", content);
    formData.append("repo_url", repoUrl);
    formData.append("context", context);
    formData.append("paper_id", paperId);
    formData.append("box", JSON.stringify(box));
    formData.append("page_number", String(pageNumber));
    
    const response: Response = await fetch(`${API_URL}/map_content_to_code`, {
        method: "POST",
        body: formData,
    });
    
    if (!response.ok) {
        throw new Error(`Failed to map content to code: ${response}`);
    }
    return response.json();
};

const getTaskStatus = async (taskId: string): Promise<mapContentResponse> => {
    const response: Response = await fetch(`${API_URL}/tasks/${taskId}`);
    if (!response.ok) {
        console.error(response);
        throw new Error("Failed to get content mapping status");
    }
    const responseJSON: mapContentResponse = await response.json();
    return responseJSON;
};

const getCodeToContentMatches = async (paperId: string, currentPath: string): Promise<codeToContentMatch[]> => {
    const response = await fetch(`${API_URL}/get_code_to_content_matches?paper_id=${paperId}&current_path=${currentPath}`);
    if (!response.ok) {
        throw new Error(`Error retrieving code to content matches for ${paperId} and ${currentPath}`)
    }
    const responseJSON: { matches: codeToContentMatch[] } = await response.json();
    return responseJSON.matches;
}

const mapCodeToContent = async (code: string, paperId: string, start: number, end: number, filepath: string): Promise<mapCodeToContentResponse> => {
    const formData = new FormData();
    formData.append("code", code);
    formData.append("paper_id", paperId);
    formData.append("start", String(start));
    formData.append("end", String(end));
    formData.append("filepath", filepath);

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
    getPaperById,
    getPaperFile,
    downloadFile,
    getGithubRepoTree,
    getGithubFileFromBlobUrl,
    mapContentToCode,
    getTaskStatus,
    mapCodeToContent,
    getCodeMappingStatus,
    getContentToCodeMatches,
    getCodeToContentMatches
};