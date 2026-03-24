import { useState, useEffect } from 'react'
import './App.css'
import Home from './components/Home';
import PaperView from './components/PaperView.tsx';

import { submitPaperAnalysis, getPaperAnalysisStatus, type paperSubmitResponse, type paperAnalysisStatusResponse, type codeSectionsResult } from './api/main';

/** Celery stores the agent return value: `{ key_sections, code_result }`. */
type AgentTaskResult = {
  key_sections?: unknown;
  code_result?: codeSectionsResult;
};

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
  }, [taskId, analysisResult, paperFile]);

  useEffect(() => {
    if (!taskId || analysisResult) return;

    let cancelled = false;

    const poll = async () => {
      if (cancelled) return;
      try {
        const status: paperAnalysisStatusResponse = await getPaperAnalysisStatus(taskId);
        if (cancelled) return;

        if (status.status === 'SUCCESS' && status.result !== undefined && status.result !== null) {
          const sections = extractCodeSections(status.result);
          if (sections) {
            setAnalysisResult(sections);
            return;
          }
          setSubmitError('Analysis finished but the result format was unexpected.');
          setTaskId(null);
          return;
        }

        if (status.status === 'FAILURE') {
          setSubmitError('Analysis failed. Check the Celery worker logs.');
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
    const file = formData.get('file');
    if (!(file instanceof File) || file.size === 0) {
      setSubmitError('Please choose a PDF file.');
      return;
    }
    try {
      const response: paperSubmitResponse = await submitPaperAnalysis(formData);
      setPaperFile(file);
      setTaskId(response.task_id);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Upload failed';
      setSubmitError(`${message}. Check the browser console and backend logs.`);
    }
  };

  const clearEnvironment = () => {
    setTaskId(null);
    setAnalysisResult(undefined);
    setPaperFile(undefined);
    setSubmitError(null);
  };

  if (analysisResult) {
    return (
      <PaperView
        analysisResult={analysisResult}
        clearEnvironment={clearEnvironment}
        paperFile={paperFile}
      />
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

  return <Home handlePaperSubmit={handlePaperSubmit} errorMessage={submitError} />;
}

export default App;
