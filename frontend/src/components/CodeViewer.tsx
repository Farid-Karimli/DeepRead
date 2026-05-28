import { forwardRef, useEffect, useRef, useState } from 'react';
import { IoClose } from 'react-icons/io5';
import ShikiHighlighter from 'react-shiki';

interface CodeViewerProps {
   code: string;
   highlightStarts?: number[]; // Could be multiple snippets in the file
   highlightEnds?: number[];
   /** 1-based line range to scroll into view; must match one of the highlight ranges. */
   scrollFocusStart?: number;
   scrollFocusEnd?: number;
   onClearHighlight?: () => void;
}

type ClearButtonPosition = { top: number; left: number };

const CodeViewer = forwardRef<HTMLDivElement, CodeViewerProps>(function CodeViewer(
    { code, highlightStarts, highlightEnds, scrollFocusStart, scrollFocusEnd, onClearHighlight },
    ref,
) {
    const containerRef = useRef<HTMLDivElement>(null);
    const [clearButtonPosition, setClearButtonPosition] = useState<ClearButtonPosition | null>(null);

    const setContainerRef = (node: HTMLDivElement | null) => {
        containerRef.current = node;
        if (typeof ref === 'function') {
            ref(node);
        } else if (ref) {
            ref.current = node;
        }
    };

    // Decorations for all code snippets in the file
    const decorations = highlightStarts != null && highlightEnds != null
        ? highlightStarts.map((highlightStart, index) => {
            const highlightEnd = highlightEnds[index];
            const isScrollFocus =
                scrollFocusStart != null &&
                scrollFocusEnd != null &&
                scrollFocusStart === highlightStart &&
                scrollFocusEnd === highlightEnd;
            const rangeClass = `code-viewer__highlighted-line--range-${index}`;
            const focusClass = isScrollFocus ? ' code-viewer__highlighted-line--scroll-focus' : '';
            return {
                start: { line: highlightStart - 1, character: 0 },
                end: { line: highlightEnd - 1, character: 0 },
                properties: {
                    class: `code-viewer__highlighted-line ${rangeClass}${focusClass}`,
                },
            };
        })
        : [];

    const clearTargetRangeIndex =
        highlightStarts != null && highlightEnds != null
            ? (() => {
                if (scrollFocusStart != null && scrollFocusEnd != null) {
                    const focusIndex = highlightStarts.findIndex(
                        (start, index) =>
                            start === scrollFocusStart && highlightEnds[index] === scrollFocusEnd,
                    );
                    if (focusIndex >= 0) return focusIndex;
                }
                return 0;
            })()
            : null;

    useEffect(() => {
        if (onClearHighlight == null || clearTargetRangeIndex == null || !containerRef.current) {
            setClearButtonPosition(null);
            return;
        }

        const container = containerRef.current;
        const rangeSelector = `.code-viewer__highlighted-line--range-${clearTargetRangeIndex}`;

        const updateClearButtonPosition = () => {
            const firstLine = container.querySelector(rangeSelector);
            if (!firstLine) {
                setClearButtonPosition(null);
                return;
            }
            const containerRect = container.getBoundingClientRect();
            const lineRect = firstLine.getBoundingClientRect();
            setClearButtonPosition({
                top: lineRect.top - containerRect.top + container.scrollTop,
                left: lineRect.left - containerRect.left + container.scrollLeft,
            });
        };

        updateClearButtonPosition();

        const observer = new MutationObserver(updateClearButtonPosition);
        observer.observe(container, { childList: true, subtree: true, attributes: true });

        container.addEventListener('scroll', updateClearButtonPosition);
        window.addEventListener('resize', updateClearButtonPosition);

        return () => {
            observer.disconnect();
            container.removeEventListener('scroll', updateClearButtonPosition);
            window.removeEventListener('resize', updateClearButtonPosition);
        };
    }, [code, highlightStarts, highlightEnds, scrollFocusStart, scrollFocusEnd, onClearHighlight, clearTargetRangeIndex]);

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
        <div ref={setContainerRef} className="code-viewer">
            <ShikiHighlighter
                theme="github-dark"
                language="python"
                showLineNumbers
                decorations={decorations}
            >
                {code}
            </ShikiHighlighter>
            {onClearHighlight && clearButtonPosition && (
                <button
                    type="button"
                    className="code-viewer__clear-highlight"
                    style={{ top: clearButtonPosition.top, left: clearButtonPosition.left }}
                    onClick={onClearHighlight}
                    aria-label="Clear highlight"
                >
                    <IoClose aria-hidden />
                </button>
            )}
        </div>
    );
});

export default CodeViewer;
