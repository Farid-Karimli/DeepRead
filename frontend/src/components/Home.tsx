import React, { useContext, useState, useEffect } from 'react';
import {useQuery} from '@tanstack/react-query';

import { getAvailPapers, getUserByUsername } from '../api/main';
import { UserContext } from '../context/UserContext';

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

    const {currentUser, setUser} = useContext(UserContext);
    const [pendingUserName, setPendingUserName] = useState('');
    const [submittedUsername, setSubmittedUsername] = useState<string | null>(null);

    const userQuery = useQuery({
        queryKey: ['users', submittedUsername],
        queryFn: () => getUserByUsername(submittedUsername!),
        enabled: submittedUsername !== null,
    })

    useEffect(()=>{
        if (userQuery.data) {
            const user = userQuery.data;
            console.log(user);
            setUser(user)
            localStorage.setItem('user', JSON.stringify(user))
        }
    }, [userQuery.data, submittedUsername])

    const handleLogout = () => {
        setPendingUserName('');
        setSubmittedUsername(null);
        setUser(null);
        localStorage.removeItem('user');
    };

    return (
        <>
            <section id="center">
                <h1 className="home-upload__title">Analyze a Paper with DeepRead</h1>
                <div className="user-login">
                    {currentUser === null ? <><h2 className="user-login__title">Choose a username</h2>
                        <form className="user-login__form" onSubmit={(e)=>{
                            e.preventDefault();
                            setSubmittedUsername(pendingUserName);
                        }}>
                            <input
                                id="username"
                                className="user-login__input"
                                type="text"
                                name="username"
                                placeholder="your username"
                                onChange={e => setPendingUserName(e.target.value)}
                            />
                            <button className="outline-action-btn" type="submit">
                                Submit
                            </button>
                        </form></> 
                        : 
                        <div className="user-login__welcome">
                            <h2>Welcome back, {currentUser.username}</h2>
                            <p>Pick an available paper or start a new analysis below.</p>
                            <button className="outline-action-btn" type="button" onClick={handleLogout}>
                                Log out
                            </button>
                        </div>
                    }
                </div>
                <div className="home-papers">
                    <h2 className="home-papers__title">Available papers</h2>
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
            </section>
        </>
    );
}