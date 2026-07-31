import React from 'react';

export function usePDFTextSelection(
    pdfRoot: React.RefObject<HTMLElement | null>,
    setSelection: (selection: {
        text: string, 
        rect: DOMRect,
        range: Range,
    } | null) => void, // function that sets the value of the selection for outside scope
) {
    React.useEffect(() => {

        const handleSelection = () => {
            const root = pdfRoot.current;
            const selection = document.getSelection();

            if (!root || !selection) {
                setSelection(null);
                return;
            }

            const text = selection.toString().trim();
            if (!text) {
                setSelection(null);
                return;
            }

            const range = selection.getRangeAt(0);
            if (!root.contains(range.commonAncestorContainer)) {
                setSelection(null);
                return;
            }

            const commonAncestor = range.getBoundingClientRect();

            setSelection({
                text,
                rect: commonAncestor,
                range: range.cloneRange(),
            });

        }

        document.addEventListener('mouseup', handleSelection);

        return () => {
            document.removeEventListener('mouseup', handleSelection);
        }

    }, [pdfRoot, setSelection]);
}