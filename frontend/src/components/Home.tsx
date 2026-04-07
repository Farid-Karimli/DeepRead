import React from 'react';

interface HomeProps {
    handlePaperSubmit: (e: React.FormEvent<HTMLFormElement>) => void;
    errorMessage?: string | null;
}

export default function Home({ handlePaperSubmit, errorMessage }: HomeProps) {
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
            </section>
        </>
    );
}