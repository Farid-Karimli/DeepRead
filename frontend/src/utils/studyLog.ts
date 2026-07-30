const API_URL: string =
  import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

export type StudyLogGroup =
  | "ui"
  | "navigation"
  | "mapping"
  | "copilot"
  | "system";

export type StudyLogEventInput = {
  group: StudyLogGroup;
  event_type: string;
  payload?: Record<string, unknown>;
};

let activeSessionId: string | null = null;
let sessionStartedAtMs: number | null = null;

const pendingEvents: Array<StudyLogEventInput & { session_id: string }> = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;

export function getActiveStudySessionId(): string | null {
  return activeSessionId;
}

export function setActiveStudySessionId(sessionId: string | null): void {
  activeSessionId = sessionId;
  sessionStartedAtMs = sessionId ? Date.now() : null;
}

export async function startStudySession(input: {
  userId: number;
  paperId: string;
  username?: string;
  paperTitle?: string;
}): Promise<string | null> {
  try {
    const response = await fetch(`${API_URL}/study/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: input.userId,
        paper_id: input.paperId,
        username: input.username,
        paper_title: input.paperTitle,
        client_meta: {
          user_agent: navigator.userAgent,
          viewport: {
            width: window.innerWidth,
            height: window.innerHeight,
          },
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        },
      }),
    });
    if (!response.ok) {
      console.warn("Failed to start study session", response.status);
      return null;
    }
    const body: { session_id: string } = await response.json();
    setActiveStudySessionId(body.session_id);
    return body.session_id;
  } catch (error) {
    console.warn("Failed to start study session", error);
    return null;
  }
}

export async function endStudySession(reason = "client_unload"): Promise<void> {
  const sessionId = activeSessionId;
  if (!sessionId) return;
  await flushStudyEvents();
  const durationMs =
    sessionStartedAtMs != null ? Date.now() - sessionStartedAtMs : undefined;
  try {
    await fetch(`${API_URL}/study/sessions/${encodeURIComponent(sessionId)}/end`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason, duration_ms: durationMs }),
    });
  } catch (error) {
    console.warn("Failed to end study session", error);
  } finally {
    setActiveStudySessionId(null);
  }
}

function scheduleFlush(): void {
  if (flushTimer) return;
  flushTimer = setTimeout(() => {
    flushTimer = null;
    void flushStudyEvents();
  }, 400);
}

export function logStudyEvent(
  group: StudyLogGroup,
  event_type: string,
  payload: Record<string, unknown> = {},
): void {
  const sessionId = activeSessionId;
  if (!sessionId) return;
  pendingEvents.push({ session_id: sessionId, group, event_type, payload });
  scheduleFlush();
}

export async function flushStudyEvents(): Promise<void> {
  if (pendingEvents.length === 0) return;
  const batch = pendingEvents.splice(0, pendingEvents.length);
  try {
    await fetch(`${API_URL}/study/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        events: batch.map((event) => ({
          session_id: event.session_id,
          group: event.group,
          event_type: event.event_type,
          payload: event.payload,
          client_timestamp: new Date().toISOString(),
        })),
      }),
    });
  } catch (error) {
    console.warn("Failed to flush study events; re-queueing", error);
    pendingEvents.unshift(...batch);
  }
}

export function matchSourceFromHighlight(box: {
  contextRef?: { type?: string; mapping_type?: string };
  variant?: string;
}): "ai" | "content_to_code" | "code_to_content" | "unknown" {
  const ref = box.contextRef;
  if (ref?.type === "mapping") {
    if (ref.mapping_type === "initial_analysis") return "ai";
    if (ref.mapping_type === "content_to_code") return "content_to_code";
    if (ref.mapping_type === "code_to_content") return "code_to_content";
  }
  if (box.variant === "underline") return "code_to_content";
  return "unknown";
}
