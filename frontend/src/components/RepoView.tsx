import { useEffect, useState } from 'react';
import { type githubRepoTreeResponse } from '../api/main';
import { VscFolder, VscFile } from 'react-icons/vsc';
import { IoIosArrowBack } from "react-icons/io";
import { getGithubFileFromBlobUrl } from '../api/main';
import CodeViewer from './CodeViewer.tsx';
import { useSidePanel } from '../context/SidePanelContext.tsx';


interface RepoViewProps {
    tree: githubRepoTreeResponse;
    code?: string,
    filepath?: string
}

type HighlightRange = {
  start: number;
  end: number;
}

const RepoView = ({ tree }: RepoViewProps) => {
    const [currentPath, setCurrentPath] = useState(() => "");
    const [currentFileContent, setCurrentFileContent] = useState<string | null>(null);
    const [highlightRanges, setHighlightRanges] = useState<HighlightRange[] | null>(null);
    const [scrollFocusRange, setScrollFocusRange] = useState<HighlightRange | null>(null);
    const { codeInfo } = useSidePanel();

    const [currentCodeDescription, setCurrentCodeDescription] = useState<string | null>(null);

    const getFileURLByPath = (path: string) => {
        return tree.tree.find((obj, _) => obj.path === path)?.url;
    };

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
        setHighlightRanges([] as HighlightRange[]);
        setCurrentPath(filepath);
        if (!isFile) {
            setCurrentFileContent(null);
            return;
        }
        setScrollFocusRange(null);
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
                code={currentFileContent}
                highlightStarts={highlightRanges?.map((highlightRange) => highlightRange.start)}
                highlightEnds={highlightRanges?.map((highlightRange) => highlightRange.end)}
                scrollFocusStart={scrollFocusRange?.start}
                scrollFocusEnd={scrollFocusRange?.end}
            /> : <div className="repo-tree__list">
                {getCurrentFiles().map((file, index) => (
                    <div key={index} className="repo-tree__row">
                        {file.mode === '040000'
                            ? <VscFolder className="repo-tree__icon repo-tree__icon--dir" />
                            : <VscFile className="repo-tree__icon repo-tree__icon--file" />
                        }
                        <button style={{ background: 'none', border: 'none', cursor: 'pointer' }} onClick={() => onEntryClick(file.path as string, file.url as string, file.mode !== '100644')} className="repo-tree__link">{file.path as string}</button>
                    </div>
                ))}
            </div>}
        </div>
    );
};

export default RepoView;