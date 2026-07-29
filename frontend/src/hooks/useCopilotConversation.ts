import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
    getCopilotConversation,
    sendCopilotMessage,
} from '../api/main.ts';
import type {
    CopilotContextRef,
    CopilotMessage,
} from '../api/types.ts';

const POLL_INTERVAL_MS = 2_000;
const EMPTY_MESSAGES: CopilotMessage[] = [];

export type SendCopilotMessageInput = {
    content: string;
    contextRefs?: CopilotContextRef[];
};

export function useCopilotConversation(
    paperId: string,
    userId?: number,
) {
    const queryClient = useQueryClient();
    const queryKey = ['copilot-conversation', paperId, userId] as const;
    const enabled = Boolean(paperId) && userId !== undefined && userId > 0;

    const conversationQuery = useQuery({
        queryKey,
        queryFn: () => {
            if (!paperId || userId === undefined || userId <= 0) {
                throw new Error('A paper and user are required for Copilot chat.');
            }
            return getCopilotConversation(paperId, userId);
        },
        enabled,
        refetchInterval: (query) =>
            query.state.data?.status === 'processing'
                ? POLL_INTERVAL_MS
                : false,
    });

    const sendMutation = useMutation({
        mutationFn: ({
            content,
            contextRefs = [],
        }: SendCopilotMessageInput) => {
            if (!paperId || userId === undefined || userId <= 0) {
                throw new Error('A paper and user are required for Copilot chat.');
            }
            return sendCopilotMessage(
                paperId,
                userId,
                content,
                contextRefs,
            );
        },
        onSuccess: (response) => {
            queryClient.setQueryData(queryKey, response.conversation);
        },
    });

    const conversation = conversationQuery.data ?? null;

    return {
        conversation,
        messages: conversation?.messages ?? EMPTY_MESSAGES,
        isLoading: conversationQuery.isLoading,
        isSending: sendMutation.isPending,
        error: conversationQuery.error ?? sendMutation.error ?? null,
        sendMessage: sendMutation.mutateAsync,
        refresh: conversationQuery.refetch,
    };
}
