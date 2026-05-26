import { HighlightOverlayDemo, type BoundingBoxWithTooltip } from './../components/CodeOverlay.tsx';
import { type codeSectionsResult, type githubRepoTreeResponse } from '../api/main.ts';
import type PDFDocumentProxy from '@allenai/pdf-components';
import type { PdfTextItemLike } from './pdfTextItemToBoundingBox.ts';
import { textItemToBoundingBoxLike } from './pdfTextItemToBoundingBox.ts';
 
const sectionToBBoxBruteForce = async (
    analysisResult: codeSectionsResult,
    numPages: number,
    pdfDocProxy: typeof PDFDocumentProxy,
    rotation: number,
    pageDimensions: { width: number, height: number },
    cancelled: boolean,
    setHitBoxes: (boxes: BoundingBoxWithTooltip[]) => void,
) => {
    const next: BoundingBoxWithTooltip[] = [];
    let hitSeq = 0;

    // Normalize a string for matching: strip whitespace and lowercase
    const normalize = (s: string) => s.replace(/\s+/g, '').toLowerCase();

    // Build (normalizedName, sectionName) pairs once
    const targets = analysisResult.sections.map((section) => ({
        section,
        needle: normalize(section.section_header),
    })).filter(t => t.needle.length > 0);

    // Track which sections have been matched (by index) so we skip them on later pages
    const matched = new Set<number>();

    for (let pageNum = 1; pageNum <= numPages; pageNum++) {
        if (cancelled) return;
        if (matched.size === targets.length) break;

        // @ts-ignore
        const page = await pdfDocProxy.getPage(pageNum);
        const pageText = await page.getTextContent();
        const viewport = page.getViewport({ scale: 1, rotation });

        const scaleX = pageDimensions.width / viewport.width;
        const scaleY = pageDimensions.height / viewport.height;
        const pageIndexZeroBased = pageNum - 1;

        // Collect only text items (not TextMarkedContent)
        const items = pageText.items.filter((it: object): it is PdfTextItemLike => 'str' in it);

        // Build flat string and char→item index map
        let flatStr = '';
        const charToItem: number[] = [];
        for (let idx = 0; idx < items.length; idx++) {
            const str = items[idx].str;
            for (let c = 0; c < str.length; c++) {
                charToItem.push(idx);
            }
            flatStr += str;
        }

        // Build normalized flat string and normChar→origChar map (strip whitespace, lowercase)
        const normToOrig: number[] = [];
        let normalizedFlat = '';
        for (let c = 0; c < flatStr.length; c++) {
            if (!/\s/.test(flatStr[c])) {
                normToOrig.push(c);
                normalizedFlat += flatStr[c].toLowerCase();
            }
        }

        for (let ti = 0; ti < targets.length; ti++) {
            if (matched.has(ti)) continue;
            const { section, needle } = targets[ti];

            const pos = normalizedFlat.indexOf(needle);
            if (pos === -1) continue;

            matched.add(ti);

            const startOrigChar = normToOrig[pos];
            const endOrigChar   = normToOrig[pos + needle.length - 1];
            const startItemIdx  = charToItem[startOrigChar];
            const endItemIdx    = charToItem[endOrigChar];

            // Union bounding boxes across the matched item span
            let unionLeft   = Infinity;
            let unionTop    = Infinity;
            let unionRight  = -Infinity;
            let unionBottom = -Infinity;

            for (let idx = startItemIdx; idx <= endItemIdx; idx++) {
                const box = textItemToBoundingBoxLike(items[idx], pageIndexZeroBased, viewport.height);
                if (!box) continue;
                unionLeft   = Math.min(unionLeft,   box.left);
                unionTop    = Math.min(unionTop,    box.top);
                unionRight  = Math.max(unionRight,  box.left + box.width);
                unionBottom = Math.max(unionBottom, box.top  + box.height);
            }

            if (!isFinite(unionLeft)) continue;

            next.push({
                page: pageIndexZeroBased,
                top:    unionTop    * scaleY - 5,
                left:   unionLeft   * scaleX,
                width:  (unionRight  - unionLeft)   * scaleX,
                height: (unionBottom - unionTop)    * scaleY * 1.5,
                hitKey: `p${pageIndexZeroBased}-h${hitSeq++}`,
                file_infos: section.code_snippets.map((snippet) => `${snippet.filepath}:${snippet.start_line}-${snippet.end_line}`),
                code_snippets: section.code_snippets,
                description: section.section_description,
            });
        }
    }
    if (!cancelled) {
        setHitBoxes(next);
    }
};

export default sectionToBBoxBruteForce;