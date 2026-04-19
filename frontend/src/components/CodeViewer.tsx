import { useEffect, useRef } from 'react';
import ShikiHighlighter from 'react-shiki';

interface CodeViewerProps {
   code: string;
   highlightStarts?: number[]; // Could be multiple snippets in the file
   highlightEnds?: number[];
}

const CodeViewer = ({ code, highlightStarts, highlightEnds }: CodeViewerProps) => {
    const containerRef = useRef<HTMLDivElement>(null);

    // Decorations for all code snippets in the file
    const decorations = highlightStarts != null && highlightEnds != null
        ? highlightStarts.map((highlightStart, index) => ({
            start: { line: highlightStart - 1, character: 0 },
            end: { line: highlightEnds[index] - 1, character: 0 },
            properties: { class: 'code-viewer__highlighted-line' },
        }))
        : [];

    useEffect(() => {
        if (highlightStarts == null || highlightEnds == null || !containerRef.current) return;

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
    }, [code, highlightStarts, highlightEnds]);

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