import {
    type FormEvent,
    type KeyboardEvent,
    useContext,
    useEffect,
    useRef,
    useState,
} from 'react';
import {
    IoChatbubbleEllipsesOutline,
    IoChevronBackOutline,
    IoChevronForwardOutline,
    IoCloseOutline,
    IoRefreshOutline,
    IoSendOutline,
    IoTrashOutline,
} from 'react-icons/io5';

import type {
    CopilotContextRef,
    CopilotMessage,
} from '../api/types.ts';
import {
    copilotContextRefKey,
    useCopilotContext,
} from '../context/CopilotContext.tsx';
import { UserContext } from '../context/UserContext.tsx';
import { useCopilotConversation } from '../hooks/useCopilotConversation.ts';
import { formatCopilotContent } from '../utils/formatCopilotContent.tsx';
import { logStudyEvent } from '../utils/studyLog.ts';
import './CopilotChat.css';

type CopilotChatProps = {
    paperId: string;
};

type CopilotDock = 'left' | 'right';

const COPILOT_DOCK_STORAGE_KEY = 'deepread-copilot-dock';

function readStoredDock(): CopilotDock {
    try {
        const value = localStorage.getItem(COPILOT_DOCK_STORAGE_KEY);
        return value === 'left' ? 'left' : 'right';
    } catch {
        return 'right';
    }
}

function messageTime(createdAt: string): string {
    const date = new Date(createdAt);
    if (Number.isNaN(date.getTime())) return '';
    return new Intl.DateTimeFormat(undefined, {
        hour: 'numeric',
        minute: '2-digit',
    }).format(date);
}

function ContextChips({
    refs,
    onRemove,
}: {
    refs: CopilotContextRef[];
    onRemove?: (ref: CopilotContextRef) => void;
}) {
    if (refs.length === 0) return null;

    return (
        <div
            className="copilot-context-chips"
            aria-label={onRemove ? 'Attached context' : 'Message context'}
        >
            {refs.map((ref) => (
                <span
                    className="copilot-context-chip"
                    key={copilotContextRefKey(ref)}
                >
                    <span className="copilot-context-chip__label" title={ref.label}>
                        {ref.label}
                    </span>
                    {onRemove && (
                        <button
                            type="button"
                            className="copilot-context-chip__remove"
                            onClick={() => onRemove(ref)}
                            aria-label={`Remove ${ref.label} from context`}
                        >
                            <IoCloseOutline aria-hidden="true" />
                        </button>
                    )}
                </span>
            ))}
        </div>
    );
}

function Message({ message }: { message: CopilotMessage }) {
    const isUser = message.role === 'user';
    const statusLabel =
        message.status === 'queued' || message.status === 'processing'
            ? 'Sending'
            : message.status === 'failed'
              ? 'Failed'
              : null;

    return (
        <article
            className={`copilot-message copilot-message--${message.role}`}
            aria-label={`${isUser ? 'You' : 'Copilot'} at ${messageTime(message.created_at)}`}
        >
            <div className="copilot-message__meta" aria-hidden="true">
                <span>{isUser ? 'You' : 'Copilot'}</span>
                <time dateTime={message.created_at}>{messageTime(message.created_at)}</time>
            </div>
            <div className="copilot-message__bubble">
                <div className="copilot-message__content">
                    {isUser ? message.content : formatCopilotContent(message.content)}
                </div>
                {message.context_refs.length > 0 && (
                    <ContextChips refs={message.context_refs} />
                )}
                {message.citations.length > 0 && (
                    <div className="copilot-citations" aria-label="Sources">
                        <span className="copilot-citations__label">Sources</span>
                        <ContextChips refs={message.citations} />
                    </div>
                )}
                {statusLabel && (
                    <span
                        className={`copilot-message__status copilot-message__status--${message.status}`}
                    >
                        {statusLabel}
                    </span>
                )}
                {message.status === 'failed' && message.metadata?.error && (
                    <span className="copilot-message__error">
                        {message.metadata.error}
                    </span>
                )}
            </div>
        </article>
    );
}

export default function CopilotChat({ paperId }: CopilotChatProps) {
    const [isOpen, setIsOpen] = useState(false);
    const [dock, setDock] = useState<CopilotDock>(readStoredDock);
    const [draft, setDraft] = useState('');
    const { currentUser } = useContext(UserContext);
    const { contextRefs, removeContext, clearContext } = useCopilotContext();
    const {
        conversation,
        messages,
        isLoading,
        isSending,
        error,
        sendMessage,
        refresh,
    } = useCopilotConversation(paperId, currentUser?.id);
    const transcriptRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    const isProcessing = conversation?.status === 'processing';
    const isBusy = isSending || isProcessing;
    const canSend =
        Boolean(currentUser) && Boolean(draft.trim()) && !isBusy;

    useEffect(() => {
        if (!isOpen) return;
        textareaRef.current?.focus();
    }, [isOpen]);

    useEffect(() => {
        if (!isOpen) return;
        const transcript = transcriptRef.current;
        transcript?.scrollTo({
            top: transcript.scrollHeight,
            behavior: 'smooth',
        });
    }, [isOpen, messages.length, isProcessing]);

    useEffect(() => {
        if (!isOpen) return;
        const closeOnEscape = (event: globalThis.KeyboardEvent) => {
            if (event.key === 'Escape') setIsOpen(false);
        };
        window.addEventListener('keydown', closeOnEscape);
        return () => window.removeEventListener('keydown', closeOnEscape);
    }, [isOpen]);

    const submitMessage = async (event?: FormEvent) => {
        event?.preventDefault();
        const content = draft.trim();
        if (!currentUser || !content || isBusy) return;

        try {
            logStudyEvent('copilot', 'user_message_send', {
                content,
                context_refs: contextRefs,
            });
            await sendMessage({ content, contextRefs });
            setDraft('');
            clearContext();
        } catch {
            // The hook exposes the request error; keep the draft and context
            // intact so the user can retry without reconstructing the prompt.
        }
    };

    const moveDock = (next: CopilotDock) => {
        logStudyEvent('ui', 'copilot_dock_change', { dock: next });
        setDock(next);
        try {
            localStorage.setItem(COPILOT_DOCK_STORAGE_KEY, next);
        } catch {
            // Ignore private-mode or quota errors; position still updates for this session.
        }
    };

    const handleComposerKeyDown = (
        event: KeyboardEvent<HTMLTextAreaElement>,
    ) => {
        if (
            event.key === 'Enter' &&
            !event.shiftKey &&
            !event.nativeEvent.isComposing
        ) {
            event.preventDefault();
            void submitMessage();
        }
    };

    return (
        <aside
            className={`copilot-chat copilot-chat--${dock}`}
            aria-label="DeepRead Copilot"
        >
            {isOpen && (
                <section
                    id="copilot-chat-panel"
                    className="copilot-panel"
                    aria-label="DeepRead Copilot conversation"
                >
                    <header className="copilot-panel__header">
                        <div>
                            <h2>DeepRead Copilot</h2>
                            <p>Ask about this paper and its code</p>
                        </div>
                        <button
                            type="button"
                            className="copilot-icon-button"
                            onClick={() => setIsOpen(false)}
                            aria-label="Close Copilot"
                        >
                            <IoCloseOutline aria-hidden="true" />
                        </button>
                    </header>

                    <div
                        className="copilot-transcript"
                        ref={transcriptRef}
                        role="log"
                        aria-live="polite"
                        aria-relevant="additions text"
                    >
                        {!currentUser ? (
                            <div className="copilot-empty-state">
                                <IoChatbubbleEllipsesOutline aria-hidden="true" />
                                <h3>Choose a user to start chatting</h3>
                                <p>
                                    Conversations are saved separately for each
                                    user and paper.
                                </p>
                            </div>
                        ) : isLoading ? (
                            <div className="copilot-loading" role="status">
                                Loading conversation…
                            </div>
                        ) : messages.length === 0 ? (
                            <div className="copilot-empty-state">
                                <IoChatbubbleEllipsesOutline aria-hidden="true" />
                                <h3>Explore the paper with Copilot</h3>
                                <p>
                                    Ask a question, or attach a match from the
                                    paper or repository for focused context.
                                </p>
                            </div>
                        ) : (
                            messages.map((message) => (
                                <Message message={message} key={message.id} />
                            ))
                        )}

                        {isProcessing && (
                            <div
                                className="copilot-thinking"
                                role="status"
                                aria-label="Copilot is working"
                            >
                                <span />
                                <span />
                                <span />
                            </div>
                        )}
                    </div>

                    {(error || conversation?.status === 'failed') && (
                        <div className="copilot-error" role="alert">
                            <div>
                                <strong>Copilot hit a snag.</strong>
                                <span>
                                    {error?.message ??
                                        'Your message is saved. You can try again.'}
                                </span>
                            </div>
                            <button type="button" onClick={() => void refresh()}>
                                <IoRefreshOutline aria-hidden="true" />
                                Refresh
                            </button>
                        </div>
                    )}

                    <form className="copilot-composer" onSubmit={submitMessage}>
                        {contextRefs.length > 0 && (
                            <div className="copilot-attachments">
                                <div className="copilot-attachments__heading">
                                    <span>
                                        Context ({contextRefs.length})
                                    </span>
                                    <button
                                        type="button"
                                        onClick={clearContext}
                                    >
                                        <IoTrashOutline aria-hidden="true" />
                                        Clear
                                    </button>
                                </div>
                                <ContextChips
                                    refs={contextRefs}
                                    onRemove={removeContext}
                                />
                            </div>
                        )}
                        <div className="copilot-composer__row">
                            <textarea
                                ref={textareaRef}
                                value={draft}
                                onChange={(event) => setDraft(event.target.value)}
                                onKeyDown={handleComposerKeyDown}
                                placeholder={
                                    currentUser
                                        ? 'Ask about the paper or code…'
                                        : 'Choose a user to enable chat'
                                }
                                aria-label="Message Copilot"
                                maxLength={20_000}
                                rows={2}
                                disabled={!currentUser}
                            />
                            <button
                                type="submit"
                                className="copilot-send-button"
                                disabled={!canSend}
                                aria-label={
                                    isBusy
                                        ? 'Copilot is working'
                                        : 'Send message'
                                }
                            >
                                <IoSendOutline aria-hidden="true" />
                            </button>
                        </div>
                        <p className="copilot-composer__hint">
                            {currentUser
                                ? 'Enter to send · Shift+Enter for a new line'
                                : 'Select or create a user from the user menu first.'}
                        </p>
                    </form>
                </section>
            )}

            <div className="copilot-launcher-row">
                {dock === 'right' && (
                    <button
                        type="button"
                        className="copilot-dock-button"
                        onClick={() => moveDock('left')}
                        aria-label="Move Copilot to bottom left"
                        title="Move to bottom left"
                    >
                        <IoChevronBackOutline aria-hidden="true" />
                    </button>
                )}
                <button
                    type="button"
                    className="copilot-launcher"
                    onClick={() => {
                        const nextOpen = !isOpen;
                        logStudyEvent('ui', 'copilot_panel_toggle', { open: nextOpen });
                        setIsOpen(nextOpen);
                    }}
                    aria-expanded={isOpen}
                    aria-controls="copilot-chat-panel"
                    aria-label={
                        isOpen
                            ? 'Close Copilot'
                            : `Open Copilot${
                                  contextRefs.length > 0
                                      ? `, ${contextRefs.length} context ${
                                            contextRefs.length === 1
                                                ? 'item'
                                                : 'items'
                                        } attached`
                                      : ''
                              }`
                    }
                    title={isOpen ? 'Close Copilot' : 'Open Copilot'}
                >
                    {isOpen ? (
                        <IoCloseOutline aria-hidden="true" />
                    ) : (
                        <IoChatbubbleEllipsesOutline aria-hidden="true" />
                    )}
                    {!isOpen && contextRefs.length > 0 && (
                        <span
                            className="copilot-launcher__badge"
                            aria-hidden="true"
                        >
                            {contextRefs.length > 9 ? '9+' : contextRefs.length}
                        </span>
                    )}
                </button>
                {dock === 'left' && (
                    <button
                        type="button"
                        className="copilot-dock-button"
                        onClick={() => moveDock('right')}
                        aria-label="Move Copilot to bottom right"
                        title="Move to bottom right"
                    >
                        <IoChevronForwardOutline aria-hidden="true" />
                    </button>
                )}
            </div>
        </aside>
    );
}
