/**
 * Map a DOM text selection inside @allenai/pdf-components to page index and
 * normalized box coordinates (PaperMage-style l/t/w/h in 0–1 page space).
 *
 * Pages are `.pdf-reader__page` elements with `data-page-number` (1-based).
 * Overlay code denormalizes with viewport × pageDimensions scaling.
 */

const PAGE_SELECTOR = '.pdf-reader__page';
const PAGE_NUMBER_ATTR = 'data-page-number';

export type NormalizedPageBox = {
    l: number;
    t: number;
    w: number;
    h: number;
};

export type SelectionPageBox = {
    /** Zero-based page index (matches PageWrapper pageIndex / overlay `page`). */
    page: number;
    box: NormalizedPageBox;
};

function nodeToElement(node: Node): HTMLElement | null {
    if (node.nodeType === Node.ELEMENT_NODE) {
        return node as HTMLElement;
    }
    if (node.nodeType === Node.TEXT_NODE) {
        return node.parentElement;
    }
    return null;
}

export function getPageElementFromRange(
    range: Range,
    endpoint: 'start' | 'end' = 'start',
): HTMLElement | null {
    const container = endpoint === 'start' ? range.startContainer : range.endContainer;
    const el = nodeToElement(container);
    return (el?.closest(PAGE_SELECTOR) as HTMLElement | null) ?? null;
}

export function getPageIndexFromPageElement(pageEl: HTMLElement): number | null {
    const pageNumber = parseInt(pageEl.getAttribute(PAGE_NUMBER_ATTR) ?? '', 10);
    if (!Number.isFinite(pageNumber) || pageNumber < 1) {
        return null;
    }
    return pageNumber - 1;
}

/** Zero-based page index for the given range endpoint. */
export function getPageIndexFromRange(
    range: Range,
    endpoint: 'start' | 'end' = 'start',
): number | null {
    const pageEl = getPageElementFromRange(range, endpoint);
    if (!pageEl) {
        return null;
    }
    return getPageIndexFromPageElement(pageEl);
}

export function normalizeClientRectToPageBox(
    selRect: DOMRect,
    pageRect: DOMRect,
): NormalizedPageBox {
    return {
        l: (selRect.left - pageRect.left) / pageRect.width,
        t: (selRect.top - pageRect.top) / pageRect.height,
        w: selRect.width / pageRect.width,
        h: selRect.height / pageRect.height,
    };
}

function getPageElementForClientRect(rect: DOMRect): HTMLElement | null {
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const stack = document.elementsFromPoint(cx, cy);
    for (const el of stack) {
        if (el instanceof HTMLElement && el.classList.contains('pdf-reader__page')) {
            return el;
        }
        if (el instanceof HTMLElement) {
            const page = el.closest(PAGE_SELECTOR);
            if (page instanceof HTMLElement) {
                return page;
            }
        }
    }
    return null;
}

/**
 * Snapshot a Range into one normalized box per client rect (multi-line selections
 * produce multiple entries). Each rect is mapped to the page under its center point.
 */
export function captureSelectionHighlightsFromRange(range: Range): SelectionPageBox[] {
    const rects = Array.from(range.getClientRects()).filter((r) => r.width > 0 && r.height > 0);
    if (rects.length === 0) {
        const fallback = range.getBoundingClientRect();
        if (fallback.width > 0 || fallback.height > 0) {
            rects.push(fallback);
        }
    }

    const highlights: SelectionPageBox[] = [];
    for (const rect of rects) {
        const pageEl = getPageElementForClientRect(rect) ?? getPageElementFromRange(range);
        if (!pageEl) {
            continue;
        }
        const page = getPageIndexFromPageElement(pageEl);
        if (page == null) {
            continue;
        }
        highlights.push({
            page,
            box: normalizeClientRectToPageBox(rect, pageEl.getBoundingClientRect()),
        });
    }
    return highlights;
}
