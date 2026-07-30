import { Fragment, type ReactNode } from 'react';

/**
 * Highlights repository paths and line references in Copilot answers.
 * Also renders **markdown bold** when the model uses it.
 */
const HIGHLIGHT_PATTERN =
    /\*\*([^*]+)\*\*|`([^`]+)`|([\w@./-]+\/[\w@./-]+(?:\.[a-zA-Z0-9]{1,12})?(?::\d+(?:-\d+)?)?)|([\w@.-]+\.(?:py|pyi|ipynb|tsx?|jsx?|mjs|cjs|json|md|ya?ml|toml|rs|go|java|cpp|cc|cxx|c|h|hpp|sh|rb|vue|wasm)(?::\d+(?:-\d+)?)?)|(\blines?\s+\d+(?:\s*[-–]\s*\d+)?\b)|(\bL\d+(?:-L\d+)?\b)/gi;

export function formatCopilotContent(text: string): ReactNode {
    const nodes: ReactNode[] = [];
    let lastIndex = 0;
    let key = 0;

    for (const match of text.matchAll(HIGHLIGHT_PATTERN)) {
        const index = match.index ?? 0;
        if (index > lastIndex) {
            nodes.push(text.slice(lastIndex, index));
        }

        const highlighted =
            match[1] ?? match[2] ?? match[3] ?? match[4] ?? match[5] ?? match[6] ?? match[0];
        nodes.push(<strong key={key++}>{highlighted}</strong>);
        lastIndex = index + match[0].length;
    }

    if (lastIndex < text.length) {
        nodes.push(text.slice(lastIndex));
    }

    if (nodes.length === 0) {
        return text;
    }
    if (nodes.length === 1) {
        return nodes[0];
    }
    return <Fragment>{nodes}</Fragment>;
}
