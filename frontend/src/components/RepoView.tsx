import { useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { codeToContentMatch, githubRepoTreeResponse } from '../api/types.ts';
import { getGithubFileFromBlobUrl, mapCodeToContent, getCodeToContentMatches } from '../api/main';
import { dedupeRanges } from '../utils/dedupeRanges.ts';
import { VscFolder, VscFile } from 'react-icons/vsc';
import { IoIosArrowBack } from "react-icons/io";
import { IoChevronDown } from 'react-icons/io5';
import CodeViewer from './CodeViewer.tsx';
import { useSidePanel } from '../context/SidePanelContext.tsx';
import { usePDFTextSelection } from '../hooks/useTextSelection.tsx';
import { useCeleryTaskStatus } from '../hooks/useCeleryTaskStatus.ts';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import { UserContext } from '../context/userContext.tsx';

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

type CodeMatchFilter = 'all' | 'hide' | 'my' | 'others' | 'described' | 'not_described' | 'not_applicable';

const CODE_MATCH_FILTER_STORAGE_KEY = 'deepread.codeMatchFilter';
const DEFAULT_CODE_MATCH_FILTER: CodeMatchFilter = 'all';

const CODE_MATCH_FILTER_OPTIONS: { value: CodeMatchFilter; label: string }[] = [
    { value: 'all', label: 'Show all code matches' },
    { value: 'hide', label: 'Hide code matches' },
    { value: 'my', label: 'Show matches by me' },
    { value: 'others', label: 'Show matches by others' },
    { value: 'described', label: 'Show described matches' },
    { value: 'not_described', label: 'Show not described matches' },
    { value: 'not_applicable', label: 'Show not applicable matches' },
];

const readStoredCodeMatchFilter = (): CodeMatchFilter => {
    if (typeof window === 'undefined') return DEFAULT_CODE_MATCH_FILTER;
    const stored = window.localStorage.getItem(CODE_MATCH_FILTER_STORAGE_KEY);
    if (
        stored === 'all' ||
        stored === 'hide' ||
        stored === 'my' ||
        stored === 'others' ||
        stored === 'described' ||
        stored === 'not_described' ||
        stored === 'not_applicable'
    ) {
        return stored;
    }
    return DEFAULT_CODE_MATCH_FILTER;
};

const RepoView = ({ tree, paperId, setPaperHighlightSections }: RepoViewProps) => {
    const {currentUser} = useContext(UserContext);
    const [currentPath, setCurrentPath] = useState(() => "");
    const [currentFileContent, setCurrentFileContent] = useState<string | null>(null);
    const [scrollFocusRange, setScrollFocusRange] = useState<{ start: number; end: number } | null>(null);
    const { codeInfo, hideCode } = useSidePanel();
    const codeViewerRef = useRef<HTMLDivElement>(null);
    const codeMatchFilterRef = useRef<HTMLDivElement>(null);
    const [isCodeMatchFilterOpen, setIsCodeMatchFilterOpen] = useState(false);
    const [codeMatchFilter, setCodeMatchFilter] = useState<CodeMatchFilter>(readStoredCodeMatchFilter);

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
        user_id: number,
      };

    const codeMatchingMutation = useMutation({
        mutationFn: ({code, paperId, start, end, filepath, user_id}: CodeToContentInput) => mapCodeToContent(code, paperId, start, end, filepath, user_id),
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

    useEffect(() => {
        window.localStorage.setItem(CODE_MATCH_FILTER_STORAGE_KEY, codeMatchFilter);
    }, [codeMatchFilter]);

    useEffect(() => {
        if (!isCodeMatchFilterOpen) return;
        const handleClickOutside = (event: MouseEvent) => {
            if (codeMatchFilterRef.current && !codeMatchFilterRef.current.contains(event.target as Node)) {
                setIsCodeMatchFilterOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [isCodeMatchFilterOpen]);

    const highlightRanges = useMemo(() => {
        // Matches from the DB for this code file
        const fromDB = (codeToContentMatchesQuery.data ?? [])
            .filter((match: codeToContentMatch) => {
                const isMyMatch = currentUser != null && match.created_by === currentUser.id;
                if (codeMatchFilter === 'hide') return false;
                if (codeMatchFilter === 'all') return true;
                if (codeMatchFilter === 'my') return isMyMatch;
                if (codeMatchFilter === 'others') return !isMyMatch;
                return match.outputs.verdict === codeMatchFilter;
            })
            .map((match: codeToContentMatch) => ({
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
    }, [codeToContentMatchesQuery.data, codeInfo, currentPath, codeMatchFilter, currentUser]);

    usePDFTextSelection(codeViewerRef, setPendingCodeSelection);

    const handleShowInPaper = (range: { start: number; end: number }) => {
        const match = (codeToContentMatchesQuery.data ?? []).find(
            (m: codeToContentMatch) => m.inputs.start === range.start && m.inputs.end === range.end,
        );
        if (match?.outputs.sections) {
            setPaperHighlightSections(match.outputs.sections);
        }
    };

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
            filepath: currentPath,
            user_id: currentUser?.id ?? 1,
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
                                    {index < currentPathParts.length - 1 ? '/' : ''}
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
                {currentFileContent && (
                    <div className="match-filter" ref={codeMatchFilterRef}>
                        <button
                            type="button"
                            className="outline-action-btn match-filter__toggle"
                            aria-haspopup="true"
                            aria-expanded={isCodeMatchFilterOpen}
                            onClick={() => setIsCodeMatchFilterOpen((open) => !open)}
                        >
                            Filter code matches
                            <IoChevronDown aria-hidden />
                        </button>
                        {isCodeMatchFilterOpen && (
                            <div className="match-filter__menu" role="menu">
                                {CODE_MATCH_FILTER_OPTIONS.map((option) => (
                                    <button
                                        key={option.value}
                                        type="button"
                                        className={`match-filter__item${codeMatchFilter === option.value ? ' match-filter__item--active' : ''}`}
                                        role="menuitemradio"
                                        aria-checked={codeMatchFilter === option.value}
                                        onClick={() => {
                                            setCodeMatchFilter(option.value);
                                            setIsCodeMatchFilterOpen(false);
                                        }}
                                    >
                                        {option.label}
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                )}
            </div>
            {currentFileContent ? <CodeViewer
                ref={codeViewerRef}
                code={currentFileContent}
                highlightRanges={highlightRanges as { start: number; end: number; color: string }[]}
                scrollFocusStart={scrollFocusRange?.start}
                scrollFocusEnd={scrollFocusRange?.end}
                onShowInPaper={handleShowInPaper}
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
