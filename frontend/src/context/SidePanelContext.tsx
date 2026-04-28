// src/context/SidePanelContext.tsx
import React, { createContext, useContext, useState, type ReactNode } from 'react';

type CodeRange = {
  startLine: number;
  endLine: number;
}

type CodeInfo = {
  filePath: string;
  codeRanges: CodeRange[];
  /** If set, scroll this range into view (still highlights all `codeRanges`). */
  scrollToRange?: CodeRange;
  description: string;
};

type sidePanelContext = {
  codeInfo: CodeInfo | null;
  showCode: (codeInfo: CodeInfo) => void;
  hideCode: () => void;
};

const sidePanelContext = createContext<sidePanelContext>({
  codeInfo: null,
  showCode: () => {},
  hideCode: () => {},
});

export function SidePanelProvider({ children }: { children: ReactNode }) {
  const [codeInfo, setCodeInfo] = useState<CodeInfo | null>(null);
  return (
    <sidePanelContext.Provider value={{
      codeInfo,
      showCode: (codeInfo: CodeInfo) =>
        setCodeInfo(codeInfo),
      hideCode: () => setCodeInfo(null),
    }}>
      {children}
    </sidePanelContext.Provider>
  );
}

export const useSidePanel = () => useContext(sidePanelContext);