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

const RepoView = ({ tree }: RepoViewProps) => {
    const [currentPath, setCurrentPath] = useState(() => "");
    const [currentFile, setCurrentFile] = useState<string | null>(null);
    const [highlightRange, setHighlightRange] = useState<{ start: number; end: number } | null>(null);
    const { codeInfo } = useSidePanel();

    const getFileURLByPath = (path: string) => {
        return tree.tree.find((obj, _) => obj.path === path)?.url;
    };

    useEffect(() => {
        if (codeInfo) {
            setCurrentPath(codeInfo.filePath);
            setHighlightRange({ start: codeInfo.startLine, end: codeInfo.endLine });
            const url = getFileURLByPath(codeInfo.filePath);
            if (url) {
                getGithubFileFromBlobUrl(url).then((content) => {
                    setCurrentFile(content);
                }).catch(() => {
                    setCurrentFile(codeInfo.code);
                });
            } else {
                setCurrentFile(codeInfo.code);
            }
        }
    }, [codeInfo]);

    const currentPathParts = currentPath.split('/');

    const fileDepthDifference = (filepath1: string, filepath2: string) => {
        const n1 = filepath1.split("/").length;
        const n2 = filepath2.split("/").length;
        // console.log(`For ${filepath1} and ${filepath2}, the difference is ${Math.abs(n1 - n2)}`);

        return Math.abs(n1 - n2);
    }

    const getCurrentFiles = () => {
        const files = tree.tree.filter((obj, _) =>{
            const fp: string = obj.path;
            const url: string = obj.url;
            const type: string = obj.mode === '100644' ? 'file' : 'directory';
            const fileDifference = fileDepthDifference(currentPath, fp);

            if (
                (fp.startsWith(currentPath) && fp.length !== currentPath.length) // directory
                &&
                (fileDifference<1)
            ) {
                return { path: fp, url: url, type: type };
            }
        }
        )

        return files;
    }

    const onFileClick = (filepath: string, url: string) => {
        setCurrentPath(filepath);
        setHighlightRange(null);
        getGithubFileFromBlobUrl(url).then((content) => {
            setCurrentFile(content);
        }).catch((error) => {
            console.error('error', error);
            setCurrentFile(null);
        });
    }

    const backButtonClick = () => {
        setCurrentPath(currentPathParts.slice(0, -1).join('/'));
        setCurrentFile(null);
        setHighlightRange(null);
    }

    return (
        <div className="repo-tree">
            <h3 className="repo-tree__heading">Repo View</h3>
            <div className="repo-tree__breadcrumb">
                {currentPathParts.map((part, index) => (
                    <span key={index}>
                        {part}
                        {index < currentPathParts.length - 1 ? '/ ' : ' '}
                    </span>
                ))}
            </div>
            <button style={{ background: 'none', border: 'none', cursor: 'pointer' }} onClick={backButtonClick} className="repo-tree__link"><IoIosArrowBack /></button>
            {currentFile ? <CodeViewer
                code={currentFile}
                highlightStart={highlightRange?.start}
                highlightEnd={highlightRange?.end}
            /> : <div className="repo-tree__list">
                {getCurrentFiles().map((file, index) => (
                    <div key={index} className="repo-tree__row">
                        {file.mode !== '100644'
                            ? <VscFolder className="repo-tree__icon repo-tree__icon--dir" />
                            : <VscFile className="repo-tree__icon repo-tree__icon--file" />
                        }
                        <button style={{ background: 'none', border: 'none', cursor: 'pointer' }} onClick={() => onFileClick(file.path as string, file.url as string)} className="repo-tree__link">{file.path as string}</button>
                    </div>
                ))}
            </div>}
        </div>
    );
};

export default RepoView;