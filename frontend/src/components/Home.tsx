import React from 'react';

interface HomeProps {
    handlePaperSubmit: (e: React.FormEvent<HTMLFormElement>) => void;
    errorMessage?: string | null;
}

export default function Home({ handlePaperSubmit, errorMessage }: HomeProps) {
    return (    
        <>
            <section id="center">
                <h1>Analyze a Paper</h1>
                <p>Upload a paper to get started.</p>
                {errorMessage ? (
                    <p role="alert" style={{ color: 'var(--accent, #c00)', maxWidth: 480, textAlign: 'center' }}>
                        {errorMessage}
                    </p>
                ) : null}
                <form onSubmit={handlePaperSubmit}>
                <input type="file" accept=".pdf" name="file" required />
                <button type="submit">Analyze</button>
                </form>
            </section>
        </>
    );
}