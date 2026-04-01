/**
 * Convert a PDF.js `getTextContent()` item into a `{ page, top, left, width, height }`
 * box for @allenai/pdf-components overlays.
 *
 * item.width / item.height are already in PDF user-space (points).
 * item.transform[4,5] = (x, y) position in PDF user-space (origin bottom-left, y up).
 *
 * To get overlay coordinates (origin top-left, y down), flip Y with viewport.height.
 * Use scale=1 so computeBoundingBoxStyle can apply user zoom separately.
 */

export type PdfTextItemLike = {
    str: string;
    transform: number[];
    width: number;
    height: number;
};

export type BoundingBoxLike = {
    page: number;
    top: number;
    left: number;
    width: number;
    height: number;
};

export function textItemToBoundingBoxLike(
    item: PdfTextItemLike,
    pageIndexZeroBased: number,
    viewportHeight: number,
): BoundingBoxLike | null {
    if (!item.str?.trim()) {
        return null;
    }

    const x = item.transform[4];
    const y = item.transform[5];
    const width = item.width;
    const fontSize = item.height > 0 ? item.height : Math.abs(item.transform[3]) || 1;

    // (x, y) is the baseline-left of the run. Glyphs extend ~80% of fontSize
    // above the baseline (ascent) and ~20% below (descent). Shift accordingly.
    const ascent = fontSize * 0.8;

    return {
        page: pageIndexZeroBased,
        left: x,
        top: viewportHeight - y - ascent,
        width,
        height: fontSize,
    };
}
