export type LineRange = { start: number; end: number };

export function dedupeRanges(ranges: LineRange[]): LineRange[] {
    const seen = new Set<string>();
    return ranges.filter(({ start, end }) => {
        const key = `${start}:${end}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    });
}
