import React from 'react';
import {useQuery} from '@tanstack/react-query';

import { getAvailPapers } from '../api/main';

interface HomeProps {
    handlePaperSubmit: (e: React.FormEvent<HTMLFormElement>) => void;
    onOpenCachedPaper: (paperId: string) => void;
    errorMessage?: string | null;
}

export default function Home({ handlePaperSubmit, onOpenCachedPaper, errorMessage }: HomeProps) {
    const papersQuery = useQuery({
        queryKey: ['paperRecords'],
        queryFn: getAvailPapers
    })

    return (
        <>
            <section id="center" className="home-upload">
                <h1 className="home-upload__title">Analyze a Paper with DeepRead</h1>
                <p className="home-upload__lead">Upload file or provide a link to get started.</p>
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
                    />
                    <input
                        className="home-upload__file"
                        type="text"
                        name="link"
                        placeholder="https://..."
                    />
                    <button className="outline-action-btn" type="submit">
                        Analyze
                    </button>
                </form>

                <div className="home-papers">
                    <h2 className="home-papers__title">Computed papers</h2>
                    {papersQuery.isPending ? (
                        <p className="home-papers__muted">Loading…</p>
                    ) : papersQuery.error ? (
                        <p className="home-papers__muted" role="status">
                            {papersQuery.error.message}
                        </p>
                    ) : papersQuery.data.papers.length === 0 ? (
                        <p className="home-papers__muted">No analyses in cache yet.</p>
                    ) : (
                        <ul className="home-papers__list">
                            {papersQuery.data.papers.map((p) => (
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