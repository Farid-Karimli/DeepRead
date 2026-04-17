import { useEffect, useRef } from 'react';
import ShikiHighlighter from 'react-shiki';

interface CodeViewerProps {
   code: string;
   highlightStart?: number;
   highlightEnd?: number;
}

const CodeViewer = ({ code, highlightStart, highlightEnd }: CodeViewerProps) => {
    const containerRef = useRef<HTMLDivElement>(null);

    const decorations = highlightStart != null && highlightEnd != null
        ? [{
            start: { line: highlightStart - 1, character: 0 },
            end: { line: highlightEnd, character: 0 },
            properties: { class: 'code-viewer__highlighted-line' },
        }]
        : [];

    useEffect(() => {
        if (highlightStart == null || !containerRef.current) return;

        const container = containerRef.current;
        const tryScroll = () => {
            const el = container.querySelector('.code-viewer__highlighted-line');
            if (el) {
                el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                return true;
            }
            return false;
        };

        if (tryScroll()) return;

        const observer = new MutationObserver(() => {
            if (tryScroll()) observer.disconnect();
        });
        observer.observe(container, { childList: true, subtree: true });

        return () => observer.disconnect();
    }, [code, highlightStart]);

    return (
        <div ref={containerRef} className="code-viewer">
            <ShikiHighlighter
                theme="github-dark"
                language="python"
                showLineNumbers
                decorations={decorations}
            >
                {code}
            </ShikiHighlighter>
        </div>
    );
};

export default CodeViewer;