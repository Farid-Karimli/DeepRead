import { useState, useEffect } from 'react'
import './App.css'
import Home from './components/Home';
import PaperView from './components/PaperView.tsx';
import { useQueryClient, useQuery, useMutation } from '@tanstack/react-query';

import {
  submitPaperAnalysis,
  getPaperAnalysisStatus,
  getPaperById,
  getPaperFile,
  downloadFile,
  getGithubRepoTree,
} from './api/main';

import type { AgentTaskResult, codeSectionsResult } from './api/types.ts';

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

  const queryClient = useQueryClient();

  const [selectedPaperId, setSelectedPaperId] = useState<string | null>(() => {
    const selectedPaperId = localStorage.getItem('selectedPaperId');
    return selectedPaperId ?? null;
  });

  const [taskId, setTaskId] = useState<string | null>(() => {
    const taskId = localStorage.getItem('taskId');
    return taskId ?? null;
  });

  const [submitError, setSubmitError] = useState<string | null>(null);

  const taskQuery = useQuery({
    queryKey: ['tasks', taskId],
    queryFn: () => getPaperAnalysisStatus(taskId!),
    enabled: Boolean(taskId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'SUCCESS' || status === 'FAILURE' ? false : 5000;
    },
  })

  const paperQuery = useQuery({
    queryKey: ['papers', selectedPaperId],
    queryFn: () => {
      if (!selectedPaperId) throw new Error('No paper selected');
      return getPaperById(selectedPaperId);
    },
    enabled: Boolean(selectedPaperId) && !taskId,
  });

  const fileQuery = useQuery({
    queryKey: ['papers', selectedPaperId, 'file'],
    queryFn: () => {
      if (!paperQuery.data?.file_url) throw new Error('No file URL');
      return getPaperFile(paperQuery.data.file_url);
    },
    enabled: Boolean(paperQuery.data?.file_url),
  });

  useEffect(()=> {
    if (!taskQuery.data || !selectedPaperId) return;

    if (taskQuery.data.status === "SUCCESS") {
      setTaskId(null);
      queryClient.invalidateQueries({queryKey: ['papers', selectedPaperId]})
    }

    if (taskQuery.data.status === "FAILURE") {
      setTaskId(null);
      setSubmitError(taskQuery.data.error ?? "Analysis failed.");
    }
  }, [taskQuery.data, selectedPaperId, queryClient])
  
  const paperMetadata = paperQuery.data;

  const analysisResult = paperMetadata ? 
    extractCodeSections(paperMetadata.analysis_result) : null;

  const papermageResult = paperMetadata ? 
    paperMetadata.papermage_result : null;

  const githubRepoUrl = paperMetadata ? 
    extractGithubRepoUrl(paperMetadata.analysis_result) : null;

  const paperFile = fileQuery.data && selectedPaperId
    ? new File([fileQuery.data], selectedPaperId, { type: 'application/pdf' })
    : undefined;

  const repoTreeQuery = useQuery({
      queryKey: ['repos', githubRepoUrl, 'tree'],
      queryFn: () => getGithubRepoTree(githubRepoUrl!),
      enabled: Boolean(githubRepoUrl),
  });

  const repoTree = repoTreeQuery.data ?? null;

  const analyzeMutation = useMutation({
    mutationFn: submitPaperAnalysis,
    onSuccess: (response) => {
      setSelectedPaperId(response.paper_id);
      if (response.status === 'pending' && response.task_id) {
        setTaskId(response.task_id);
      }
      if (response.status === 'complete') {
        setTaskId(null);
        queryClient.invalidateQueries({ queryKey: ['papers', response.paper_id] });
      }
    },
  });
  
  useEffect(() => {
    if (taskId) {
      localStorage.setItem('taskId', taskId);
    } else {
      localStorage.removeItem('taskId');
    }
  }, [taskId]);

  useEffect(() => {
    if (selectedPaperId) {
      localStorage.setItem('selectedPaperId', selectedPaperId);
    } else {
      localStorage.removeItem('selectedPaperId')
    }
  }, [selectedPaperId])

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

    analyzeMutation.mutate(formData);
  };

  const clearEnvironment = () => {
    setTaskId(null);
    setSelectedPaperId(null);
    setSubmitError(null);
  };

  const openCachedPaper = async (id: string) => {
    setSubmitError(null);
    setSelectedPaperId(id);
  };

  if (
    selectedPaperId &&
    paperFile &&
    analysisResult &&
    papermageResult &&
    githubRepoUrl &&
    repoTree
  ) {
    return (
      <PaperView
        analysisResult={analysisResult}
        processResult={papermageResult}
        paperFile={paperFile}
        tree={repoTree}
        githubRepoUrl={githubRepoUrl}
        paperId={selectedPaperId}
        clearEnvironment={clearEnvironment}
      />
    );
  }

  if (analyzeMutation.isPending) {
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
