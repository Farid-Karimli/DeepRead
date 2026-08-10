import { useCallback, useEffect, useState } from 'react';
import { logStudyEvent } from './studyLog.ts';

/**
 * "Show matches by others" is a single preference shared by the paper and code
 * views, independent of each view's match filter. Both views can be mounted at
 * once, so changes are broadcast so the other menu stays in sync.
 */
const SHOW_MATCHES_FROM_OTHERS_STORAGE_KEY = 'deepread.showMatchesFromOthers';
const SHOW_MATCHES_FROM_OTHERS_EVENT = 'deepread:showMatchesFromOthers';

const readStoredShowMatchesFromOthers = (): boolean => {
    if (typeof window === 'undefined') return false;
    return window.localStorage.getItem(SHOW_MATCHES_FROM_OTHERS_STORAGE_KEY) === 'true';
};

export const useShowMatchesFromOthers = (): [boolean, (enabled: boolean) => void] => {
    const [showMatchesFromOthers, setState] = useState(readStoredShowMatchesFromOthers);

    useEffect(() => {
        const handleChange = (event: Event) => {
            setState((event as CustomEvent<boolean>).detail);
        };
        window.addEventListener(SHOW_MATCHES_FROM_OTHERS_EVENT, handleChange);
        return () => window.removeEventListener(SHOW_MATCHES_FROM_OTHERS_EVENT, handleChange);
    }, []);

    const setShowMatchesFromOthers = useCallback((enabled: boolean) => {
        window.localStorage.setItem(SHOW_MATCHES_FROM_OTHERS_STORAGE_KEY, String(enabled));
        logStudyEvent('ui', 'show_matches_from_others_change', { enabled });
        window.dispatchEvent(new CustomEvent(SHOW_MATCHES_FROM_OTHERS_EVENT, { detail: enabled }));
    }, []);

    return [showMatchesFromOthers, setShowMatchesFromOthers];
};
