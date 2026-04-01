import ShikiHighlighter from 'react-shiki';
import { useShikiHighlighter } from "react-shiki";

interface CodeSidePanelProps {
    codeContent: string;
}

const CodeSidePanel = ({codeContent}: CodeSidePanelProps) => {
    const highlightedCode = useShikiHighlighter(codeContent, "python", "github-dark");
    return (
        <div style={{
            height: '100%', 
            textAlign: 'left',
            fontFamily: 'var(--mono)',
            padding: 16,
            borderRadius: 8,
            border: '1px solid var(--border)',
            fontSize: '0.8rem',
        }}>
            <ShikiHighlighter theme="github-dark" language="python">
                {codeContent}
            </ShikiHighlighter>
        </div>
    )
}

export default CodeSidePanel;