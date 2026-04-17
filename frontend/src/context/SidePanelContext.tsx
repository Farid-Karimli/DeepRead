// src/context/SidePanelContext.tsx
import React, { createContext, useContext, useState, type ReactNode } from 'react';

type CodeInfo = {
  code: string;
  filePath: string;
  startLine: number;
  endLine: number;
};

type sidePanelContext = {
  codeInfo: CodeInfo | null;
  showCode: (code: string, filePath: string, startLine: number, endLine: number) => void;
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
      showCode: (code: string, filePath: string, startLine: number, endLine: number) =>
        setCodeInfo({ code, filePath, startLine, endLine }),
      hideCode: () => setCodeInfo(null),
    }}>
      {children}
    </sidePanelContext.Provider>
  );
}

export const useSidePanel = () => useContext(sidePanelContext);