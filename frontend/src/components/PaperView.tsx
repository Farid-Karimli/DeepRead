import {
    ContextProvider,
    DocumentContext,
    DocumentWrapper,
    Overlay,
    PageWrapper,
    RENDER_TYPE,
    TransformContext,
} from '@allenai/pdf-components';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { IoChevronDown } from 'react-icons/io5';
import { Group, Panel, Separator } from "react-resizable-panels";
import { useQuery, useMutation, useQueryClient} from '@tanstack/react-query';

import { mapContentToCode, getContentToCodeMatches } from '../api/main.ts';
import type { codeSectionsResult, githubRepoTreeResponse, processPDFResult, paperContentToCodeMatch, paperContentBox } from '../api/types.ts';
import { HighlightOverlayDemo, type BoundingBoxWithTooltip } from './CodeOverlay.tsx';
import RepoView from './RepoView.tsx';
import { captureSelectionHighlightsFromRange } from '../utils/selectionRangeToPageBox.ts';
import { usePDFTextSelection } from '../hooks/useTextSelection.tsx';
import { useCeleryTaskStatus } from '../hooks/useCeleryTaskStatus.ts';

interface PaperViewProps {
    analysisResult: codeSectionsResult;
    processResult: processPDFResult;
    clearEnvironment: () => void;
    paperFile: File | undefined;
    tree: githubRepoTreeResponse | undefined;
    githubRepoUrl: string;
    paperId: string;
}

type PaperHighlight = {
    section_id: string;
    description: string;
};

type ContentToCodeInput = {
    content: string | Blob;
    repoUrl: string;
    context: string;
    paperId: string;
    box: paperContentBox;
    pageNumber: number;
}

const CODE_MATCH_VERDICT_TO_COLOR: Record<string, string> = {
    "implemented": "rgba(37, 99, 235, 1)",
    "not_implemented": "rgba(220, 38, 38, 1)",
    "ai": "rgba(255, 215, 0, 1)",
}

/** User code→paper mapping underlines in the PDF. */
const CODE_TO_CONTENT_HIGHLIGHT_COLOR = "rgba(192, 132, 252, 1)";

type MatchFilter = 'all' | 'hide' | 'ai' | 'mine' | 'not_implemented';

const MATCH_FILTER_STORAGE_KEY = 'deepread.matchFilter';
const DEFAULT_MATCH_FILTER: MatchFilter = 'all';

const MATCH_FILTER_OPTIONS: { value: MatchFilter; label: string }[] = [
    { value: 'all', label: 'Show all matches' },
    { value: 'hide', label: 'Hide all matches' },
    { value: 'ai', label: 'Show AI matches' },
    { value: 'mine', label: 'Show matches selected by me' },
    { value: 'not_implemented', label: 'Show failed matches'}
];

const readStoredMatchFilter = (): MatchFilter => {
    if (typeof window === 'undefined') return DEFAULT_MATCH_FILTER;
    const stored = window.localStorage.getItem(MATCH_FILTER_STORAGE_KEY);
    if (stored === 'all' || stored === 'hide' || stored === 'ai' || stored === 'mine' || stored === 'not_implemented') {
        return stored;
    }
    return DEFAULT_MATCH_FILTER;
};
/**
 * Must render *inside* ContextProvider + DocumentWrapper so DocumentContext
 * is the real provider (not the default). Otherwise numPages stays 0 and
 * nothing renders.
 */
function PdfPageList({
    analysisResult,
    processResult,
    paperHighlightSections,
    scrollRef,
    codeMatches,
}: {
    analysisResult: codeSectionsResult;
    processResult: processPDFResult;
    paperHighlightSections: PaperHighlight[];
    scrollRef: React.RefObject<HTMLDivElement | null>;
    codeMatches: paperContentToCodeMatch[];
}) {
    const { numPages, pdfDocProxy, pageDimensions } = React.useContext(DocumentContext);
    const { rotation } = React.useContext(TransformContext);
    const [hitBoxes, setHitBoxes] = useState<BoundingBoxWithTooltip[]>([]);

    useEffect(() => {
        if (!pdfDocProxy || numPages < 1 || pageDimensions.height < 1) {
            return;
        }
        let cancelled = false;
        let boxes: BoundingBoxWithTooltip[] = [];

        const contentToBBoxPaperMage = async () => {
            // AI-discovered matches
            for (let i = 0; i < analysisResult.sections.length; i++) {
                const analyzedSection = analysisResult.sections[i];

                if (analyzedSection.code_snippets.length === 0) {
                    console.warn("No code snippets listed for section", analyzedSection);
                    continue;
                }

                const paperMageSection = processResult.sections.filter((section)=>section.entity_id === analyzedSection.section_id)[0];

                if (!paperMageSection) {
                    console.warn('No PaperMage section for analyzed section', analyzedSection);
                    continue;
                }
    
                const box = paperMageSection.box;
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
                    file_infos: analyzedSection.code_snippets.map((snippet) => `${snippet.filepath}:${snippet.start_line}-${snippet.end_line}`),
                    code_snippets: analyzedSection.code_snippets,
                    description: analyzedSection.section_description,
                    color: CODE_MATCH_VERDICT_TO_COLOR.ai,
                })
            }

            // Match from user-selected code
            for (let j = 0; j < paperHighlightSections.length; j++) {
                const highlight = paperHighlightSections[j];
                const paperMageSection = processResult.sections.find(
                    (section) => section.entity_id === highlight.section_id,
                );
                if (!paperMageSection) {
                    console.warn('No PaperMage section for mapped highlight', highlight);
                    continue;
                }

                const box = paperMageSection.box;
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
                    hitKey: `map-${highlight.section_id}-${j}`,
                    file_infos: [],
                    code_snippets: [],
                    description: highlight.description,
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

            if (paperHighlightSections.length > 0) {
                const firstSection = processResult.sections.find(
                    (s) => s.entity_id === paperHighlightSections[0].section_id,
                );
                const pageIndex = firstSection?.box.page;
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
    }, [pdfDocProxy, numPages, rotation, pageDimensions, analysisResult, processResult, paperHighlightSections, scrollRef, codeMatches]);

    return (
        <div className="reader__page-list" ref={scrollRef}>
            {Array.from({ length: numPages > 0 ? numPages : 0 }).map((_, i) => (
                <PageWrapper key={i} pageIndex={i} renderType={RENDER_TYPE.MULTI_CANVAS}>
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

    const [matchingTaskId, setMatchingTaskId] = useState<string | null>(null);
    const [paperHighlightSections, setPaperHighlightSections] = useState<PaperHighlight[]>([]);
    const [contentToCodeMatches, setContentToCodeMatches] = useState<paperContentToCodeMatch[]>([]);
    const [isMatchFilterOpen, setIsMatchFilterOpen] = useState(false);
    const [matchFilter, setMatchFilter] = useState<MatchFilter>(readStoredMatchFilter);
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
        mutationFn: ({content, repoUrl, context, paperId, box, pageNumber}: ContentToCodeInput) => 
            mapContentToCode(content, repoUrl, context, paperId, box, pageNumber),
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
            }
            
            contentToCodeMutation.mutate(matchTaskInput);
    };

    usePDFTextSelection(pdfContentRef, setPendingSelection);
    
    const fileForViewer = useMemo(() => paperFile, [paperFile]);

    const hasRealFile = paperFile instanceof File && paperFile.size > 0;

    // Match visibility filter: 'all' shows everything, 'hide' nothing,
    // 'ai' only analysisResult matches, 'mine' only successful user matches,
    // 'not_implemented' only paper→code matches where no implementation was found.
    const showAiMatches = matchFilter === 'all' || matchFilter === 'ai';
    const showMyMatches = matchFilter === 'all' || matchFilter === 'mine';
    const showFailedMatches = matchFilter === 'all' || matchFilter === 'not_implemented';

    const filteredAnalysisResult = useMemo(
        () => (showAiMatches ? analysisResult : { ...analysisResult, sections: [] }),
        [showAiMatches, analysisResult],
    );
    const filteredPaperHighlightSections = useMemo(
        () => (showMyMatches ? paperHighlightSections : []),
        [showMyMatches, paperHighlightSections],
    );
    const filteredContentToCodeMatches = useMemo(
        () => contentToCodeMatches.filter((match) => {
            const failed = match.outputs.verdict === 'not_implemented';
            if (matchFilter === 'hide' || matchFilter === 'ai') return false;
            if (failed) return showFailedMatches;
            return showMyMatches;
        }),
        [contentToCodeMatches, matchFilter, showMyMatches, showFailedMatches],
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
                        {paperHighlightSections.length > 0 && <button
                            type="button"
                            className="outline-action-btn temp-action-btn"
                            onClick={() => {
                                setPaperHighlightSections([]);
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
                                </div>
                            )}
                        </div>
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
                                        paperHighlightSections={filteredPaperHighlightSections}
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
                        {<RepoView tree={tree} paperId={paperId} setPaperHighlightSections={setPaperHighlightSections} />}
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