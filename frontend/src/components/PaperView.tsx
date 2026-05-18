import { type codeSectionsResult, type githubRepoTreeResponse } from '../api/main.ts';
import type { processPDFResult } from '../api/types.ts';
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
import { HighlightOverlayDemo, type BoundingBoxWithTooltip } from './CodeOverlay.tsx';
import { useSidePanel } from '../context/SidePanelContext.tsx';
import RepoView from './RepoView.tsx';

interface PaperViewProps {
    analysisResult: codeSectionsResult;
    processResult: processPDFResult;
    clearEnvironment: () => void;
    paperFile: File | undefined;
    tree: githubRepoTreeResponse | undefined;
}

/**
 * Must render *inside* ContextProvider + DocumentWrapper so DocumentContext
 * is the real provider (not the default). Otherwise numPages stays 0 and
 * nothing renders.
 */
function PdfPageList({ analysisResult, processResult,  scrollRef }: { analysisResult: codeSectionsResult, processResult: processPDFResult, scrollRef: React.RefObject<HTMLDivElement | null> }) {
    const { numPages, pdfDocProxy, pageDimensions } = React.useContext(DocumentContext);
    const { rotation } = React.useContext(TransformContext);
    const [hitBoxes, setHitBoxes] = useState<BoundingBoxWithTooltip[]>([]);

    useEffect(() => {
        if (!pdfDocProxy || numPages < 1 || pageDimensions.height < 1) {
            return;
        }
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
                console.log('paperMageSection for', analyzedSection, " = ", paperMageSection.box);
    
                const box = paperMageSection.box;
                const page = await pdfDocProxy.getPage(box.page + 1);
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
                })
            }
        
            setHitBoxes(boxes)
        }

        contentToBBoxPaperMage();
    }, [pdfDocProxy, numPages, rotation, pageDimensions, analysisResult, processResult]);

    return (
        <div className="reader__page-list" ref={scrollRef}>
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

export default function PaperView({ analysisResult: _analysisResult, processResult, clearEnvironment, paperFile, tree }: PaperViewProps) {
    const pdfContentRef = useRef<HTMLDivElement>(null);
    const pdfScrollableRef = useRef<HTMLDivElement>(null);

    // react-pdf / DocumentWrapper use reference equality on `file`
    const fileForViewer = useMemo(() => paperFile, [paperFile]);

    const hasRealFile = paperFile instanceof File && paperFile.size > 0;

    const { hideCode } = useSidePanel();

    return (
        <div className="paper-view-layout">
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
                </div>

                {!hasRealFile ? (
                    <p role="status" style={{ padding: '0 1rem' }}>
                        No PDF file in memory. That often happens after a refresh (the browser cannot
                        restore file uploads from storage). Go back, upload your PDF again, then analyze.
                    </p>
                ) : (
                    <div className="paper-view-layout__pdf-scroll">
                        <div className="paper-view-layout__pdf-inner paper-viewer">
                            <ContextProvider>
                                <DocumentWrapper
                                    className="pdf-document paper-view-layout__doc-shell"
                                    file={fileForViewer}
                                    renderType={RENDER_TYPE.SINGLE_CANVAS}
                                    inputRef={pdfContentRef}
                                >
                                    <PdfPageList analysisResult={_analysisResult} processResult={processResult} scrollRef={pdfScrollableRef} />
                                </DocumentWrapper>
                            </ContextProvider>
                        </div>
                    </div>
                )}
            </section>

            {tree && (
                <aside className="paper-view-layout__code-panel">
                    <div className="paper-view-layout__code-toolbar">
                        {/* <button type="button" className="outline-action-btn" onClick={hideCode}>
                            Close
                        </button> */}
                    </div>
                    <div className="paper-view-layout__code-scroll">
                        {<RepoView tree={tree} />}
                    </div>
                </aside>
            )}
        </div>
    );
}