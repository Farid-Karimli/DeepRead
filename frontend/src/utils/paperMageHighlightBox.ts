import type { PaperMageBox } from '../api/types.ts';

/**
 * Max normalized width/height for a single-line / single-column highlight.
 * Boxes above these usually mean PaperMage merged tokens across columns or pages
 * (see token-union boxes in process_pdf), not the span the agent intended.
 */
export const PAPERMAGE_HIGHLIGHT_MAX_WIDTH = 0.55;
export const PAPERMAGE_HIGHLIGHT_MAX_HEIGHT = 0.12;

export type PaperMageBoxLike = Pick<PaperMageBox, 'l' | 't' | 'w' | 'h'>;

export function isPlausiblePaperMageHighlightBox(box: PaperMageBoxLike): boolean {
    const { w, h, l, t } = box;
    if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) {
        return false;
    }
    if (w > PAPERMAGE_HIGHLIGHT_MAX_WIDTH || h > PAPERMAGE_HIGHLIGHT_MAX_HEIGHT) {
        return false;
    }
    if (l < 0 || t < 0 || l + w > 1.001 || t + h > 1.001) {
        return false;
    }
    return true;
}
