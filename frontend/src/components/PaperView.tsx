import { type codeSectionsResult } from '../api/main.ts';
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
import { textItemToBoundingBoxLike, type PdfTextItemLike } from '../utils/pdfTextItemToBoundingBox.ts';
import { HighlightOverlayDemo, type BoundingBoxWithTooltip } from './CodeOverlay.tsx';
import CodeSidePanel from './CodeSidePanel.tsx';
import { useSidePanel } from '../context/SidePanelContext.tsx';

interface PaperViewProps {
    analysisResult: codeSectionsResult;
    clearEnvironment: () => void;
    paperFile: File | undefined;
}

/**
 * Must render *inside* ContextProvider + DocumentWrapper so DocumentContext
 * is the real provider (not the default). Otherwise numPages stays 0 and
 * nothing renders.
 */
function PdfPageList({ analysisResult, scrollRef }: { analysisResult: codeSectionsResult, scrollRef: React.RefObject<HTMLDivElement | null> }) {
    const { numPages, pdfDocProxy, pageDimensions } = React.useContext(DocumentContext);
    const { rotation } = React.useContext(TransformContext);
    const [hitBoxes, setHitBoxes] = useState<BoundingBoxWithTooltip[]>([]);

    useEffect(() => {
        if (!pdfDocProxy || numPages < 1 || pageDimensions.height < 1) {
            return;
        }
        console.log("analysisResult: ", analysisResult);

        let cancelled = false;

        const run = async () => {
            const next: BoundingBoxWithTooltip[] = [];
            let hitSeq = 0;

            // Normalize a string for matching: strip whitespace and lowercase
            const normalize = (s: string) => s.replace(/\s+/g, '').toLowerCase();

            // Build (normalizedName, sectionName) pairs once
            const targets = analysisResult.sections.map((section) => ({
                section,
                needle: normalize(section.section_name),
            })).filter(t => t.needle.length > 0);

            // Track which sections have been matched (by index) so we skip them on later pages
            const matched = new Set<number>();

            for (let pageNum = 1; pageNum <= numPages; pageNum++) {
                if (cancelled) return;
                if (matched.size === targets.length) break;

                const page = await pdfDocProxy.getPage(pageNum);
                const pageText = await page.getTextContent();
                const viewport = page.getViewport({ scale: 1, rotation });

                const scaleX = pageDimensions.width / viewport.width;
                const scaleY = pageDimensions.height / viewport.height;
                const pageIndexZeroBased = pageNum - 1;

                // Collect only text items (not TextMarkedContent)
                const items = pageText.items.filter((it: object): it is PdfTextItemLike => 'str' in it);

                // Build flat string and char→item index map
                let flatStr = '';
                const charToItem: number[] = [];
                for (let idx = 0; idx < items.length; idx++) {
                    const str = items[idx].str;
                    for (let c = 0; c < str.length; c++) {
                        charToItem.push(idx);
                    }
                    flatStr += str;
                }

                // Build normalized flat string and normChar→origChar map (strip whitespace, lowercase)
                const normToOrig: number[] = [];
                let normalizedFlat = '';
                for (let c = 0; c < flatStr.length; c++) {
                    if (!/\s/.test(flatStr[c])) {
                        normToOrig.push(c);
                        normalizedFlat += flatStr[c].toLowerCase();
                    }
                }

                for (let ti = 0; ti < targets.length; ti++) {
                    if (matched.has(ti)) continue;
                    const { section, needle } = targets[ti];

                    const pos = normalizedFlat.indexOf(needle);
                    if (pos === -1) continue;

                    matched.add(ti);

                    const startOrigChar = normToOrig[pos];
                    const endOrigChar   = normToOrig[pos + needle.length - 1];
                    const startItemIdx  = charToItem[startOrigChar];
                    const endItemIdx    = charToItem[endOrigChar];

                    // Union bounding boxes across the matched item span
                    let unionLeft   = Infinity;
                    let unionTop    = Infinity;
                    let unionRight  = -Infinity;
                    let unionBottom = -Infinity;

                    for (let idx = startItemIdx; idx <= endItemIdx; idx++) {
                        const box = textItemToBoundingBoxLike(items[idx], pageIndexZeroBased, viewport.height);
                        if (!box) continue;
                        unionLeft   = Math.min(unionLeft,   box.left);
                        unionTop    = Math.min(unionTop,    box.top);
                        unionRight  = Math.max(unionRight,  box.left + box.width);
                        unionBottom = Math.max(unionBottom, box.top  + box.height);
                    }

                    if (!isFinite(unionLeft)) continue;

                    next.push({
                        page: pageIndexZeroBased,
                        top:    unionTop    * scaleY - 5,
                        left:   unionLeft   * scaleX,
                        width:  (unionRight  - unionLeft)   * scaleX,
                        height: (unionBottom - unionTop)    * scaleY * 1.5,
                        hitKey: `p${pageIndexZeroBased}-h${hitSeq++}`,
                        file_info: `${section.code_filepath}:${section.code_start_line}-${section.code_end_line}`,
                        code: section.code_snippet,
                    });
                }
            }
            if (!cancelled) {
                setHitBoxes(next);
            }
        };

        void run();
        return () => {
            cancelled = true;
        };
    }, [pdfDocProxy, numPages, rotation, pageDimensions]);

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

export default function PaperView({ analysisResult: _analysisResult, clearEnvironment, paperFile }: PaperViewProps) {
    const pdfContentRef = useRef<HTMLDivElement>(null);
    const pdfScrollableRef = useRef<HTMLDivElement>(null);

    // react-pdf / DocumentWrapper use reference equality on `file`
    const fileForViewer = useMemo(() => paperFile, [paperFile]);

    const hasRealFile = paperFile instanceof File && paperFile.size > 0;

    const { codeContent, showCode, hideCode } = useSidePanel();

    return (
        <div style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-around' }}>
            <section id="paper-viewer" style={{ width: '60%' }}>
                <h1>Paper View</h1>
                <button type="button" onClick={clearEnvironment}>
                    Clear Environment
                </button>

                {!hasRealFile ? (
                    <p role="status">
                        No PDF file in memory. That often happens after a refresh (the browser cannot
                        restore file uploads from storage). Go back, upload your PDF again, then analyze.
                    </p>
                ) : (
                    <div className="paper-viewer" style={{ width: '100%', maxWidth: 900, minHeight: 480 }}>
                        <ContextProvider>
                            <DocumentWrapper
                                className="pdf-document"
                                file={fileForViewer}
                                renderType={RENDER_TYPE.SINGLE_CANVAS}
                                inputRef={pdfContentRef}
                            >
                                <PdfPageList analysisResult={_analysisResult} scrollRef={pdfScrollableRef} />
                            </DocumentWrapper>
                        </ContextProvider>
                    </div>
                )}
            </section>

            {codeContent && 
                ( 
                <aside style={{ width: '40%', borderLeft: '1px solid #333', overflow: 'auto', padding: 16 }}>
                    <button style={{ marginBottom: 16 }} onClick={hideCode}>Close</button>
                    <CodeSidePanel codeContent={codeContent} />
                  </aside>
                  )
            }

        </div>
    );
}