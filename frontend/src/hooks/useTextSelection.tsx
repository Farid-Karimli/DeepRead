import React from 'react';

export function usePDFTextSelection(
    pdfRoot: React.RefObject<HTMLElement | null>,
    onSelection: (selection: {
        text: string, 
        rect: DOMRect,
        range: Range,
    } | null) => void, // function that fires once selected text is extracted
) {
    React.useEffect(() => {

        const handleSelection = () => {
            const root = pdfRoot;
            const selection = document.getSelection();

            if (!root || !selection) {
                onSelection(null);
                return;
            }

            const text = selection.toString().trim();
            if (!text) {
                onSelection(null);
                return;
            }

            const range = selection.getRangeAt(0);
            const commonAncestor = range.getBoundingClientRect();

            onSelection(
                {
                    text, 
                    rect: commonAncestor,
                    range,
                }
            )

        }

        document.addEventListener('mouseup', handleSelection);

        return () => {
            document.removeEventListener('mouseup', handleSelection);
        }

    }, [pdfRoot, onSelection]);
}