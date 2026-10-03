import { marked } from 'marked';
import path from 'node:path';
import type { PostMeta } from './index.ts';
import { ensure_thumbnail } from './utils.ts';

const Image = ({ media_name }: { media_name: path.ParsedPath }) => {
    const preview_name = path.join('media/thumbnails', `${media_name.name}.webp`);
    const original_name = path.join('media', media_name.base);

    return html`
        <a class="media-item" href="${original_name}" target="_blank" rel="noopener noreferrer">
            <img src="${preview_name}" alt="Preview" loading="lazy" decoding="async" />
        </a>
    `;
};

const Video = ({ media_name }: { media_name: path.ParsedPath }) => {
    const preview_name = path.join('media/thumbnails', `${media_name.name}.webp`);
    const original_name = path.join('media', media_name.base);

    return html`
        <a class="media-item" href="${original_name}" target="_blank" rel="noopener noreferrer">
            <div class="video-overlay">Click to Play</div>
            <img src="${preview_name}" alt="Preview" loading="lazy" decoding="async" />
        </a>
    `;
};

const Post = async ({ meta, content }: { meta: PostMeta; content: string }) => {
    const media = async () => {
        if (meta.media == null || meta.media.length === 0) {
            return null;
        }

        const items: string[] = [];
        for (const item of meta.media) {
            const media_name = path.parse(item);
            await ensure_thumbnail(media_name);
            const media_content = media_name.ext === '.mp4' ? Video({ media_name }) : Image({ media_name });
            items.push(media_content);
        }

        return html`<div class="post-media">${items.join('')}</div>`;
    };

    return html`
        <article class="post" id="${meta.id}">
            <div class="post-header">
                <a href="#${meta.id}">#${meta.id}</a>
                <div class="post-meta">${meta.date}</div>
            </div>
            <div class="post-body">${content}</div>
            ${await media()}
        </article>
    `;
};

export const Blog = async ({ posts }: { posts: Array<{ meta: PostMeta; content: string }> }) => {
    const rendered_posts: string[] = [];
    for (const post of posts) {
        const content = await marked.parse(post.content);
        rendered_posts.push(await Post({ meta: post.meta, content }));
    }

    const divider = html`<div class="divider">...</div>`;

    return html`
        <!DOCTYPE html>
        <html lang="en">
            <head>
                <meta charset="UTF-8" />
                <meta name="viewport" content="width=device-width, initial-scale=1.0" />
                <title>🐰 Robot Rabbit</title>
                <meta
                    name="description"
                    content="Robot Rabbit: A blog about building a robot with Ackermann steering, ROS2 (NATS), and autonomous navigation. Follow the journey from hardware to software, including electronics, mechanics, and code."
                />
                <meta
                    name="keywords"
                    content="robot, robotics, Ackermann, ROS2, Raspberry Pi, Jetson, hardware, electronics, DIY, blog, autonomous, navigation, servo, BLDC, prototype, PCB, software, fullstack"
                />
                <meta name="robots" content="index, follow" />
                <link rel="canonical" href="https://rabbit0.dev/" />
                <meta property="og:title" content="Robot Rabbit" />
                <meta
                    property="og:description"
                    content="A blog about building a robot with Ackermann steering, ROS2 (NATS), and autonomous navigation."
                />
                <meta property="og:type" content="website" />
                <meta property="og:url" content="https://rabbit0.dev/" />
                <meta property="og:image" content="https://rabbit0.dev/media/logo.gif" />
                <meta name="twitter:card" content="summary_large_image" />
                <meta name="twitter:title" content="Robot Rabbit" />
                <meta
                    name="twitter:description"
                    content="A blog about building a robot with Ackermann steering, ROS2 (NATS), and autonomous navigation."
                />
                <meta name="twitter:image" content="https://rabbit0.dev/media/logo.gif" />
                <link rel="preconnect" href="https://fonts.googleapis.com" />
                <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />

                <style>
                    :root {
                        --color-black: #000;
                        --color-white: #fff;
                        --color-gray: #aaa;
                        --color-blue: #007aff;
                        --color-green: #41ff00;
                    }

                    * {
                        margin: 0;
                        padding: 0;
                        box-sizing: border-box;
                    }

                    html,
                    body,
                    div,
                    span,
                    h1,
                    h2,
                    h3,
                    h4,
                    h5,
                    h6,
                    p,
                    pre,
                    code {
                        margin: 0;
                        padding: 0;
                        border: 0;
                        font-size: 100%;
                        font: inherit;
                        vertical-align: baseline;
                    }

                    body {
                        font-family: 'Fira Code', monospace;
                        font-size: 16px;
                        line-height: 1.4;
                        color: var(--color-black);
                        background: var(--color-white);
                        padding: 20px;
                    }

                    .container {
                        max-width: 720px;
                        margin: 0 auto;
                    }

                    header {
                        margin-bottom: 48px;
                    }

                    footer {
                        margin: 48px 0;
                        text-align: center;
                        font-size: 14px;
                    }

                    h1 {
                        font-size: 24px;
                        font-weight: normal;
                        background: var(--color-black);
                        color: var(--color-green);
                        margin-top: 2px;
                    }

                    header img {
                        height: 36px;
                        vertical-align: middle;
                    }

                    .post-list {
                        display: flex;
                        flex-direction: column;
                        gap: 20px;
                    }

                    .post {
                        width: 100%;
                        display: flex;
                        flex-direction: column;
                        gap: 8px;
                        overflow: hidden;
                    }

                    .post-header {
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        gap: 8px;
                    }

                    .post-meta {
                        color: var(--color-gray);
                    }

                    .post-media {
                        display: flex;
                        gap: 8px;
                    }

                    .media-item {
                        text-decoration: none;
                        border: none;
                        background: var(--color-black);
                        width: 100%;
                        overflow: hidden;
                        position: relative;
                        max-height: 512px;
                        border-radius: 4px;
                    }

                    .media-item img,
                    .media-item video {
                        width: 100%;
                        height: 100%;
                        object-fit: cover;
                        cursor: pointer;
                    }

                    .media-item .video-overlay {
                        position: absolute;
                        top: 0;
                        left: 0;
                        width: 100%;
                        height: 100%;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        background: var(--color-black);
                        opacity: 0.7;
                        color: var(--color-white);
                        font-size: 16px;
                        z-index: 1;
                    }

                    a {
                        color: var(--color-blue);
                        text-decoration: underline;
                        text-underline-offset: 0.2rem;
                        word-wrap: break-word;
                    }

                    u {
                        text-decoration: none;
                        border-bottom: 1px solid var(--color-black);
                    }

                    p {
                        margin-bottom: 16px;
                    }

                    ul {
                        margin-left: 20px;
                    }

                    ul li > p {
                        margin-bottom: 0;
                    }

                    ul li {
                        margin-bottom: 8px;
                    }

                    ul li::marker {
                        content: '> ';
                        color: var(--color-gray);
                    }

                    code {
                        background: var(--color-black);
                        color: var(--color-green);
                        padding: 0 2px;
                        font-family: inherit;
                    }

                    pre {
                        background: var(--color-black);
                        color: var(--color-green);
                        padding: 8px;
                        margin: 8px 0;
                        overflow-x: auto;
                    }

                    .divider {
                        text-align: center;
                        color: var(--color-gray);
                        font-size: 14px;
                    }

                    .translated {
                        color: var(--color-gray);
                        font-size: 12px;
                        text-align: right;
                        margin-top: 4px;
                        display: flex;
                        justify-content: space-between;
                    }
                </style>
            </head>
            <body>
                <div class="container">
                    <header>
                        <img alt="Robot Rabbit" src="./media/logo.gif" />
                        <h1>Robot Rabbit</h1>
                        <div class="translated">
                            <span>translated from Russian via ChatGPT</span>
                            <span><a href="/ru">RU</a> <a href="/">EN</a> <a href="/bunnyfleet">BunnyFleet</a></span>
                        </div>
                    </header>

                    <div class="post-list">${rendered_posts.join(divider)}</div>

                    <footer><a href="https://www.linkedin.com/in/seralexeev">Sergey Alekseev</a></footer>
                </div>
            </body>
            <link
                href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@300..700&display=swap"
                rel="stylesheet"
            />
        </html>
    `;
};

const html = (strings: TemplateStringsArray, ...values: Array<string | null | number | string[]>) => {
    return String.raw(strings, ...values.map((x) => (Array.isArray(x) ? x.join('') : x ?? '')));
};
