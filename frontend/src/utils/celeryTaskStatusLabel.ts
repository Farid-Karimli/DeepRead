/** Human-readable labels for Celery task polling states. */
export function celeryTaskStatusLabel(
    status: string | undefined,
    submitting = false,
): string {
    if (submitting && !status) {
        return "Submitting match request…";
    }
    switch (status) {
        case "PENDING":
            return "Queued — will start when processing capacity is available";
        case "STARTED":
            return "Matching — finding related code";
        case "RETRY":
            return "Retrying match request…";
        case "FAILURE":
            return "Match request failed";
        default:
            return "Processing match request…";
    }
}
