import {
    ContextProvider,
    DocumentContext,
    DocumentWrapper,
    getPageWidth,
    Overlay,
    PageWrapper,
    RENDER_TYPE,
    TransformContext,
} from '@allenai/pdf-components';
import React, { useContext, useEffect, useMemo, useRef, useState } from 'react';
import { IoChevronDown } from 'react-icons/io5';
import { Group, Panel, Separator } from "react-resizable-panels";
import { useQuery, useMutation, useQueryClient} from '@tanstack/react-query';

import { mapContentToCode, getContentToCodeMatches } from '../api/main.ts';
import type { codeMatchesResult, githubRepoTreeResponse, processPDFResult, paperContentToCodeMatch, paperContentBox, PaperContentMatch } from '../api/types.ts';
import { resolvePaperMageEntity } from '../utils/resolvePaperMageEntity.ts';
import { HighlightOverlayDemo, type BoundingBoxWithTooltip } from './CodeOverlay.tsx';
import RepoView from './RepoView.tsx';
import { captureSelectionHighlightsFromRange } from '../utils/selectionRangeToPageBox.ts';
import { usePDFTextSelection } from '../hooks/useTextSelection.tsx';
import { useCeleryTaskStatus } from '../hooks/useCeleryTaskStatus.ts';
import { UserContext } from '../context/UserContext.tsx';
import ThemeToggle from './ThemeToggle';

interface PaperViewProps {
    analysisResult: codeMatchesResult;
    processResult: processPDFResult;
    clearEnvironment: () => void;
    paperFile: File | undefined;
    tree: githubRepoTreeResponse | undefined;
    githubRepoUrl: string;
    paperId: string;
}

type ContentToCodeInput = {
    content: string | Blob;
    repoUrl: string;
    context: string;
    paperId: string;
    box: paperContentBox;
    pageNumber: number;
    user_id: number;
}

const CODE_MATCH_VERDICT_TO_COLOR: Record<string, string> = {
    "implemented": "rgba(37, 99, 235, 1)",
    "not_implemented": "rgba(220, 38, 38, 1)",
    "ai": "rgba(255, 215, 0, 1)",
}

/** User code→paper mapping underlines in the PDF. */
const CODE_TO_CONTENT_HIGHLIGHT_COLOR = "rgba(192, 132, 252, 1)";

type MatchFilter = 'all' | 'hide' | 'ai' | 'my' | 'others' | 'not_implemented';

const MATCH_FILTER_STORAGE_KEY = 'deepread.matchFilter';
const SHOW_MATCHES_FROM_CODE_STORAGE_KEY = 'deepread.showMatchesFromCode';
const DEFAULT_MATCH_FILTER: MatchFilter = 'all';

const MATCH_FILTER_OPTIONS: { value: MatchFilter; label: string }[] = [
    { value: 'all', label: 'Show all matches' },
    { value: 'hide', label: 'Hide all matches' },
    { value: 'ai', label: 'Show AI matches' },
    { value: 'my', label: 'Show matches by me' },
    { value: 'others', label: 'Show matches by others' },
    { value: 'not_implemented', label: 'Show failed matches'}
];

const readStoredMatchFilter = (): MatchFilter => {
    if (typeof window === 'undefined') return DEFAULT_MATCH_FILTER;
    const stored = window.localStorage.getItem(MATCH_FILTER_STORAGE_KEY);
    if (
        stored === 'all' ||
        stored === 'hide' ||
        stored === 'ai' ||
        stored === 'my' ||
        stored === 'others' ||
        stored === 'not_implemented'
    ) {
        return stored;
    }
    return DEFAULT_MATCH_FILTER;
};

const readStoredShowMatchesFromCode = (): boolean => {
    if (typeof window === 'undefined') return true;
    const stored = window.localStorage.getItem(SHOW_MATCHES_FROM_CODE_STORAGE_KEY);
    if (stored === 'false') return false;
    return true;
};

/**
 * Must render *inside* ContextProvider + DocumentWrapper so DocumentContext
 * is the real provider (not the default). Otherwise numPages stays 0 and
 * nothing renders.
 */
function PdfPageList({
    analysisResult,
    processResult,
    paperContentMatches,
    scrollRef,
    codeMatches,
}: {
    analysisResult: codeMatchesResult;
    processResult: processPDFResult;
    paperContentMatches: PaperContentMatch[];
    scrollRef: React.RefObject<HTMLDivElement | null>;
    codeMatches: paperContentToCodeMatch[];
}) {
    const { numPages, pdfDocProxy, pageDimensions } = React.useContext(DocumentContext);
    const { rotation, setScale } = React.useContext(TransformContext);
    const [hitBoxes, setHitBoxes] = useState<BoundingBoxWithTooltip[]>([]);

    // Auto-fit the rendered page to the panel width, recomputing whenever the
    // panel is resized (e.g. dragging the layout separator) or the window changes.
    useEffect(() => {
        const container = scrollRef.current;
        if (!container || pageDimensions.width < 1) return;

        const fitToWidth = () => {
            const pageWidth = getPageWidth(pageDimensions, rotation);
            const available = container.clientWidth - 24; // gutter for padding/scrollbar
            if (pageWidth < 1 || available < 1) return;
            setScale(available / pageWidth);
        };

        fitToWidth();
        const observer = new ResizeObserver(fitToWidth);
        observer.observe(container);
        return () => observer.disconnect();
    }, [scrollRef, pageDimensions, rotation, setScale]);

    useEffect(() => {
        if (!pdfDocProxy || numPages < 1 || pageDimensions.height < 1) {
            return;
        }
        let cancelled = false;
        let boxes: BoundingBoxWithTooltip[] = [];

        const contentToBBoxPaperMage = async () => {
            const aiMatches = analysisResult.matches ?? [];
            // AI-discovered matches
            for (let i = 0; i < aiMatches.length; i++) {
                const analyzedMatch = aiMatches[i];

                if (analyzedMatch.code_snippets.length === 0) {
                    console.warn("No code snippets listed for match", analyzedMatch);
                    continue;
                }

                const resolved = resolvePaperMageEntity(processResult, analyzedMatch);
                if (!resolved) {
                    console.warn('No PaperMage entity for analyzed match', analyzedMatch);
                    continue;
                }

                const box = resolved.box;
                if (cancelled) return;
                const page = await pdfDocProxy.getPage(box.page + 1);
                if (cancelled) return;
                const viewport = page.getViewport({ scale: 1, rotation });

                const scaleX = pageDimensions.width / viewport.width;
                const scaleY = pageDimensions.height / viewport.height;
    
                boxes.push({
                    page:   box.page,
                    top:    box.t   * viewport.height * scaleY,
                    left:   box.l   * viewport.width * scaleX,
                    width:  box.w   * viewport.width * scaleX,
                    height: box.h   * viewport.height * scaleY,
                    hitKey: `p${box.page}-h${i}`,
                    file_infos: analyzedMatch.code_snippets.map((snippet) => `${snippet.filepath}:${snippet.start_line}-${snippet.end_line}`),
                    code_snippets: analyzedMatch.code_snippets,
                    description: analyzedMatch.description || analyzedMatch.content,
                    content_type: analyzedMatch.content_type,
                    color: CODE_MATCH_VERDICT_TO_COLOR.ai,
                })
            }

            // Match from user-selected code
            for (let j = 0; j < paperContentMatches.length; j++) {
                const match = paperContentMatches[j];
                console.log("from paperview", match);
                const resolved = resolvePaperMageEntity(processResult, match);
                if (!resolved) {
                    console.warn('No PaperMage entity for match', match);
                    continue;
                }

                const box = resolved.box;
                if (cancelled) return;
                const page = await pdfDocProxy.getPage(box.page + 1);
                if (cancelled) return;
                const viewport = page.getViewport({ scale: 1, rotation });

                const scaleX = pageDimensions.width / viewport.width;
                const scaleY = pageDimensions.height / viewport.height;

                boxes.push({
                    page: box.page,
                    top: box.t * viewport.height * scaleY,
                    left: box.l * viewport.width * scaleX,
                    width: box.w * viewport.width * scaleX,
                    height: box.h * viewport.height * scaleY,
                    hitKey: `map-${match.entity_id}-${j}`,
                    file_infos: [],
                    code_snippets: [],
                    description: match.description,
                    variant: 'underline',
                    color: CODE_TO_CONTENT_HIGHLIGHT_COLOR,
                });
            }

            // Match from user-selected paper content
            for (let k = 0; k < codeMatches.length; k++) {
                const codeMatch = codeMatches[k];
                const box = codeMatch.inputs.box;
                const pageIndex = codeMatch.inputs.page_number;
                if (pageIndex == null || Number.isNaN(pageIndex)) {
                    console.warn('Code match missing page_number; skipping overlay', codeMatch);
                    continue;
                }
                if (cancelled) return;
                const page = await pdfDocProxy.getPage(pageIndex + 1);
                if (cancelled) return;
                const viewport = page.getViewport({ scale: 1, rotation });
                const scaleX = pageDimensions.width / viewport.width;
                const scaleY = pageDimensions.height / viewport.height;

                const codeSnippet = codeMatch.outputs.code_snippet;

                boxes.push({
                    page: pageIndex,
                    top: box.t * viewport.height * scaleY - 5,
                    left: box.l * viewport.width * scaleX,
                    width: box.w * viewport.width * scaleX,
                    height: box.h * viewport.height * scaleY * 1.5,
                    hitKey: `map-${codeMatch.cache_key ?? k}-${k}`,
                    file_infos: codeSnippet
                        ? [`${codeSnippet.filepath}:${codeSnippet.start_line}-${codeSnippet.end_line}`]
                        : [],
                    code_snippets: codeSnippet ? [codeSnippet] : [],
                    description: codeMatch.outputs.reasoning,
                    variant: 'overlay',
                    color: CODE_MATCH_VERDICT_TO_COLOR[codeMatch.outputs.verdict] ?? CODE_MATCH_VERDICT_TO_COLOR.not_implemented,
                });
            }

            if (cancelled) return;
            setHitBoxes(boxes);

            if (paperContentMatches.length > 0) {
                const firstResolved = resolvePaperMageEntity(processResult, paperContentMatches[0]);
                const pageIndex = firstResolved?.box.page;
                requestAnimationFrame(() => {
                    if (pageIndex != null) {
                        scrollRef.current?.children[pageIndex]?.scrollIntoView({
                            behavior: 'smooth',
                            block: 'center',
                        });
                    }
                });
            }
        }

        contentToBBoxPaperMage().catch((err) => {
            if (!cancelled) {
                console.error('Failed to compute paper bounding boxes', err);
            }
        });

        return () => {
            cancelled = true;
        };
    }, [pdfDocProxy, numPages, rotation, pageDimensions, analysisResult, processResult, paperContentMatches, scrollRef, codeMatches]);

    return (
        <div className="reader__page-list" ref={scrollRef}>
            {/* renderType must match DocumentWrapper's: with SINGLE_CANVAS the page
                image is a CSS background, and the MULTI_CANVAS styles would make the
                text layer transparent whenever that image is missing. */}
            {Array.from({ length: numPages > 0 ? numPages : 0 }).map((_, i) => (
                <PageWrapper key={i} pageIndex={i} renderType={RENDER_TYPE.SINGLE_CANVAS}>
                    <Overlay>
                        <HighlightOverlayDemo pageIndex={i} boxes={hitBoxes} />
                    </Overlay>
                    </PageWrapper>
            ))}
        </div>
    );
}

export default function PaperView({ analysisResult, processResult, clearEnvironment, paperFile, tree, githubRepoUrl, paperId }: PaperViewProps) {
    const pdfContentRef = useRef<HTMLDivElement>(null);
    const pdfScrollableRef = useRef<HTMLDivElement>(null);

    const {currentUser} = useContext(UserContext);

    const [matchingTaskId, setMatchingTaskId] = useState<string | null>(null);
    const [paperContentMatches, setPaperContentMatches] = useState<PaperContentMatch[]>([]);
    const [contentToCodeMatches, setContentToCodeMatches] = useState<paperContentToCodeMatch[]>([]);
    const [isMatchFilterOpen, setIsMatchFilterOpen] = useState(false);
    const [matchFilter, setMatchFilter] = useState<MatchFilter>(readStoredMatchFilter);
    const [showMatchesFromCode, setShowMatchesFromCode] = useState(readStoredShowMatchesFromCode);
    const matchFilterRef = useRef<HTMLDivElement>(null);

    const queryClient = useQueryClient();

    const matchesQuery = useQuery({
        queryKey: ['matches', paperId],
        queryFn: () => getContentToCodeMatches(paperId),
        enabled: Boolean(paperId),
    })

    const [pendingSelection, setPendingSelection] = useState<{
        text: string;
        rect: DOMRect;
        range: Range;
    } | null>(null);

    useEffect(() => {
        if (matchesQuery.data) {
            setContentToCodeMatches(matchesQuery.data);
        }
    }, [matchesQuery.data])

    useEffect(() => {
        window.localStorage.setItem(MATCH_FILTER_STORAGE_KEY, matchFilter);
    }, [matchFilter])

    useEffect(() => {
        window.localStorage.setItem(SHOW_MATCHES_FROM_CODE_STORAGE_KEY, String(showMatchesFromCode));
    }, [showMatchesFromCode])

    useEffect(() => {
        if (!isMatchFilterOpen) return;
        const handleClickOutside = (event: MouseEvent) => {
            if (matchFilterRef.current && !matchFilterRef.current.contains(event.target as Node)) {
                setIsMatchFilterOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [isMatchFilterOpen])

    

    // This submits a user's selection to the server for Celery task
    const contentToCodeMutation = useMutation({
        mutationFn: ({content, repoUrl, context, paperId, box, pageNumber, user_id}: ContentToCodeInput) => 
            mapContentToCode(content, repoUrl, context, paperId, box, pageNumber, user_id),
        onSuccess: (response) => {
            if (response.status === "SUCCESS") {
                queryClient.invalidateQueries({queryKey: ["matches", paperId]})
            } else if (response.status === "PENDING" && response.task_id) {
                setMatchingTaskId(response.task_id);
            }
        },
        onError: (error) => {
            console.error(error);
            setPendingSelection(null);
            setMatchingTaskId(null);
        }
    })

    const matchTaskQuery = useCeleryTaskStatus(matchingTaskId, { queryKey: 'matchTask' });

    useEffect(() => {
        if (matchTaskQuery.data?.status === "SUCCESS") {
            queryClient.invalidateQueries({queryKey: ['matches', paperId]});
            setMatchingTaskId(null);
        }
    }, [matchTaskQuery.data, paperId, queryClient])

    const isMapping =
        contentToCodeMutation.isPending ||
        matchingTaskId !== null;

    const submitPendingSelection = () => {
            // Block any additional match requests if one is already ongoing
            if (!pendingSelection || matchingTaskId !== null) return; 

            const selectionHighlight = captureSelectionHighlightsFromRange(pendingSelection.range)[0];
            if (!selectionHighlight) {
                console.warn('No selection highlight captured');
                return;
            }

            let selectionContext = processResult.sections.filter((section) => section.entity_id === "abstract")[0]?.section_content ?? "";
            if (!selectionContext) {
                console.warn('No context found');
                selectionContext = "";
            }

            const matchTaskInput: ContentToCodeInput = {
                content: pendingSelection.text,
                context: selectionContext,
                repoUrl: githubRepoUrl,
                paperId: paperId,
                box: selectionHighlight.box,
                pageNumber: selectionHighlight.page,
                user_id: currentUser?.id ?? 1,
            }
            
            contentToCodeMutation.mutate(matchTaskInput);
    };

    usePDFTextSelection(pdfContentRef, setPendingSelection);
    
    const fileForViewer = useMemo(() => paperFile, [paperFile]);

    const hasRealFile = paperFile instanceof File && paperFile.size > 0;

    // Match visibility filter: 'my'/'others' split persisted user matches by creator.
    const showAiMatches = matchFilter === 'all' || matchFilter === 'ai';
    const showMyMatches = matchFilter === 'all' || matchFilter === 'my';
    const showFailedMatches = matchFilter === 'all' || matchFilter === 'not_implemented';

    const filteredAnalysisResult = useMemo(
        () => (showAiMatches ? analysisResult : { ...analysisResult, matches: [] }),
        [showAiMatches, analysisResult],
    );
    const filteredPaperContentMatches = useMemo(
        () => (showMatchesFromCode ? paperContentMatches : []),
        [showMatchesFromCode, paperContentMatches],
    );
    const filteredContentToCodeMatches = useMemo(
        () => contentToCodeMatches.filter((match) => {
            const isMyMatch = currentUser != null && match.created_by === currentUser.id;
            if (matchFilter === 'my') return isMyMatch;
            if (matchFilter === 'others') return !isMyMatch;

            const failed = match.outputs.verdict === 'not_implemented';
            if (matchFilter === 'hide' || matchFilter === 'ai') return false;
            if (failed) return showFailedMatches;
            return showMyMatches;
        }),
        [contentToCodeMatches, currentUser, matchFilter, showMyMatches, showFailedMatches],
    );

    return ( 
        <div className="paper-view-layout">
            <Group orientation="horizontal" className="paper-view-layout__group">
            <Panel defaultSize={53} minSize={15}>
            <section id="paper-viewer" className="paper-view-layout__pdf-panel">
                    <div className="paper-view-layout__pdf-toolbar">
                        <h1 className="paper-view-layout__toolbar-title">Paper View</h1>
                        <button
                            type="button"
                            className="outline-action-btn"
                            onClick={clearEnvironment}
                        >
                            Clear Environment
                        </button>
                        {paperContentMatches.length > 0 && <button
                            type="button"
                            className="outline-action-btn temp-action-btn"
                            onClick={() => {
                                setPaperContentMatches([]);
                            }}
                        >
                            Clear Paper Highlights
                        </button>}
                        <div className="match-filter" ref={matchFilterRef}>
                            <button
                                type="button"
                                className="outline-action-btn match-filter__toggle"
                                aria-haspopup="true"
                                aria-expanded={isMatchFilterOpen}
                                onClick={() => setIsMatchFilterOpen((open) => !open)}
                            >
                                Filter matches
                                <IoChevronDown aria-hidden />
                            </button>
                            {isMatchFilterOpen && (
                                <div className="match-filter__menu" role="menu">
                                    {MATCH_FILTER_OPTIONS.map((option) => (
                                        <button
                                            key={option.value}
                                            type="button"
                                            className={`match-filter__item${matchFilter === option.value ? ' match-filter__item--active' : ''}`}
                                            role="menuitemradio"
                                            aria-checked={matchFilter === option.value}
                                            onClick={() => {
                                                setMatchFilter(option.value);
                                                setIsMatchFilterOpen(false);
                                            }}
                                        >
                                            {option.label}
                                        </button>
                                    ))}
                                    <div className="match-filter__separator" role="separator" />
                                    <label className="match-filter__checkbox">
                                        <input
                                            type="checkbox"
                                            checked={showMatchesFromCode}
                                            onChange={(event) => setShowMatchesFromCode(event.target.checked)}
                                        />
                                        Show matches from code
                                    </label>
                                </div>
                            )}
                        </div>
                        <ThemeToggle className="theme-toggle theme-toggle--toolbar-end" />
                    </div>

                {!hasRealFile ? (
                    <p role="status" style={{ padding: '0 1rem' }}>
                        No PDF file in memory. That often happens after a refresh (the browser cannot
                        restore file uploads from storage). Go back, upload your PDF again, then analyze.
                    </p>
                ) : (
                    (<div className="paper-view-layout__pdf-scroll">
                        <div className="paper-view-layout__pdf-inner paper-viewer">
                            <ContextProvider>
                                <DocumentWrapper
                                    className="pdf-document paper-view-layout__doc-shell"
                                    file={fileForViewer}
                                    renderType={RENDER_TYPE.SINGLE_CANVAS}
                                    inputRef={pdfContentRef}
                                >
                                    <PdfPageList
                                        analysisResult={filteredAnalysisResult}
                                        processResult={processResult}
                                        paperContentMatches={filteredPaperContentMatches}
                                        scrollRef={pdfScrollableRef}
                                        codeMatches={filteredContentToCodeMatches}
                                    />
                                </DocumentWrapper>
                            </ContextProvider>
                        </div>
                    </div>)
                )}
            </section>
            </Panel>
            <Separator className="paper-view-layout__separator" />
            <Panel defaultSize={47} minSize={15}>
            {tree && (
                <aside className="paper-view-layout__code-panel">
                    <div className="paper-view-layout__code-toolbar">
                        {/* <button type="button" className="outline-action-btn" onClick={hideCode}>
                            Close
                        </button> */}
                    </div>
                    <div className="paper-view-layout__code-scroll">
                        {<RepoView tree={tree} paperId={paperId} setPaperContentMatches={setPaperContentMatches} />}
                    </div>
                </aside>
            )}
            </Panel>
            </Group>

            {pendingSelection && (
            <div className="pdf-selection-popover" style={{
                position: 'fixed',
                left: pendingSelection.rect.right + 8,
                top: pendingSelection.rect.bottom + 8,
                zIndex: 10000,
              }}>
            <div className="pdf-selection-popover__actions">
              <button
                type="button"
                className="pdf-selection-popover__btn pdf-selection-popover__btn--primary"
                onClick={submitPendingSelection}
                disabled={isMapping}
              >
                {isMapping ? "Mapping..." : "Map to code"}
              </button>
              <button
                type="button"
                className="pdf-selection-popover__btn pdf-selection-popover__btn--ghost"
                onClick={() => setPendingSelection(null)}
              >
                Cancel
              </button>
            </div>
          </div>
            )}
        </div>
    );
}