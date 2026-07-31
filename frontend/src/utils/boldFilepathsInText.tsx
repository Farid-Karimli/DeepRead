import { Fragment, type ReactNode } from 'react';

function escapeRegExp(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

const GENERIC_PATH_RE = /\b((?:[\w.-]+\/)+[\w.-]+\.\w+)\b/g;
const GENERIC_PATH_TEST = /^(?:[\w.-]+\/)+[\w.-]+\.\w+$/;

/** Bold repo filepaths mentioned in mapping reasoning (snippet paths + generic path-like tokens). */
export function boldFilepathsInText(text: string, filepaths: string[] = []): ReactNode {
    const paths = [...new Set(filepaths.filter(Boolean))].sort((a, b) => b.length - a.length);
    const pattern =
        paths.length > 0
            ? new RegExp(`(${paths.map(escapeRegExp).join('|')})`, 'g')
            : GENERIC_PATH_RE;

    const parts = text.split(pattern).filter((part) => part.length > 0);
    const pathSet = new Set(paths);

    return parts.map((part, index) => {
        const isPath = pathSet.has(part) || (paths.length === 0 && GENERIC_PATH_TEST.test(part));
        if (isPath) {
            return <strong key={index}>{part}</strong>;
        }
        return <Fragment key={index}>{part}</Fragment>;
    });
}
