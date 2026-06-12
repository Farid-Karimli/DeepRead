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
import { Group, Panel, Separator } from "react-resizable-panels";
import { useQuery, useMutation, useQueryClient} from '@tanstack/react-query';

import { mapContentToCode, getTaskStatus, getContentToCodeMatches } from '../api/main.ts';
import type { codeSectionsResult, githubRepoTreeResponse, processPDFResult, paperContentToCodeMatch, paperContentBox } from '../api/types.ts';
import { HighlightOverlayDemo, type BoundingBoxWithTooltip } from './CodeOverlay.tsx';
import { useSidePanel } from '../context/SidePanelContext.tsx';
import RepoView from './RepoView.tsx';
import { captureSelectionHighlightsFromRange } from '../utils/selectionRangeToPageBox.ts';
import { usePDFTextSelection } from '../hooks/useTextSelection.tsx';

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

const CODE_MATCH_VERDICT_TO_COLOR: Record<string, string> = {
    "implemented": "rgba(37, 99, 235, 1)",
    "not_implemented": "rgba(220, 38, 38, 1)",
    "ai": "rgba(255, 215, 0, 1)",
}
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
                });
            }

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

    type ContentToCodeInput = {
        content: string | Blob;
        repoUrl: string;
        context: string;
        paperId: string;
        box: paperContentBox;
        pageNumber: number;
    }

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

    const matchTaskQuery = useQuery({
        queryKey: ['matchTask', matchingTaskId], 
        queryFn: () => {
            if (!matchingTaskId) throw new Error("No matching task ID set.")
            return getTaskStatus(matchingTaskId);
        },
        refetchInterval: (query) => {
            const status = query.state.data?.status;
            return status === 'SUCCESS' || status === 'FAILURE' ? false : 10000;
          },
        enabled: Boolean(matchingTaskId),
    })

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

    const { showCode } = useSidePanel();

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
                                        analysisResult={analysisResult}
                                        processResult={processResult}
                                        paperHighlightSections={paperHighlightSections}
                                        scrollRef={pdfScrollableRef}
                                        codeMatches={contentToCodeMatches}
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