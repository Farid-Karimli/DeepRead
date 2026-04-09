import React, { useEffect, useState } from 'react';
import { listCachedPapers, type cachedPaperSummary } from '../api/main';

interface HomeProps {
    handlePaperSubmit: (e: React.FormEvent<HTMLFormElement>) => void;
    onOpenCachedPaper: (paperId: string) => void;
    errorMessage?: string | null;
}

export default function Home({ handlePaperSubmit, onOpenCachedPaper, errorMessage }: HomeProps) {
    const [papers, setPapers] = useState<cachedPaperSummary[]>([]);
    const [papersLoading, setPapersLoading] = useState(true);
    const [papersError, setPapersError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        setPapersLoading(true);
        setPapersError(null);
        listCachedPapers()
            .then((rows) => {
                console.log(`Found ${rows.length} cached papers`);
                for (const row of rows) {
                    console.log(`Paper ${row.paper_id} has ${row.section_count} sections`);
                }
                if (!cancelled) setPapers(rows);
            })
            .catch(() => {
                if (!cancelled) setPapersError('Could not load saved analyses.');
            })
            .finally(() => {
                if (!cancelled) setPapersLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, []);

    return (
        <>
            <section id="center" className="home-upload">
                <h1 className="home-upload__title">Analyze a Paper with DeepRead</h1>
                <p className="home-upload__lead">Upload a paper to get started.</p>
                {errorMessage ? (
                    <p className="home-upload__alert" role="alert">
                        {errorMessage}
                    </p>
                ) : null}
                <form className="home-upload__form" onSubmit={handlePaperSubmit}>
                    <input
                        className="home-upload__file"
                        type="file"
                        accept=".pdf"
                        name="file"
                        required
                    />
                    <button className="outline-action-btn" type="submit">
                        Analyze
                    </button>
                </form>

                <div className="home-papers">
                    <h2 className="home-papers__title">Computed papers</h2>
                    {papersLoading ? (
                        <p className="home-papers__muted">Loading…</p>
                    ) : papersError ? (
                        <p className="home-papers__muted" role="status">
                            {papersError}
                        </p>
                    ) : papers.length === 0 ? (
                        <p className="home-papers__muted">No analyses in cache yet.</p>
                    ) : (
                        <ul className="home-papers__list">
                            {papers.map((p) => (
                                <li key={p.paper_id} className="home-papers__item">
                                    <button
                                        type="button"
                                        className="home-papers__link"
                                        onClick={() => onOpenCachedPaper(p.paper_id)}
                                    >
                                        <span className="home-papers__label">
                                            {p.label?.trim() || p.paper_id.slice(0, 12) + '…'}
                                        </span>
                                        <span className="home-papers__meta">
                                            {p.section_count} section{p.section_count === 1 ? '' : 's'}
                                            {p.github_repo_url ? ' · repo linked' : ''}
                                        </span>
                                    </button>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            </section>
        </>
    );
}