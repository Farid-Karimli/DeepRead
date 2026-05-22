import { useEffect, useRef } from 'react';
import ShikiHighlighter from 'react-shiki';

interface CodeViewerProps {
   code: string;
   highlightStarts?: number[]; // Could be multiple snippets in the file
   highlightEnds?: number[];
   /** 1-based line range to scroll into view; must match one of the highlight ranges. */
   scrollFocusStart?: number;
   scrollFocusEnd?: number;
}

const CodeViewer = ({ code, highlightStarts, highlightEnds, scrollFocusStart, scrollFocusEnd }: CodeViewerProps) => {
    const containerRef = useRef<HTMLDivElement>(null);

    // Decorations for all code snippets in the file
    const decorations = highlightStarts != null && highlightEnds != null
        ? highlightStarts.map((highlightStart, index) => {
            const highlightEnd = highlightEnds[index];
            const isScrollFocus =
                scrollFocusStart != null &&
                scrollFocusEnd != null &&
                scrollFocusStart === highlightStart &&
                scrollFocusEnd === highlightEnd;
            return {
                start: { line: highlightStart - 1, character: 0 },
                end: { line: highlightEnd - 1, character: 0 },
                properties: {
                    class: isScrollFocus
                        ? 'code-viewer__highlighted-line code-viewer__highlighted-line--scroll-focus'
                        : 'code-viewer__highlighted-line',
                },
            };
        })
        : [];

    useEffect(() => {
        if (highlightStarts == null || highlightEnds == null || !containerRef.current) return;

        const container = containerRef.current;
        const tryScroll = () => {
            const focusEl = container.querySelector('.code-viewer__highlighted-line--scroll-focus');
            const el =
                focusEl ??
                container.querySelector('.code-viewer__highlighted-line');
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
    }, [code, highlightStarts, highlightEnds, scrollFocusStart, scrollFocusEnd]);

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