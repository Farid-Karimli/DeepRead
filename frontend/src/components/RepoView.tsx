import { useEffect, useRef, useState } from 'react';
import type { githubRepoTreeResponse } from '../api/types.ts';
import { getGithubFileFromBlobUrl, mapCodeToContent, getCodeMappingStatus } from '../api/main';
import { VscFolder, VscFile } from 'react-icons/vsc';
import { IoIosArrowBack } from "react-icons/io";
import CodeViewer from './CodeViewer.tsx';
import { useSidePanel } from '../context/SidePanelContext.tsx';
import { usePDFTextSelection } from '../hooks/useTextSelection.tsx';

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

type HighlightRange = {
  start: number;
  end: number;
}

const RepoView = ({ tree, paperId, setPaperHighlightSections }: RepoViewProps) => {
    const [currentPath, setCurrentPath] = useState(() => "");
    const [currentFileContent, setCurrentFileContent] = useState<string | null>(null);
    const [highlightRanges, setHighlightRanges] = useState<HighlightRange[] | null>(null);
    const [scrollFocusRange, setScrollFocusRange] = useState<HighlightRange | null>(null);
    const { codeInfo } = useSidePanel();
    const codeViewerRef = useRef<HTMLDivElement>(null);

    const [currentCodeDescription, setCurrentCodeDescription] = useState<string | null>(null);

    const [pendingCodeSelection, setPendingCodeSelection] = useState<{
        text: string;
        rect: DOMRect;
        range: Range;
    } | null>(null);
    const [codeMappingLoading, setCodeMappingLoading] = useState(false);
    const [codeMappingTaskId, setCodeMappingTaskId] = useState<string | null>(null);

    usePDFTextSelection(codeViewerRef, setPendingCodeSelection);

    const getFileURLByPath = (path: string) => {
        return tree.tree.find((obj, _) => obj.path === path)?.url;
    };

    const submitPendingCodeSelection = () => {
        if (!pendingCodeSelection || codeMappingTaskId !== null) return;

        setCodeMappingLoading(true);
        mapCodeToContent(pendingCodeSelection.text, paperId)
            .then((response) => {
                if (response.status === 'SUCCESS') {
                    console.log('Code mapping successful', response.result);
                    setCodeMappingLoading(false);
                    if (!response.result) {
                        console.error('No result found');
                        return;
                    }
                    const result: any = response.result;
                    setPaperHighlightSections(result);
                }
                else {
                    setCodeMappingTaskId(response.task_id);
                }
            })
            .catch((error) => {
                console.error('error', error);
                setCodeMappingLoading(false);
                setCodeMappingTaskId(null);
                setPendingCodeSelection(null);
            });
    };

    useEffect(() => {
        if (!codeMappingTaskId) return;
        let cancelled = false;

        const poll = async () => {
            if (cancelled) {
                setCodeMappingLoading(false);
                return;
            }

            const status = await getCodeMappingStatus(codeMappingTaskId);

            if (cancelled) {
                setCodeMappingLoading(false);
                return;
            }

            if (status.status === 'FAILURE') {
                console.error('Code mapping failed');
                setCodeMappingLoading(false);
                setCodeMappingTaskId(null);
                setPendingCodeSelection(null);
                return;
            }

            if (status.status === 'SUCCESS' && status.result) {
                setCodeMappingLoading(false);
                setPaperHighlightSections(status.result);
                setCodeMappingTaskId(null);
                setPendingCodeSelection(null);
                return;
            }

            setTimeout(poll, 5000);
        };

        poll();
        return () => { cancelled = true; };
    }, [codeMappingTaskId, setPaperHighlightSections]);

    useEffect(() => {
        if (codeInfo) {
            setCurrentPath(codeInfo.filePath);
            setCurrentCodeDescription(codeInfo.description);
            setHighlightRanges(codeInfo.codeRanges.map((codeRange) => ({ start: codeRange.startLine, end: codeRange.endLine })));
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
        setHighlightRanges([]);
        setScrollFocusRange(null);
        setCurrentCodeDescription(null);
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
            setHighlightRanges([] as HighlightRange[]);
            setScrollFocusRange(null);
            setCurrentPath(parentDir);
            setCurrentCodeDescription(null);
            setPendingCodeSelection(null);
            return;
        }
        setCurrentPath(parentDir);
    }

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
                highlightStarts={highlightRanges?.map((highlightRange) => highlightRange.start)}
                highlightEnds={highlightRanges?.map((highlightRange) => highlightRange.end)}
                scrollFocusStart={scrollFocusRange?.start}
                scrollFocusEnd={scrollFocusRange?.end}
                onClearHighlight={
                    highlightRanges && highlightRanges.length > 0
                        ? () => {
                            setHighlightRanges([]);
                            setScrollFocusRange(null);
                            setCurrentCodeDescription(null);
                        }
                        : undefined
                }
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
                            onClick={submitPendingCodeSelection}
                            disabled={codeMappingLoading || codeMappingTaskId !== null}
                        >
                            {codeMappingLoading ? 'Mapping...' : 'Map to paper content'}
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
