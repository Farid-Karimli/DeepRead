import { forwardRef, useEffect, useRef, useState } from 'react';
import { CiLink } from 'react-icons/ci';
import ShikiHighlighter from 'react-shiki';

interface CodeViewerProps {
   code: string;
   highlightRanges?: { start: number; end: number; color: string }[];
   /** 1-based line range to scroll into view; must match one of the highlight ranges. */
   scrollFocusStart?: number;
   scrollFocusEnd?: number;
}

type ActionsPosition = { top: number; left: number };

const CodeViewer = forwardRef<HTMLDivElement, CodeViewerProps>(function CodeViewer(
    { code, highlightRanges, scrollFocusStart, scrollFocusEnd },
    ref,
) {
    const containerRef = useRef<HTMLDivElement>(null);
    const [actionsPosition, setActionsPosition] = useState<ActionsPosition | null>(null);

    const setContainerRef = (node: HTMLDivElement | null) => {
        containerRef.current = node;
        if (typeof ref === 'function') {
            ref(node);
        } else if (ref) {
            ref.current = node;
        }
    };

    // Decorations for all code snippets in the file
    const decorations = highlightRanges != null && highlightRanges.length > 0
        ? highlightRanges.map((highlightRange, index) => {
            const highlightStart = highlightRange.start;
            const highlightEnd = highlightRange.end;
            const highlightColor = highlightRange.color;
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
                    style: `background-color: ${highlightColor}`
                },
            };
        })
        : [];

    const actionsTargetRangeIndex =
        highlightRanges != null && highlightRanges.length > 0
            ? (() => {
                if (scrollFocusStart != null && scrollFocusEnd != null) {
                    const focusIndex = highlightRanges.findIndex(
                        (range) =>
                            range.start === scrollFocusStart && range.end === scrollFocusEnd,
                    );
                    if (focusIndex >= 0) return focusIndex;
                }
                return 0;
            })()
            : null;

    useEffect(() => {
        if (actionsTargetRangeIndex == null || !containerRef.current) {
            setActionsPosition(null);
            return;
        }

        const container = containerRef.current;
        const rangeSelector = `.code-viewer__highlighted-line--range-${actionsTargetRangeIndex}`;

        const updateActionsPosition = () => {
            const firstLine = container.querySelector(rangeSelector);
            if (!firstLine) {
                setActionsPosition(null);
                return;
            }
            const containerRect = container.getBoundingClientRect();
            const lineRect = firstLine.getBoundingClientRect();
            setActionsPosition({
                top: lineRect.top - containerRect.top + container.scrollTop,
                left: lineRect.left - containerRect.left + container.scrollLeft,
            });
        };

        updateActionsPosition();

        const observer = new MutationObserver(updateActionsPosition);
        observer.observe(container, { childList: true, subtree: true, attributes: true });

        container.addEventListener('scroll', updateActionsPosition);
        window.addEventListener('resize', updateActionsPosition);

        return () => {
            observer.disconnect();
            container.removeEventListener('scroll', updateActionsPosition);
            window.removeEventListener('resize', updateActionsPosition);
        };
    }, [code, highlightRanges, scrollFocusStart, scrollFocusEnd, actionsTargetRangeIndex]);

    useEffect(() => {
        if (highlightRanges == null || highlightRanges.length === 0 || !containerRef.current) return;

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
    }, [code, highlightRanges, scrollFocusStart, scrollFocusEnd]);

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
            {actionsPosition && (
                <div
                    className="code-viewer__highlight-actions"
                    style={{ top: actionsPosition.top, left: actionsPosition.left }}
                >
                    <button
                        type="button"
                        className="code-viewer__show-in-paper"
                        aria-label="Show in paper"
                    >
                        <CiLink aria-hidden />
                        <span className="code-viewer__show-in-paper-label">Show in paper</span>
                    </button>
                </div>
            )}
        </div>
    );
});

export default CodeViewer;
