import { useState, useEffect } from 'react'
import './App.css'
import Home from './components/Home';
import PaperView from './components/PaperView.tsx';
import { SidePanelProvider } from './context/SidePanelContext.tsx';

import {
  submitPaperAnalysis,
  getPaperAnalysisStatus,
  getCachedPaperById,
  downloadFile,
  getGithubRepoTree,
  type paperSubmitResponse,
  type paperAnalysisStatusResponse,
  type codeSectionsResult,
  type CachedPaper,
  type githubRepoTreeResponse,
} from './api/main';
import type { processPDFResult, AgentTaskResult } from './api/types.ts';

/** Celery stores the agent return value: `{ github_repo_url, code_result }`. */


function extractGithubRepoUrl(result: unknown): string | null {
  if (!result || typeof result !== 'object') return null;
  const r = result as AgentTaskResult;
  if (!r.github_repo_url) return null;
  return r.github_repo_url as string;
}

function extractCodeSections(result: unknown): codeSectionsResult | null {
  if (!result || typeof result !== 'object') return null;
  const r = result as AgentTaskResult & codeSectionsResult;
  if (r.code_result?.sections) return r.code_result;
  if (Array.isArray(r.sections)) return r as codeSectionsResult;
  return null;
}

function App() {
  const [taskId, setTaskId] = useState<string | null>(() => {
    const taskId = localStorage.getItem('taskId');
    return taskId ?? null;
  });
  const [analysisResult, setAnalysisResult] = useState<codeSectionsResult | undefined>(() => {
    const analysisResult = localStorage.getItem('analysisResult');
    return analysisResult ? JSON.parse(analysisResult) : undefined;
  });
  const [papermageResult, setPaperMageResult] = useState<processPDFResult | undefined>(() => {
    const papermageResult = localStorage.getItem('papermageResult');
    return papermageResult ? JSON.parse(papermageResult) : undefined;
  });
  const [githubRepoTree, setGithubRepoTree] = useState<githubRepoTreeResponse | undefined>(() => {
    const githubRepoTree = localStorage.getItem('githubRepoTree');
    return githubRepoTree ? JSON.parse(githubRepoTree) : undefined;
  });
  const [paperId, setPaperId] = useState<string | null>(() => {
    const paperId = localStorage.getItem('paperId');
    return paperId ?? null;
  });
  const [githubRepoUrl, setGithubRepoUrl] = useState<string | undefined>(() => {
    const githubRepoUrl = localStorage.getItem('githubRepoUrl');
    return githubRepoUrl ?? undefined;
  });
  const [paperFile, setPaperFile] = useState<File | undefined>(undefined);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (taskId) {
      localStorage.setItem('taskId', taskId);
    } else {
      localStorage.removeItem('taskId');
    }
    if (analysisResult) {
      localStorage.setItem('analysisResult', JSON.stringify(analysisResult));
    } else {
      localStorage.removeItem('analysisResult');
    }
    if (papermageResult) {
      localStorage.setItem('papermageResult', JSON.stringify(papermageResult));
    } else {
      localStorage.removeItem('papermageResult');
    }
    if (paperId) {
      localStorage.setItem('paperId', paperId);
    } else {
      localStorage.removeItem('paperId');
    }
    if (githubRepoTree) {
      localStorage.setItem('githubRepoTree', JSON.stringify(githubRepoTree));
    } else {
      localStorage.removeItem('githubRepoTree');
    }
  }, [taskId, analysisResult, paperFile, paperId, githubRepoTree, papermageResult, githubRepoUrl]);

  useEffect(() => {
    if (!taskId || analysisResult) return;

    let cancelled = false;

    const poll = async () => {
      if (cancelled) return;
      try {
        const status: paperAnalysisStatusResponse = await getPaperAnalysisStatus(taskId);
        if (cancelled) return;

        if (status.status === 'SUCCESS' && status.result !== undefined && status.result !== null) {

          const sections: codeSectionsResult | null = extractCodeSections(status.result.analysis);
          const githubRepoUrl: string | null = extractGithubRepoUrl(status.result.analysis);
          const papermageResult: processPDFResult = status.result.processed;

          if (githubRepoUrl === null) {
            setSubmitError('Could not extract GitHub repository URL from the result.');
            setTaskId(null);
            return;
          }
          const tree: githubRepoTreeResponse = await getGithubRepoTree(githubRepoUrl);
          if (sections !== null && tree !== undefined && papermageResult !== null) {
            setGithubRepoTree(tree); 
            setAnalysisResult(sections);
            setPaperMageResult(papermageResult)
            setGithubRepoUrl(githubRepoUrl);
            return;
          }
          setSubmitError('Analysis finished but the result format was unexpected.');
          setTaskId(null);
          return;
        }

        if (status.status === 'FAILURE') {
          setSubmitError(status.error ?? 'Analysis failed. Check the Celery worker logs.');
          setTaskId(null);
          return;
        }

        setTimeout(poll, 5000);
      } catch {
        if (cancelled) return;
        setSubmitError('Could not reach the API. Is the backend running on http://127.0.0.1:8000?');
        setTaskId(null);
      }
    };

    poll();
    return () => {
      cancelled = true;
    };
  }, [taskId, analysisResult]);

  const handlePaperSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setSubmitError(null);
    const formData = new FormData(e.currentTarget);
    let file = formData.get('file');
 
    if (!(file instanceof File) || file.size === 0) {
      const link = formData.get('link') as string;
      if (!link || !link.startsWith('http')) {
        setSubmitError('Please choose a PDF file or provide a link.');
        return;
      }
      const blob: Blob = await downloadFile(link);
      file = new File([blob], link.split('/').pop() ?? 'paper.pdf', { type: 'application/pdf' });
      formData.set('file', file);
    }
    try {
      const response: paperSubmitResponse = await submitPaperAnalysis(formData);
      setPaperFile(file);
      setPaperId(response.paper_id);
      if (response.status === 'complete') {
        const sections = extractCodeSections(response.result);
        if (sections) {
          setAnalysisResult(sections);
          return;
        }
        setSubmitError('Analysis finished but the result format was unexpected.');
      } else {
        setTaskId(response.task_id ?? null);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Upload failed';
      setSubmitError(`${message}. Check the browser console and backend logs.`);
    }
  };

  const clearEnvironment = () => {
    setTaskId(null);
    setAnalysisResult(undefined);
    setPaperMageResult(undefined);
    setPaperFile(undefined);
    setPaperId(null);
    setSubmitError(null);
  };

  const openCachedPaper = async (id: string) => {
    setSubmitError(null);
    try {
      const cacheResponse: CachedPaper = await getCachedPaperById(id);
      const { analysisResult, papermageResult, file } = cacheResponse;
      const sections = extractCodeSections(analysisResult);
      const githubRepoUrl = extractGithubRepoUrl(analysisResult);

      console.log('sections', sections);
      console.log('papermageResult', papermageResult);
      console.log('githubRepoUrl', githubRepoUrl);

      if (sections && githubRepoUrl) {
        const tree: githubRepoTreeResponse = await getGithubRepoTree(githubRepoUrl);
        if (tree) {
          setGithubRepoTree(tree);
          console.log('tree', tree);
        }
        setPaperId(id);
        setPaperFile(new File([file.buffer as ArrayBuffer], id, { type: 'application/pdf' }));
        setAnalysisResult(sections);
        setPaperMageResult(papermageResult);
        setGithubRepoUrl(githubRepoUrl);
        return;
      }
      setSubmitError('Cached result format was unexpected.');
    } catch {
      setSubmitError('Could not load that paper from the server.');
    }
  };

  if (analysisResult && githubRepoTree && papermageResult && githubRepoUrl && paperId) {
    return (
      <SidePanelProvider>
        <PaperView
          analysisResult={analysisResult}
          processResult={papermageResult}
          clearEnvironment={clearEnvironment}
          paperFile={paperFile}
          tree={githubRepoTree}
          githubRepoUrl={githubRepoUrl}
          paperId={paperId}
        />
      </SidePanelProvider>  
    );
  }

  if (taskId) {
    return (
      <section id="center">
        <h1>Analyzing…</h1>
        <p>Your paper is being processed. This can take a few minutes.</p>
        <p style={{ opacity: 0.75, fontSize: '0.9rem' }}>Task ID: {taskId}</p>
        <button type="button" onClick={() => { setTaskId(null); setSubmitError(null); }}>
          Cancel
        </button>
      </section>
    );
  }

  return (
    <Home
      handlePaperSubmit={handlePaperSubmit}
      onOpenCachedPaper={openCachedPaper}
      errorMessage={submitError}
    />
  );
}

export default App;
