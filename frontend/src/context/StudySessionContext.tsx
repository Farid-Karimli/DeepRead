import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import {
  endStudySession,
  flushStudyEvents,
  getActiveStudySessionId,
  logStudyEvent,
  startStudySession,
} from "../utils/studyLog.ts";

type StudySessionContextValue = {
  sessionId: string | null;
};

const StudySessionContext = createContext<StudySessionContextValue>({
  sessionId: null,
});

export function StudySessionProvider({
  children,
  paperId,
  userId,
  username,
  paperTitle,
}: {
  children: ReactNode;
  paperId: string;
  userId: number | undefined;
  username?: string;
  paperTitle?: string;
}) {
  const [sessionId, setSessionId] = useState<string | null>(null);

  useEffect(() => {
    if (!userId || userId <= 0) return;

    let cancelled = false;
    void (async () => {
      const id = await startStudySession({
        userId,
        paperId,
        username,
        paperTitle,
      });
      if (cancelled) return;
      setSessionId(id);
      if (id) {
        logStudyEvent('navigation', 'paper_session_begin', {
          paper_id: paperId,
          paper_title: paperTitle,
          user_id: userId,
        });
      }
    })();

    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        void flushStudyEvents();
      }
    };
    const onUnload = () => {
      void endStudySession("page_unload");
    };

    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", onUnload);

    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", onUnload);
      void endStudySession("paper_view_unmount");
      setSessionId(null);
    };
  }, [paperId, userId, username, paperTitle]);

  const valueSessionId = sessionId ?? getActiveStudySessionId();

  return (
    <StudySessionContext.Provider value={{ sessionId: valueSessionId }}>
      {children}
    </StudySessionContext.Provider>
  );
}

export function useStudySession(): StudySessionContextValue {
  return useContext(StudySessionContext);
}
