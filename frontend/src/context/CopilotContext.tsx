/* eslint-disable react-refresh/only-export-components */
import {
    createContext,
    useCallback,
    useContext,
    useMemo,
    useState,
    type ReactNode,
} from 'react';

import type { CopilotContextRef } from '../api/types.ts';

type CopilotContextValue = {
    contextRefs: CopilotContextRef[];
    addContext: (ref: CopilotContextRef) => void;
    removeContext: (ref: CopilotContextRef) => void;
    clearContext: () => void;
};

const CopilotContext = createContext<CopilotContextValue | null>(null);

/**
 * Stable client-side identity for attachments. The backend resolves the full
 * content from these references, so the UI only needs to retain canonical IDs.
 */
export function copilotContextRefKey(ref: CopilotContextRef): string {
    switch (ref.type) {
        case 'paper_entity':
            return `paper:${ref.entity_type}:${ref.entity_id}`;
        case 'code_range':
            return `code:${ref.filepath}:${ref.start_line}-${ref.end_line}`;
        case 'mapping':
            if (ref.cache_key) {
                return `mapping:${ref.mapping_type}:${ref.cache_key}`;
            }
            return [
                'mapping',
                ref.mapping_type,
                ref.entity_id ?? '',
                ref.filepath ?? '',
                ref.start_line ?? '',
                ref.end_line ?? '',
            ].join(':');
    }
}

export function CopilotProvider({
    children,
}: {
    children: ReactNode;
}) {
    const [contextRefs, setContextRefs] = useState<CopilotContextRef[]>([]);

    const addContext = useCallback((ref: CopilotContextRef) => {
        const key = copilotContextRefKey(ref);
        setContextRefs((current) => (
            current.some((item) => copilotContextRefKey(item) === key)
                ? current
                : [...current, ref]
        ));
    }, []);

    const removeContext = useCallback((ref: CopilotContextRef) => {
        const key = copilotContextRefKey(ref);
        setContextRefs((current) => (
            current.filter((item) => copilotContextRefKey(item) !== key)
        ));
    }, []);

    const clearContext = useCallback(() => {
        setContextRefs([]);
    }, []);

    const value = useMemo(
        () => ({ contextRefs, addContext, removeContext, clearContext }),
        [contextRefs, addContext, removeContext, clearContext],
    );

    return (
        <CopilotContext.Provider value={value}>
            {children}
        </CopilotContext.Provider>
    );
}

export function useCopilotContext(): CopilotContextValue {
    const value = useContext(CopilotContext);
    if (!value) {
        throw new Error('useCopilotContext must be used inside CopilotProvider');
    }
    return value;
}
