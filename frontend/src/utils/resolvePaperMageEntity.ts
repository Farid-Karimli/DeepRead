import type { PaperMageBox, processPDFResult } from '../api/types.ts';

type EntityRef = {
    entity_id: string;
    entity_type?: string;
    content_type?: string;
    section_id?: string | null;
};

export function resolveEntityType(match: EntityRef): string {
    return match.content_type || match.entity_type || 'section';
}

export function resolvePaperMageEntity(
    processResult: processPDFResult,
    match: EntityRef,
): { box: PaperMageBox; page_index: number } | null {
    const entityType = resolveEntityType(match);

    if (entityType === 'equation') {
        const equation = (processResult.equations ?? []).find(
            (eq) => eq.entity_id === match.entity_id,
        );
        if (equation) {
            return { box: equation.box, page_index: equation.page_index };
        }
    }

    if (entityType === 'sentence') {
        for (const section of processResult.sections) {
            const sentence = (section.sentences ?? []).find(
                (s) => s.entity_id === match.entity_id,
            );
            if (sentence) {
                return { box: sentence.box, page_index: sentence.page_index };
            }
        }
    }

    if (entityType === 'paragraph') {
        for (const section of processResult.sections) {
            const paragraph = (section.paragraphs ?? []).find(
                (p) => p.entity_id === match.entity_id,
            );
            if (paragraph) {
                return { box: paragraph.box, page_index: paragraph.page_index };
            }
        }
    }

    const sectionId = match.section_id || match.entity_id;
    const section = processResult.sections.find((s) => s.entity_id === sectionId);
    if (section) {
        return { box: section.box, page_index: section.page_index };
    }

    return null;
}
