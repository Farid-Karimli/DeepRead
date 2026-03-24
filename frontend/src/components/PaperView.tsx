import { type codeSectionsResult } from '../api/main.ts';
import {
    ContextProvider,
    DocumentContext,
    DocumentWrapper,
    PageWrapper,
    RENDER_TYPE,
} from '@allenai/pdf-components';
import React, { useMemo, useRef } from 'react';

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
function PdfPageList({ scrollRef }: { scrollRef: React.RefObject<HTMLDivElement | null> }) {
    const { numPages } = React.useContext(DocumentContext);

    return (
        <div className="reader__page-list" ref={scrollRef}>
            {Array.from({ length: numPages > 0 ? numPages : 0 }).map((_, i) => (
                <PageWrapper key={i} pageIndex={i} renderType={RENDER_TYPE.SINGLE_CANVAS} />
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

    return (
        <>
            <section id="center">
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
                                <PdfPageList scrollRef={pdfScrollableRef} />
                            </DocumentWrapper>
                        </ContextProvider>
                    </div>
                )}
            </section>
        </>
    );
}