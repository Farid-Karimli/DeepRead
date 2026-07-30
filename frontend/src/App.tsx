import { useState, useEffect, useMemo } from 'react'
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

import { logStudyEvent } from './utils/studyLog.ts';
import type { AgentTaskResult, codeEntityMatch, codeMatchesResult, codeSectionsResult } from './api/types.ts';
import { SidePanelProvider } from './context/SidePanelContext.tsx';
import { UserContext, type User } from './context/UserContext.tsx';
import { CopilotProvider } from './context/CopilotContext.tsx';
import { StudySessionProvider } from './context/StudySessionContext.tsx';
import CopilotChat from './components/CopilotChat.tsx';

/** Celery stores the agent return value: `{ github_repo_url, code_result }`. */


function extractGithubRepoUrl(result: unknown): string | null {
  if (!result || typeof result !== 'object') return null;
  const r = result as AgentTaskResult;
  if (!r.github_repo_url) return null;
  return r.github_repo_url as string;
}

function migrateLegacySectionsToMatches(
  sections: codeSectionsResult['sections'],
): codeEntityMatch[] {
  return sections.map((section) => ({
    entity_id: section.section_id,
    content_type: 'section' as const,
    content: section.section_description || section.section_header || '',
    section_id: section.section_id,
    reasoning: section.paper_section_description,
    description: section.section_description,
    code_snippets: section.code_snippets ?? [],
  }));
}

function extractCodeMatches(result: unknown): codeMatchesResult | null {
  if (!result || typeof result !== 'object') return null;
  const r = result as AgentTaskResult & Partial<codeMatchesResult & codeSectionsResult>;

  const codeResult = r.code_result;
  if (codeResult && typeof codeResult === 'object') {
    if ('matches' in codeResult && Array.isArray(codeResult.matches) && codeResult.matches.length > 0) {
      return { paper_title: codeResult.paper_title, matches: codeResult.matches };
    }
    if ('sections' in codeResult && Array.isArray(codeResult.sections) && codeResult.sections.length > 0) {
      return {
        paper_title: codeResult.paper_title,
        matches: migrateLegacySectionsToMatches(codeResult.sections),
      };
    }
  }

  if (Array.isArray(r.matches) && r.matches.length > 0) {
    return { paper_title: r.paper_title ?? undefined, matches: r.matches };
  }
  if (Array.isArray(r.sections) && r.sections.length > 0) {
    return { matches: migrateLegacySectionsToMatches(r.sections) };
  }
  return { matches: [] };
}

function App() {
  const [currentUser, setUser] = useState<User | null>(() => {
    const userString = localStorage.getItem('user');
    if (userString) {
      return JSON.parse(userString);
    }
    return null;
  });

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
      return status === 'SUCCESS' || status === 'FAILURE' ? false : 10000;
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
    // The PDF blob is immutable; refetching it (e.g. on window focus) creates a
    // new Blob identity, which forces react-pdf to destroy and reload the
    // document and leaves pages pointing at a dead pdf.js proxy.
    staleTime: Infinity,
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
    extractCodeMatches(paperMetadata.analysis_result) : null;

  const papermageResult = paperMetadata ? 
    paperMetadata.papermage_result : null;

  const githubRepoUrl = paperMetadata ? 
    extractGithubRepoUrl(paperMetadata.analysis_result) : null;

  // Memoized so the File identity is stable across re-renders. A fresh File on
  // every render makes react-pdf reload the document each time, destroying the
  // pdf.js worker that already-rendered pages (text + image layers) depend on.
  const paperFile = useMemo(
    () =>
      fileQuery.data && selectedPaperId
        ? new File([fileQuery.data], selectedPaperId, { type: 'application/pdf' })
        : undefined,
    [fileQuery.data, selectedPaperId],
  );

  
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
      if (response.status === 'PENDING' && response.task_id) {
        setTaskId(response.task_id);
      }
      if (response.status === 'SUCCESS') {
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
    logStudyEvent('system', 'clear_environment', {});
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
        <SidePanelProvider>
            <UserContext 
                value={{
                  currentUser, setUser
                }}>
                <CopilotProvider key={selectedPaperId}>
                  <StudySessionProvider
                    paperId={selectedPaperId}
                    userId={currentUser?.id}
                    username={currentUser?.username}
                    paperTitle={analysisResult.paper_title ?? undefined}
                  >
                  <PaperView
                    analysisResult={analysisResult}
                    processResult={papermageResult}
                    paperFile={paperFile}
                    tree={repoTree}
                    githubRepoUrl={githubRepoUrl}
                    paperId={selectedPaperId}
                    clearEnvironment={clearEnvironment}
                  />
                  <CopilotChat paperId={selectedPaperId} />
                  </StudySessionProvider>
                </CopilotProvider>
            </UserContext>
        </SidePanelProvider>
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
    <UserContext 
        value={{
          currentUser, setUser
        }}>
        <Home
          handlePaperSubmit={handlePaperSubmit}
          onOpenCachedPaper={openCachedPaper}
          errorMessage={submitError}
        />
   </UserContext>
  );
}

export default App;
