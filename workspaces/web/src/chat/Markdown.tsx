import { css } from '@emotion/css';
import React from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { InlineToken } from './answer/InlineToken.tsx';
import { parseToken } from './answer/tokens.ts';

const PLUGINS = [remarkGfm];

const Code: Components['code'] = ({ className, children }) => {
    const token = className == null && typeof children === 'string' ? parseToken(children) : null;
    return token == null ? <code className={className}>{children}</code> : <InlineToken token={token} />;
};

const COMPONENTS: Components = { code: Code };

export const Markdown: React.FC<{ text: string }> = ({ text }) => (
    <div className={markdownCss}>
        <ReactMarkdown remarkPlugins={PLUGINS} components={COMPONENTS}>
            {text}
        </ReactMarkdown>
    </div>
);

const markdownCss = css`
    font-size: 11px;
    line-height: 1.5;
    text-transform: none;
    letter-spacing: 0.01em;
    overflow-wrap: anywhere;

    & p {
        margin: 0 0 6px;
    }

    & p:last-child {
        margin-bottom: 0;
    }

    & ul,
    & ol {
        margin: 2px 0 6px;
        padding-left: 18px;
    }

    & li::marker {
        color: var(--hud-dim);
    }

    & strong {
        color: #fff;
        font-weight: 600;
    }

    & h1,
    & h2,
    & h3,
    & h4 {
        margin: 8px 0 4px;
        font-size: 11px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--hud);
    }

    & code {
        padding: 0 3px;
        background: rgba(98, 232, 255, 0.1);
        font-family: inherit;
    }

    & pre {
        margin: 4px 0 6px;
        padding: 6px;
        background: rgba(0, 0, 0, 0.5);
        border-left: 2px solid var(--hud-dim);
        overflow-x: auto;
    }

    & pre code {
        padding: 0;
        background: none;
    }

    & a {
        color: var(--hud-amber);
    }

    & table {
        border-collapse: collapse;
        margin: 4px 0 6px;
        font-size: 10px;
    }

    & th,
    & td {
        padding: 2px 6px;
        border-bottom: 1px solid var(--hud-faint);
        text-align: left;
    }

    & blockquote {
        margin: 4px 0;
        padding-left: 8px;
        border-left: 2px solid var(--hud-amber);
        opacity: 0.85;
    }
`;
