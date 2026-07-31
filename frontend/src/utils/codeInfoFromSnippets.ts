import type { codeSnippet } from '../api/types.ts';
import type { CodeInfo } from '../context/SidePanelContext.tsx';

type ContentToCodeTaskResult = {
    code_snippets?: codeSnippet[];
    reasoning?: string;
};

/** Celery task / cache-hit payloads may be a snippet list or a full mapping result. */
export function extractSnippetsFromMapResult(result: unknown): codeSnippet[] {
    if (!result) return [];
    if (Array.isArray(result)) {
        return result as codeSnippet[];
    }
    if (typeof result === 'object' && result !== null && 'code_snippets' in result) {
        const snippets = (result as ContentToCodeTaskResult).code_snippets;
        return Array.isArray(snippets) ? snippets : [];
    }
    return [];
}

export function reasoningFromMapResult(result: unknown): string {
    if (result && typeof result === 'object' && 'reasoning' in result) {
        const reasoning = (result as ContentToCodeTaskResult).reasoning;
        return typeof reasoning === 'string' ? reasoning : '';
    }
    return '';
}

export function buildCodeInfoFromSnippets(
    snippets: codeSnippet[],
    options: {
        description?: string;
        paperPageIndex?: number;
        activeIndex?: number;
    } = {},
): CodeInfo | null {
    const index = options.activeIndex ?? 0;
    const selected = snippets[index];
    if (!selected) return null;

    const filePath = selected.filepath;
    const rangesForFile = snippets
        .filter((snippet) => snippet.filepath === filePath)
        .map((snippet) => ({
            startLine: snippet.start_line,
            endLine: snippet.end_line,
        }));

    return {
        filePath,
        codeRanges: rangesForFile,
        scrollToRange: {
            startLine: selected.start_line,
            endLine: selected.end_line,
        },
        paperPageIndex: options.paperPageIndex,
        description: options.description ?? '',
        candidates: snippets.map((snippet) => ({
            filePath: snippet.filepath,
            startLine: snippet.start_line,
            endLine: snippet.end_line,
        })),
        activeCandidateIndex: index,
    };
}
