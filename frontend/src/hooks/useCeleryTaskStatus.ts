import { useQuery } from '@tanstack/react-query';

import { getTaskStatus } from '../api/main.ts';

const TERMINAL_STATUSES = new Set(['SUCCESS', 'FAILURE']);

type UseCeleryTaskStatusOptions = {
    /** React Query cache key prefix (default: `task`). */
    queryKey?: string;
    pollIntervalMs?: number;
};

/**
 * Poll `/tasks/{taskId}` until Celery reports SUCCESS or FAILURE.
 * Shared by content→code (PaperView) and code→content (RepoView) flows.
 */
export function useCeleryTaskStatus(
    taskId: string | null,
    options: UseCeleryTaskStatusOptions = {},
) {
    const queryKey = options.queryKey ?? 'task';
    const pollIntervalMs = options.pollIntervalMs ?? 10_000;

    return useQuery({
        queryKey: [queryKey, taskId],
        queryFn: () => {
            if (!taskId) throw new Error('No task ID set.');
            return getTaskStatus(taskId);
        },
        enabled: Boolean(taskId),
        refetchInterval: (query) => {
            const status = query.state.data?.status;
            return status && TERMINAL_STATUSES.has(status) ? false : pollIntervalMs;
        },
    });
}
