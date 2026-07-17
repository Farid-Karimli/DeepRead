/** Maps a file extension to a Shiki language id. Falls back to plain text. */
const EXTENSION_TO_SHIKI_LANGUAGE: Record<string, string> = {
    py: 'python',
    ts: 'typescript',
    tsx: 'tsx',
    js: 'javascript',
    jsx: 'jsx',
    go: 'go',
    rs: 'rust',
    java: 'java',
    kt: 'kotlin',
    c: 'c',
    h: 'c',
    cpp: 'cpp',
    cc: 'cpp',
    hpp: 'cpp',
    cs: 'csharp',
    rb: 'ruby',
    php: 'php',
    swift: 'swift',
    scala: 'scala',
    sh: 'bash',
    bash: 'bash',
    zsh: 'bash',
    json: 'json',
    yaml: 'yaml',
    yml: 'yaml',
    toml: 'toml',
    md: 'markdown',
    html: 'html',
    css: 'css',
    scss: 'scss',
    sql: 'sql',
    r: 'r',
    lua: 'lua',
    dockerfile: 'dockerfile',
};

export function getShikiLanguage(filepath: string | undefined | null): string {
    if (!filepath) return 'text';
    const basename = filepath.split('/').pop() ?? filepath;
    if (basename.toLowerCase() === 'dockerfile') return 'dockerfile';
    const extension = basename.includes('.') ? basename.split('.').pop()?.toLowerCase() : undefined;
    if (!extension) return 'text';
    return EXTENSION_TO_SHIKI_LANGUAGE[extension] ?? 'text';
}
