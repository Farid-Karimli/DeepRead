import { useEffect, useMemo, useRef, useState } from 'react';
import type { codeToContentMatch, githubRepoTreeResponse } from '../api/types.ts';
import { getGithubFileFromBlobUrl, mapCodeToContent, getCodeToContentMatches } from '../api/main';
import { dedupeRanges } from '../utils/dedupeRanges.ts';
import { VscFolder, VscFile } from 'react-icons/vsc';
import { IoIosArrowBack } from "react-icons/io";
import CodeViewer from './CodeViewer.tsx';
import { useSidePanel } from '../context/SidePanelContext.tsx';
import { usePDFTextSelection } from '../hooks/useTextSelection.tsx';
import { useCeleryTaskStatus } from '../hooks/useCeleryTaskStatus.ts';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

type PaperHighlight = {
    section_id: string;
    description: string;
};
interface RepoViewProps {
    tree: githubRepoTreeResponse;
    paperId: string;
    code?: string,
    filepath?: string,
    setPaperHighlightSections: (paperHighlightSections: PaperHighlight[]) => void
}

const CONTENT_MATCH_VERDICT_TO_COLOR: Record<string, string> = {
    "described": "rgba(135, 100, 47, 0.3)",
    "not_described": "rgb(230, 94, 94)",
    "not_applicable": "rgba(168, 168, 168, 0.6)",
}

const RepoView = ({ tree, paperId, setPaperHighlightSections }: RepoViewProps) => {
    const [currentPath, setCurrentPath] = useState(() => "");
    const [currentFileContent, setCurrentFileContent] = useState<string | null>(null);
    const [scrollFocusRange, setScrollFocusRange] = useState<{ start: number; end: number } | null>(null);
    const { codeInfo, hideCode } = useSidePanel();
    const codeViewerRef = useRef<HTMLDivElement>(null);

    const [currentCodeDescription, setCurrentCodeDescription] = useState<string | null>(null);

    const [pendingCodeSelection, setPendingCodeSelection] = useState<{
        text: string;
        rect: DOMRect;
        range: Range;
    } | null>(null);
    const [codeMappingLoading, setCodeMappingLoading] = useState(false);
    const [codeMatchingTaskId, setCodeMatchingTaskId] = useState<string | null>(null);

    const queryClient = useQueryClient();
    const codeMatchingTaskQuery = useCeleryTaskStatus(codeMatchingTaskId, { queryKey: 'codeMatchingTask' });

    type CodeToContentInput = {
        code: string;
        paperId: string;
        start: number, 
        end: number,
        filepath: string,
      };

    const codeMatchingMutation = useMutation({
        mutationFn: ({code, paperId, start, end, filepath}: CodeToContentInput) => mapCodeToContent(code, paperId, start, end, filepath),
        onSuccess: (response) => {
            if (response.status === "SUCCESS") {
                if (response.result) {
                    setPaperHighlightSections(response.result);
                }
                queryClient.invalidateQueries({queryKey: ["codeToContentMatches", paperId, currentPath]})
            } else if (response.task_id) {
                setCodeMatchingTaskId(response.task_id);
            }
        },
        onError: (error) => {
            console.log(`Error occured when matching code to content: ${error}`)
            setCodeMatchingTaskId(null);
            setPendingCodeSelection(null);
        }
        
    })

    const codeToContentMatchesQuery = useQuery({
        queryKey: ["codeToContentMatches", paperId, currentPath],
        queryFn: () => getCodeToContentMatches(paperId, currentPath),
        enabled: Boolean(paperId) && Boolean(currentPath),
    })

    const highlightRanges = useMemo(() => {
        // Matches from the DB for this code file
        const fromDB = (codeToContentMatchesQuery.data ?? []).map((match: codeToContentMatch) => ({
                start: match.inputs.start,
                end: match.inputs.end,
                color: CONTENT_MATCH_VERDICT_TO_COLOR[match.outputs.verdict]
        }));
        // Matches from the user pick
        const fromUser = codeInfo?.filePath === currentPath ? codeInfo.codeRanges.map((r) => ({ 
                start: r.startLine, 
                end: r.endLine, 
                color: "rgba(145, 102, 189, 0.3)" 
        })) : [];

        return dedupeRanges([...fromDB, ...fromUser]);
    }, [codeToContentMatchesQuery.data, codeInfo, currentPath]);

    usePDFTextSelection(codeViewerRef, setPendingCodeSelection);

    const getFileURLByPath = (path: string) => {
        return tree.tree.find((obj, _) => obj.path === path)?.url;
    };

    useEffect(() => {
        if (codeMatchingTaskQuery.data?.status === 'SUCCESS' && codeMatchingTaskQuery.data.result) {
            const sections = codeMatchingTaskQuery.data.result as unknown as PaperHighlight[];
            setPaperHighlightSections(sections);
            setCodeMatchingTaskId(null);
            setPendingCodeSelection(null);
            queryClient.invalidateQueries({ queryKey: ["codeToContentMatches", paperId, currentPath] });
            return;
        }

        if (codeMatchingTaskQuery.data?.status === 'FAILURE') {
            console.error('Code mapping failed');
            setCodeMappingLoading(false);
            setCodeMatchingTaskId(null);
            setPendingCodeSelection(null);
        }
    }, [codeMatchingTaskQuery.data, setPaperHighlightSections, queryClient, paperId, currentPath]);

    useEffect(() => {
        if (codeInfo) {
            setCurrentPath(codeInfo.filePath);
            setCurrentCodeDescription(codeInfo.description);
            setScrollFocusRange(
                codeInfo.scrollToRange
                    ? { start: codeInfo.scrollToRange.startLine, end: codeInfo.scrollToRange.endLine }
                    : null,
            );
            const url = getFileURLByPath(codeInfo.filePath);
            if (url) {
                getGithubFileFromBlobUrl(url).then((content) => {
                    setCurrentFileContent(content);
                }).catch((error) => {
                    console.error('error', error);
                    setCurrentFileContent(null);
                });
            } else {
                console.error('file not found', codeInfo.filePath);
                setCurrentFileContent(null);
            }
        }
    }, [codeInfo]);

    const currentPathParts = currentPath.split('/').filter(Boolean);

    const getCurrentFiles = () => {
        const isRoot = currentPath === "";
        const prefix = isRoot ? "" : currentPath + "/";
        const expectedDepth = isRoot ? 1 : currentPathParts.length + 1;

        const result = tree.tree.filter((obj) => {
            const fp: string = obj.path;
            if (!fp.startsWith(prefix)) return false;
            if (fp.length === prefix.length) return false;
            return fp.split('/').length === expectedDepth;
        });
        return result;
    }

    const onEntryClick = (filepath: string, url: string, isFile: boolean) => {
        setScrollFocusRange(null);
        setCurrentCodeDescription(null);
        hideCode();
        setPendingCodeSelection(null);
        setCurrentPath(filepath);
        if (!isFile) {
            setCurrentFileContent(null);
            return;
        }
        getGithubFileFromBlobUrl(url).then((content) => {
            setCurrentFileContent(content);
        }).catch((error) => {
            console.error('error', error);
            setCurrentFileContent(null);
        });
    }

    const backButtonClick = () => {
        const parts = currentPath.split('/').filter(Boolean);
        const parentDir = parts.slice(0, -1).join('/');
        if (currentFileContent) {
            setCurrentFileContent(null);
            setScrollFocusRange(null);
            setCurrentPath(parentDir);
            setCurrentCodeDescription(null);
            hideCode();
            setPendingCodeSelection(null);
            return;
        }
        setCurrentPath(parentDir);
    }

    function lineRangeFromRange(fileContent: string, range: Range): { start: number; end: number } {
        const anchor =
            range.startContainer instanceof Element
                ? range.startContainer
                : range.startContainer.parentElement;
        const codeRoot = anchor?.closest('code');
        if (!codeRoot) return { start: 1, end: 1 };

        // Count characters from the top of the rendered <code> block to a range boundary.
        const offsetInCode = (container: Node, offset: number) => {
            const probe = document.createRange();
            probe.selectNodeContents(codeRoot);
            probe.setEnd(container, offset);
            return probe.toString().length;
        };

        const startOffset = offsetInCode(range.startContainer, range.startOffset);
        const endOffset = offsetInCode(range.endContainer, range.endOffset);
        const [from, to] = startOffset <= endOffset ? [startOffset, endOffset] : [endOffset, startOffset];

        // 1-based lines, matching CodeViewer highlightStarts/highlightEnds.
        return {
            start: fileContent.slice(0, from).split('\n').length,
            end: fileContent.slice(0, to).split('\n').length,
        };
    }

    const handleSelectionSubmit = () => {
        if (!pendingCodeSelection || !currentFileContent || !currentPath) return;

        const lineRange = lineRangeFromRange(currentFileContent, pendingCodeSelection.range);

        const input: CodeToContentInput = {
            code: pendingCodeSelection.text,
            paperId: paperId,
            start: lineRange.start,
            end: lineRange.end,
            filepath: currentPath
        }
        codeMatchingMutation.mutate(input);
    }

    const isMapping = codeMatchingMutation.isPending || codeMatchingTaskId !== null;    

    return (
        <div className="repo-tree">
            <h3 className="repo-tree__heading">Repo View</h3>
            <div className="repo-tree__header">
                <div className="repo-tree__header-row">
                    {currentPath !== "" && (
                        <button
                            type="button"
                            onClick={backButtonClick}
                            className="repo-tree__back-btn"
                            aria-label="Go back"
                        >
                            <IoIosArrowBack />
                        </button>
                    )}
                    <div className="repo-tree__breadcrumb" title={currentPath || 'Repository root'}>
                        {currentPathParts.length > 0 ? (
                            currentPathParts.map((part, index) => (
                                <span key={index}>
                                    {part}
                                    {index < currentPathParts.length - 1 ? '/ ' : ''}
                                </span>
                            ))
                        ) : (
                            <span>Repository root</span>
                        )}
                    </div>
                </div>
                {currentCodeDescription && (
                    <div className="repo-tree__description">{currentCodeDescription}</div>
                )}
            </div>
            {currentPath !== "" && <button style={{ background: 'none', border: 'none', cursor: 'pointer' }} onClick={backButtonClick} className="repo-tree__link"><IoIosArrowBack /></button>}
            {currentFileContent ? <CodeViewer
                ref={codeViewerRef}
                code={currentFileContent}
                highlightRanges={highlightRanges as { start: number; end: number; color: string }[]}
                scrollFocusStart={scrollFocusRange?.start}
                scrollFocusEnd={scrollFocusRange?.end}
            /> : <div className="repo-tree__list">
                {getCurrentFiles().map((file, index) => (
                    <div key={index} className="repo-tree__row">
                        {file.mode === '040000'
                            ? <VscFolder className="repo-tree__icon repo-tree__icon--dir" />
                            : <VscFile className="repo-tree__icon repo-tree__icon--file" />
                        }
                        <button style={{ background: 'none', border: 'none', cursor: 'pointer' }} onClick={() => onEntryClick(file.path as string, file.url as string, file.mode !== "040000")} className="repo-tree__link">{file.path.split('/').pop()}</button>
                    </div>
                ))}
            </div>}

            {pendingCodeSelection && currentFileContent && (
                <div
                    className="pdf-selection-popover"
                    style={{
                        position: 'fixed',
                        left: pendingCodeSelection.rect.right + 8,
                        top: pendingCodeSelection.rect.bottom + 8,
                        zIndex: 10000,
                    }}
                >
                    <div className="pdf-selection-popover__actions">
                        <button
                            type="button"
                            className="pdf-selection-popover__btn pdf-selection-popover__btn--primary"
                            onClick={handleSelectionSubmit}
                            disabled={isMapping}
                        >
                            {isMapping ? 'Mapping...' : 'Map to paper content'}
                        </button>
                        <button
                            type="button"
                            className="pdf-selection-popover__btn pdf-selection-popover__btn--ghost"
                            onClick={() => setPendingCodeSelection(null)}
                        >
                            Cancel
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
};

export default RepoView;
