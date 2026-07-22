import { forwardRef, useEffect, useRef, useState } from 'react';
import { CiLink } from 'react-icons/ci';
import ShikiHighlighter from 'react-shiki';
import { useTheme } from '../context/ThemeContext';
import { getShikiLanguage } from '../utils/codeLanguage';

interface CodeViewerProps {
   code: string;
   highlightRanges?: { start: number; end: number; color: string }[];
   /** 1-based line range to scroll into view; must match one of the highlight ranges. */
   scrollFocusStart?: number;
   scrollFocusEnd?: number;
   /** Invoked with the highlighted code range when "Show in paper" is clicked. */
   onShowInPaper?: (range: { start: number; end: number }) => void;
   /** File path of the code being shown; used to pick the syntax highlighting language. */
   filepath?: string;
}

type RangeActionPosition = { index: number; top: number; left: number };

const CodeViewer = forwardRef<HTMLDivElement, CodeViewerProps>(function CodeViewer(
    { code, highlightRanges, scrollFocusStart, scrollFocusEnd, onShowInPaper, filepath },
    ref,
) {
    // The scroller holds the code (and the forwarded ref so text selection works);
    // actions live in the non-scrolling outer wrapper so they can never scroll away.
    const scrollRef = useRef<HTMLDivElement>(null);
    const [actionsPositions, setActionsPositions] = useState<RangeActionPosition[]>([]);
    const { resolvedTheme } = useTheme();

    const setScrollRef = (node: HTMLDivElement | null) => {
        scrollRef.current = node;
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

    useEffect(() => {
        if (!highlightRanges?.length || !scrollRef.current) {
            setActionsPositions([]);
            return;
        }

        const scroller = scrollRef.current;

        const updateActionsPosition = () => {
            const scrollerRect = scroller.getBoundingClientRect();
            const positions = highlightRanges.flatMap((_, index) => {
                const firstLine = scroller.querySelector(
                    `.code-viewer__highlighted-line--range-${index}`,
                );
                if (!firstLine) return [];

                const lineRect = firstLine.getBoundingClientRect();
                return [{
                    index,
                    top: Math.min(
                        Math.max(lineRect.top - scrollerRect.top, 9),
                        scrollerRect.height - 9,
                    ),
                    left: Math.max(lineRect.left - scrollerRect.left, 0),
                }];
            });

            setActionsPositions(positions);
        };

        updateActionsPosition();

        const observer = new MutationObserver(updateActionsPosition);
        observer.observe(scroller, { childList: true, subtree: true, attributes: true });

        scroller.addEventListener('scroll', updateActionsPosition);
        window.addEventListener('resize', updateActionsPosition);

        return () => {
            observer.disconnect();
            scroller.removeEventListener('scroll', updateActionsPosition);
            window.removeEventListener('resize', updateActionsPosition);
        };
    }, [code, highlightRanges, scrollFocusStart, scrollFocusEnd]);

    useEffect(() => {
        if (highlightRanges == null || highlightRanges.length === 0 || !scrollRef.current) return;

        const container = scrollRef.current;
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
        <div className="code-viewer">
            <div ref={setScrollRef} className="code-viewer__scroll">
                <ShikiHighlighter
                    theme={resolvedTheme === 'dark' ? 'github-dark' : 'github-light'}
                    language={getShikiLanguage(filepath)}
                    showLineNumbers
                    decorations={decorations}
                >
                    {code}
                </ShikiHighlighter>
            </div>
            {actionsPositions.map(({ index, top, left }) => (
                <div
                    key={index}
                    className="code-viewer__highlight-actions"
                    style={{ top, left }}
                >
                    <button
                        type="button"
                        className="code-viewer__show-in-paper"
                        aria-label="Show in paper"
                        onClick={() => {
                            const range = highlightRanges?.[index];
                            if (range) onShowInPaper?.({ start: range.start, end: range.end });
                        }}
                    >
                        <CiLink aria-hidden />
                        <span className="code-viewer__show-in-paper-label">Show in paper</span>
                    </button>
                </div>
            ))}
        </div>
    );
});

export default CodeViewer;
