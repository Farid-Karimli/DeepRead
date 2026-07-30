// src/context/SidePanelContext.tsx
import { createContext, useContext, useState, type ReactNode } from 'react';

type CodeRange = {
  startLine: number;
  endLine: number;
}

/** One candidate snippet in a multi-snippet match; used to populate the segmented pill list. */
export type CodeCandidate = {
  filePath: string;
  startLine: number;
  endLine: number;
};

export type CodeInfo = {
  filePath: string;
  codeRanges: CodeRange[];
  /** If set, scroll this range into view (still highlights all `codeRanges`). */
  scrollToRange?: CodeRange;
  /** Zero-based PDF page that opened this code match. */
  paperPageIndex?: number;
  description: string;
  /** All candidate snippets for the current match (may span multiple files), for the segmented pill switcher. */
  candidates?: CodeCandidate[];
  /** Index into `candidates` for the one currently shown. */
  activeCandidateIndex?: number;
};

type sidePanelContext = {
  codeInfo: CodeInfo | null;
  showCode: (codeInfo: CodeInfo) => void;
  hideCode: () => void;
  /** Switches the panel to the candidate at `index`, grouping ranges within its file. */
  selectCandidate: (index: number) => void;
};

const sidePanelContext = createContext<sidePanelContext>({
  codeInfo: null,
  showCode: () => {},
  hideCode: () => {},
  selectCandidate: () => {},
});

export function SidePanelProvider({ children }: { children: ReactNode }) {
  const [codeInfo, setCodeInfo] = useState<CodeInfo | null>(null);
  return (
    <sidePanelContext.Provider value={{
      codeInfo,
      showCode: (codeInfo: CodeInfo) =>
        setCodeInfo(codeInfo),
      hideCode: () => setCodeInfo(null),
      selectCandidate: (index: number) =>
        setCodeInfo((prev) => {
          if (!prev?.candidates) return prev;
          const candidate = prev.candidates[index];
          if (!candidate) return prev;

          const rangesForFile = prev.candidates
            .filter((c) => c.filePath === candidate.filePath)
            .map((c) => ({ startLine: c.startLine, endLine: c.endLine }));

          return {
            ...prev,
            filePath: candidate.filePath,
            codeRanges: rangesForFile,
            scrollToRange: { startLine: candidate.startLine, endLine: candidate.endLine },
            activeCandidateIndex: index,
          };
        }),
    }}>
      {children}
    </sidePanelContext.Provider>
  );
}

export const useSidePanel = () => useContext(sidePanelContext);
