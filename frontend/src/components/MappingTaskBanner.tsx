import { celeryTaskStatusLabel } from "../utils/celeryTaskStatusLabel.ts";

type MappingTaskBannerProps = {
    visible: boolean;
    status?: string;
    submitting?: boolean;
    direction?: "content_to_code" | "code_to_content";
};

export default function MappingTaskBanner({
    visible,
    status,
    submitting = false,
    direction = "content_to_code",
}: MappingTaskBannerProps) {
    if (!visible) {
        return null;
    }

    const directionLabel =
        direction === "code_to_content"
            ? "Code → paper"
            : "Paper → code";

    return (
        <div className="mapping-task-banner" role="status" aria-live="polite">
            <span className="mapping-task-banner__direction">{directionLabel}</span>
            <span className="mapping-task-banner__message">
                {celeryTaskStatusLabel(status, submitting)}
            </span>
        </div>
    );
}
