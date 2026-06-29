import React, { useContext, useState, useEffect, useRef, useMemo } from 'react';
import {useQuery} from '@tanstack/react-query';
import { IoPersonCircleOutline, IoGridOutline, IoListOutline, IoDocumentOutline, IoSearchOutline } from 'react-icons/io5';

import { getAvailPapers, getUserByUsername } from '../api/main';
import type { PaperMetadataSummary } from '../api/types';
import { UserContext } from '../context/userContext';
interface HomeProps {
    handlePaperSubmit: (e: React.FormEvent<HTMLFormElement>) => void;
    onOpenCachedPaper: (paperId: string) => void;
    errorMessage?: string | null;
}

type PaperViewMode = 'card' | 'list';

function getPaperTitle(paper: PaperMetadataSummary): string {
    return paper.paper_title?.trim() || paper.label?.trim() || paper.paper_id;
}

export default function Home({ onOpenCachedPaper }: HomeProps) {
    const papersQuery = useQuery({
        queryKey: ['paperRecords'],
        queryFn: getAvailPapers
    })

    const {currentUser, setUser} = useContext(UserContext);
    const [pendingUserName, setPendingUserName] = useState('');
    const [submittedUsername, setSubmittedUsername] = useState<string | null>(null);
    const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
    const [paperView, setPaperView] = useState<PaperViewMode>('card');
    const [isSearchOpen, setIsSearchOpen] = useState(false);
    const [paperSearch, setPaperSearch] = useState('');
    const userMenuRef = useRef<HTMLDivElement>(null);
    const searchInputRef = useRef<HTMLInputElement>(null);

    const userQuery = useQuery({
        queryKey: ['users', submittedUsername],
        queryFn: () => getUserByUsername(submittedUsername!),
        enabled: submittedUsername !== null,
    })

    useEffect(()=>{
        if (userQuery.data) {
            const user = userQuery.data;
            setUser(user)
            localStorage.setItem('user', JSON.stringify(user))
        }
    }, [userQuery.data, submittedUsername])

    useEffect(() => {
        if (!isUserMenuOpen) return;
        const handleClickOutside = (event: MouseEvent) => {
            if (userMenuRef.current && !userMenuRef.current.contains(event.target as Node)) {
                setIsUserMenuOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [isUserMenuOpen]);

    useEffect(() => {
        if (isSearchOpen) {
            searchInputRef.current?.focus();
        }
    }, [isSearchOpen]);

    const filteredPapers = useMemo(() => {
        const papers = papersQuery.data?.papers ?? [];
        const query = paperSearch.trim().toLowerCase();
        if (!query) return papers;
        return papers.filter((p) => getPaperTitle(p).toLowerCase().includes(query));
    }, [papersQuery.data, paperSearch]);

    const handleLogout = () => {
        setPendingUserName('');
        setSubmittedUsername(null);
        setUser(null);
        localStorage.removeItem('user');
        setIsUserMenuOpen(false);
    };

    return (
        <>
            <div className="home-top-bar">
                <div className="user-menu" ref={userMenuRef}>
                    <button
                        type="button"
                        className="user-menu__toggle"
                        aria-label="Account"
                        aria-haspopup="true"
                        aria-expanded={isUserMenuOpen}
                        onClick={() => setIsUserMenuOpen((open) => !open)}
                    >
                        <IoPersonCircleOutline aria-hidden />
                    </button>
                    {isUserMenuOpen ? (
                        <div className="user-menu__panel user-login">
                            {currentUser === null ? (
                                <>
                                    <h2 className="user-login__title">Choose a username</h2>
                                    <form
                                        className="user-login__form"
                                        onSubmit={(e) => {
                                            e.preventDefault();
                                            setSubmittedUsername(pendingUserName);
                                        }}
                                    >
                                        <input
                                            id="username"
                                            className="user-login__input"
                                            type="text"
                                            name="username"
                                            placeholder="your username"
                                            onChange={(e) => setPendingUserName(e.target.value)}
                                        />
                                        <button className="outline-action-btn" type="submit">
                                            Submit
                                        </button>
                                    </form>
                                </>
                            ) : (
                                <div className="user-login__welcome">
                                    <h2>Welcome back, {currentUser.username}</h2>
                                    <button className="outline-action-btn" type="button" onClick={handleLogout}>
                                        Log out
                                    </button>
                                </div>
                            )}
                        </div>
                    ) : null}
                </div>
            </div>
            <section id="center">
                <h1 className="home-upload__title">Analyze a Paper with DeepRead</h1>
                <div className="home-papers">
                    <div className="home-papers__header">
                        <div className="home-papers__title-row">
                            <h2 className="home-papers__title">Available papers</h2>
                            <div className="home-papers__search">
                                {isSearchOpen ? (
                                    <input
                                        ref={searchInputRef}
                                        type="search"
                                        className="home-papers__search-input"
                                        placeholder="Search titles…"
                                        value={paperSearch}
                                        onChange={(e) => setPaperSearch(e.target.value)}
                                        aria-label="Search paper titles"
                                    />
                                ) : null}
                                <button
                                    type="button"
                                    className={`home-papers__search-btn${isSearchOpen ? ' home-papers__search-btn--active' : ''}`}
                                    aria-label={isSearchOpen ? 'Close search' : 'Search paper titles'}
                                    aria-expanded={isSearchOpen}
                                    onClick={() => {
                                        setIsSearchOpen((open) => {
                                            if (open) setPaperSearch('');
                                            return !open;
                                        });
                                    }}
                                >
                                    <IoSearchOutline aria-hidden />
                                </button>
                            </div>
                        </div>
                        <div className="home-papers__view-toggle" role="group" aria-label="Paper layout">
                            <button
                                type="button"
                                className={`home-papers__view-btn${paperView === 'card' ? ' home-papers__view-btn--active' : ''}`}
                                aria-label="Card view"
                                aria-pressed={paperView === 'card'}
                                onClick={() => setPaperView('card')}
                            >
                                <IoGridOutline aria-hidden />
                            </button>
                            <button
                                type="button"
                                className={`home-papers__view-btn${paperView === 'list' ? ' home-papers__view-btn--active' : ''}`}
                                aria-label="List view"
                                aria-pressed={paperView === 'list'}
                                onClick={() => setPaperView('list')}
                            >
                                <IoListOutline aria-hidden />
                            </button>
                        </div>
                    </div>
                    {papersQuery.isPending ? (
                        <p className="home-papers__muted">Loading…</p>
                    ) : papersQuery.error ? (
                        <p className="home-papers__muted" role="status">
                            {papersQuery.error.message}
                        </p>
                    ) : papersQuery.data.papers.length === 0 ? (
                        <p className="home-papers__muted">No analyses in cache yet.</p>
                    ) : filteredPapers.length === 0 ? (
                        <p className="home-papers__muted">No papers match your search.</p>
                    ) : (
                        <ul className={`home-papers__list home-papers__list--${paperView}`}>
                            {filteredPapers.map((p) => (
                                <li key={p.paper_id} className="home-papers__item">
                                    <button
                                        type="button"
                                        className="home-papers__link"
                                        onClick={() => onOpenCachedPaper(p.paper_id)}
                                    >
                                        <div className="home-papers__thumb" aria-hidden>
                                            <IoDocumentOutline />
                                        </div>
                                        <div className="home-papers__body">
                                            <span className="home-papers__label">
                                                {getPaperTitle(p)}
                                            </span>
                                            <span className="home-papers__meta">
                                                {p.section_count} section{p.section_count === 1 ? '' : 's'}
                                                {p.github_repo_url ? ' · repo linked' : ''}
                                            </span>
                                        </div>
                                    </button>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>

                {/* Upload section disabled for now
                <p className="home-upload__lead">OR</p>

                <div className="home-upload">
                    <p className="home-upload__lead">To start a new analysis, provide a link to or upload a PDF file.</p>
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
                </div>
                */}
            </section>
        </>
    );
}