// src/context/SidePanelContext.tsx
import React, { createContext, useContext, useState, type ReactNode } from 'react';

type sidePanelContext = {
  codeContent: string | null;
  showCode: (code: string) => void;
  hideCode: () => void;
};

const sidePanelContext = createContext<sidePanelContext>({
  codeContent: null,
  showCode: () => {},
  hideCode: () => {},
});

export function SidePanelProvider({ children }: { children: ReactNode }) {
  const [codeContent, setCodeContent] = useState<string | null>(null);
  return (
    <sidePanelContext.Provider value={{
      codeContent,
      showCode: setCodeContent,
      hideCode: () => setCodeContent(null),
    }}>
      {children}
    </sidePanelContext.Provider>
  );
}

export const useSidePanel = () => useContext(sidePanelContext);