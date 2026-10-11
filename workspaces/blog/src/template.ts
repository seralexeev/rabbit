import { AUTHOR, DEFAULT_IMAGE, LOCALES, REPO, SITE, absolute, esc, other_lang, published_at, type Lang, type Locale } from './site.ts';
import type { Preview, Size } from './utils.ts';

export type Media = {
    kind: 'image' | 'video';
    src: string;
    size: Size;
    previews: Preview[];
};

export const thumb = (media: Media) => media.previews[0]!;

export const poster = (media: Media) => media.previews[media.previews.length - 1]!;

export type Post = {
    id: number;
    date: string;
    html: string;
    text: string;
    headline: string;
    description: string;
    media: Media[];
};

type Alternate = { hreflang: string; href: string };

type Image = { src: string; width: number; height: number; alt: string };

type Head = {
    lang: Lang;
    title: string;
    description: string;
    canonical: string | null;
    alternates: Alternate[];
    og_type: 'website' | 'article';
    og_title: string;
    image: Image;
    video: string | null;
    published: string | null;
    feed: { href: string; title: string } | null;
    robots: string;
    json_ld: object[];
};

export const html = (strings: TemplateStringsArray, ...values: Array<string | null | number | string[]>) => {
    return String.raw(strings, ...values.map((x) => (Array.isArray(x) ? x.join('') : (x ?? ''))));
};

const json_ld = (data: object) =>
    html`<script type="application/ld+json">${JSON.stringify({ '@context': 'https://schema.org', ...data }).replace(/</g, '\\u003c')}</script>`;

const Head = (head: Head) => {
    const locale = LOCALES[head.lang];
    const alt_locale = LOCALES[other_lang(head.lang)];
    return html`
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>${esc(head.title)}</title>
        <meta name="description" content="${esc(head.description)}" />
        <meta name="robots" content="${head.robots}" />
        <meta name="author" content="${AUTHOR.name}" />
        <meta name="theme-color" content="#ffffff" />
        <meta name="color-scheme" content="light" />
        ${head.canonical != null ? html`<link rel="canonical" href="${absolute(head.canonical)}" />` : null}
        ${head.alternates.map((x) => html`<link rel="alternate" hreflang="${x.hreflang}" href="${absolute(x.href)}" />`)}
        ${head.feed != null ? html`<link rel="alternate" type="application/atom+xml" title="${esc(head.feed.title)}" href="${head.feed.href}" />` : null}
        <link rel="icon" href="/favicon.ico" sizes="48x48" />
        <link rel="icon" href="/icon-192.png" type="image/png" sizes="192x192" />
        <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
        <link rel="manifest" href="/site.webmanifest" />
        <meta property="og:site_name" content="${locale.name}" />
        <meta property="og:type" content="${head.og_type}" />
        <meta property="og:title" content="${esc(head.og_title)}" />
        <meta property="og:description" content="${esc(head.description)}" />
        ${head.canonical != null ? html`<meta property="og:url" content="${absolute(head.canonical)}" />` : null}
        <meta property="og:locale" content="${locale.og_locale}" />
        ${head.alternates.length > 0 ? html`<meta property="og:locale:alternate" content="${alt_locale.og_locale}" />` : null}
        <meta property="og:image" content="${absolute(head.image.src)}" />
        <meta property="og:image:width" content="${head.image.width}" />
        <meta property="og:image:height" content="${head.image.height}" />
        <meta property="og:image:alt" content="${esc(head.image.alt)}" />
        ${head.video != null
            ? html`<meta property="og:video" content="${absolute(head.video)}" />
                  <meta property="og:video:type" content="video/mp4" />`
            : null}
        ${head.published != null
            ? html`<meta property="article:published_time" content="${head.published}" />
                  <meta property="article:author" content="${AUTHOR.url}" />`
            : null}
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:title" content="${esc(head.og_title)}" />
        <meta name="twitter:description" content="${esc(head.description)}" />
        <meta name="twitter:image" content="${absolute(head.image.src)}" />
        <meta name="twitter:image:alt" content="${esc(head.image.alt)}" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
        <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@300..700&amp;display=swap" rel="stylesheet" />
        <link rel="stylesheet" href="/vendor/photoswipe/photoswipe.css" />
        <style>
            ${STYLE}
        </style>
        ${head.json_ld.map(json_ld)}
    `;
};

const Page = ({ head, header, body }: { head: Head; header: string; body: string }) => {
    const locale = LOCALES[head.lang];
    return html`<!DOCTYPE html>
<html lang="${head.lang}">
    <head>
        ${Head(head)}
    </head>
    <body>
        <div class="container">
            ${header}
            <main>${body}</main>
            <footer>
                <a href="${AUTHOR.url}" rel="author">${AUTHOR.name}</a> · <a href="${REPO}">GitHub</a> ·
                <a href="${locale.feed}" type="application/atom+xml">RSS</a>
            </footer>
        </div>
        <script type="module">
            ${LIGHTBOX}
        </script>
    </body>
</html>
`;
};

const Header = ({
    lang,
    title,
    home,
    links,
}: {
    lang: Lang;
    title: string;
    home: string | null;
    links: { en: string; ru: string };
}) => {
    const locale = LOCALES[lang];
    const switcher = (target: Lang, label: string) =>
        target === lang
            ? html`<a href="${links[target]}" aria-current="page">${label}</a>`
            : html`<a href="${links[target]}" hreflang="${target}" lang="${target}">${label}</a>`;

    return html`
        <header>
            <a href="${locale.home}" class="logo"><img alt="${locale.name}" src="/media/logo.gif" width="67" height="36" /></a>
            <h1>${home != null ? html`<a href="${home}">${locale.name}</a> ${title}` : title}</h1>
            <div class="translated">
                <span>${locale.note}</span>
                <nav aria-label="Language">
                    ${switcher('ru', 'RU')} ${switcher('en', 'EN')} <a href="/bunnyfleet">BunnyFleet</a>
                </nav>
            </div>
        </header>
    `;
};

const MediaItem = ({
    media,
    alt,
    play,
    eager,
    count,
}: {
    media: Media;
    alt: string;
    play: string;
    eager: boolean;
    count: number;
}) => {
    const small = thumb(media);
    const gaps = 8 * (count - 1);
    const sizes = `(max-width: 752px) calc((100vw - ${32 + gaps}px) / ${count}), ${Math.round((720 - gaps) / count)}px`;
    const srcset = media.previews.map((x) => `${x.src} ${x.width}w`).join(', ');
    const loading = eager ? html`fetchpriority="high"` : html`loading="lazy"`;
    const img = html`<img src="${small.src}" srcset="${srcset}" sizes="${sizes}" alt="${esc(alt)}" width="${small.width}" height="${small.height}" ${loading} decoding="async" />`;
    const video = media.kind === 'video' ? html` type="video/mp4" data-pswp-type="video"` : null;
    return html`
        <a class="media-item" href="${media.src}" data-pswp-width="${media.size.width}" data-pswp-height="${media.size.height}"${video}>
            ${media.kind === 'video' ? html`<span class="video-overlay" aria-hidden="true">${esc(play)}</span>` : null}${img}
        </a>
    `;
};

const media_alt = (locale: Locale, post: Post, index: number) => {
    const media = post.media[index]!;
    const count = post.media.filter((x) => x.kind === media.kind).length;
    const n = post.media.slice(0, index + 1).filter((x) => x.kind === media.kind).length;
    const label = media.kind === 'video' ? locale.video : locale.photo;
    return `${post.headline} (${label}${count > 1 ? ` ${n}` : ''})`;
};

const PostArticle = ({
    locale,
    post,
    permalink,
    eager,
}: {
    locale: Locale;
    post: Post;
    permalink: string | null;
    eager: boolean;
}) => html`
    <article class="post" id="${post.id}">
        <div class="post-header">
            <a href="${permalink ?? `#${post.id}`}">#${post.id}</a>
            <time class="post-meta" datetime="${published_at(post.date).slice(0, 10)}">${post.date}</time>
        </div>
        <div class="post-body">${post.html}</div>
        ${post.media.length > 0
            ? html`<div class="post-media">
                  ${post.media.map((media, i) => MediaItem({ media, alt: media_alt(locale, post, i), play: locale.play, eager: eager && i === 0, count: post.media.length }))}
              </div>`
            : null}
    </article>
`;

const og_image = (locale: Locale, post: Post | null): Image => {
    const photo = post?.media.find((x) => x.kind === 'image');
    if (post != null && photo != null) {
        return { src: photo.src, ...photo.size, alt: media_alt(locale, post, post.media.indexOf(photo)) };
    }

    const video = post?.media.find((x) => x.kind === 'video');
    if (post != null && video != null) {
        const frame = poster(video);
        return { src: frame.src, width: frame.width, height: frame.height, alt: media_alt(locale, post, post.media.indexOf(video)) };
    }

    return { ...DEFAULT_IMAGE, alt: locale.image_alt };
};

const blog_ref = (locale: Locale) => ({ '@type': 'Blog', '@id': absolute(locale.home) + '#blog', name: locale.name, url: absolute(locale.home) });

const divider = html`<div class="divider" aria-hidden="true">...</div>`;

export const IndexPage = ({ lang, posts }: { lang: Lang; posts: Post[] }) => {
    const locale = LOCALES[lang];
    const latest = posts[0];
    const head: Head = {
        lang,
        title: locale.title,
        description: locale.description,
        canonical: locale.home,
        alternates: [
            { hreflang: 'en', href: LOCALES.en.home },
            { hreflang: 'ru', href: LOCALES.ru.home },
            { hreflang: 'x-default', href: LOCALES.en.home },
        ],
        og_type: 'website',
        og_title: locale.name,
        image: og_image(locale, null),
        video: null,
        published: null,
        feed: { href: locale.feed, title: locale.name },
        robots: 'index, follow, max-image-preview:large',
        json_ld: [
            {
                '@type': 'WebSite',
                '@id': SITE + '/#website',
                name: locale.name,
                url: absolute(locale.home),
                inLanguage: lang,
                description: locale.description,
                publisher: AUTHOR,
            },
            {
                ...blog_ref(locale),
                description: locale.description,
                inLanguage: lang,
                author: AUTHOR,
                image: absolute(DEFAULT_IMAGE.src),
                dateModified: latest != null ? published_at(latest.date) : undefined,
                blogPost: posts.slice(0, 10).map((post) => ({
                    '@type': 'BlogPosting',
                    headline: post.headline,
                    url: absolute(locale.post_path(post.id)),
                    datePublished: published_at(post.date),
                })),
            },
        ],
    };

    return Page({
        head,
        header: Header({ lang, title: locale.name, home: null, links: { en: LOCALES.en.home, ru: LOCALES.ru.home } }),
        body: html`<div class="post-list">
            ${posts.map((post, i) => PostArticle({ locale, post, permalink: locale.post_path(post.id), eager: i === 0 })).join(divider)}
        </div>`,
    });
};

export const PostPage = ({
    lang,
    post,
    older,
    newer,
}: {
    lang: Lang;
    post: Post;
    older: Post | null;
    newer: Post | null;
}) => {
    const locale = LOCALES[lang];
    const url = locale.post_path(post.id);
    const links = { en: LOCALES.en.post_path(post.id), ru: LOCALES.ru.post_path(post.id) };
    const image = og_image(locale, post);
    const video = post.media.find((x) => x.kind === 'video') ?? null;
    const published = published_at(post.date);
    const translation =
        lang === 'en' ? { translationOfWork: { '@id': absolute(links.ru) } } : { workTranslation: { '@id': absolute(links.en) } };

    const head: Head = {
        lang,
        title: `${post.headline} · ${locale.name} #${post.id}`,
        description: post.description,
        canonical: url,
        alternates: [
            { hreflang: 'en', href: links.en },
            { hreflang: 'ru', href: links.ru },
            { hreflang: 'x-default', href: links.en },
        ],
        og_type: 'article',
        og_title: `${post.headline} · #${post.id}`,
        image,
        video: video?.src ?? null,
        published,
        feed: { href: locale.feed, title: locale.name },
        robots: 'index, follow, max-image-preview:large',
        json_ld: [
            {
                '@type': 'BlogPosting',
                '@id': absolute(url),
                headline: post.headline,
                description: post.description,
                url: absolute(url),
                mainEntityOfPage: absolute(url),
                datePublished: published,
                dateModified: published,
                inLanguage: lang,
                author: AUTHOR,
                publisher: AUTHOR,
                isPartOf: blog_ref(locale),
                image: post.media.some((x) => x.kind === 'image')
                    ? post.media.filter((x) => x.kind === 'image').map((x) => absolute(x.src))
                    : absolute(image.src),
                video: post.media
                    .filter((x) => x.kind === 'video')
                    .map((x, i) => ({
                        '@type': 'VideoObject',
                        name: `${post.headline} (${locale.video}${i > 0 ? ` ${i + 1}` : ''})`,
                        description: post.description,
                        thumbnailUrl: absolute(poster(x).src),
                        width: x.size.width,
                        height: x.size.height,
                        contentUrl: absolute(x.src),
                        uploadDate: published,
                    })),
                ...translation,
            },
            {
                '@type': 'BreadcrumbList',
                itemListElement: [
                    { '@type': 'ListItem', position: 1, name: locale.name, item: absolute(locale.home) },
                    { '@type': 'ListItem', position: 2, name: `#${post.id}`, item: absolute(url) },
                ],
            },
        ],
    };

    const nav = html`
        <nav class="post-nav" aria-label="Posts">
            <span>${older != null ? html`<a href="${locale.post_path(older.id)}" rel="prev">← #${older.id} ${locale.older}</a>` : null}</span>
            <a href="${locale.home}#${post.id}">${locale.all_posts}</a>
            <span>${newer != null ? html`<a href="${locale.post_path(newer.id)}" rel="next">${locale.newer} #${newer.id} →</a>` : null}</span>
        </nav>
    `;

    return Page({
        head,
        header: Header({ lang, title: `#${post.id}`, home: locale.home, links }),
        body: html`${PostArticle({ locale, post, permalink: url, eager: true })}${nav}`,
    });
};

export const ArchivePage = ({ posts }: { posts: Post[] }) => {
    const locale = LOCALES.en;
    const head: Head = {
        lang: 'en',
        title: 'BunnyFleet · build log of a last-mile delivery platform',
        description:
            'Notes from building BunnyFleet, a last-mile delivery platform, in 2023: tasks, runs, real-time UIs and the data model behind them.',
        canonical: '/bunnyfleet',
        alternates: [],
        og_type: 'website',
        og_title: 'BunnyFleet',
        image: og_image(locale, posts.find((x) => x.media.some((m) => m.kind === 'image')) ?? null),
        video: null,
        published: null,
        feed: null,
        robots: 'index, follow, max-image-preview:large',
        json_ld: [
            {
                '@type': 'Blog',
                name: 'BunnyFleet',
                url: absolute('/bunnyfleet'),
                inLanguage: 'en',
                author: AUTHOR,
            },
        ],
    };

    return Page({
        head,
        header: Header({ lang: 'en', title: 'BunnyFleet', home: locale.home, links: { en: '/', ru: '/ru/' } }),
        body: html`<div class="post-list">
            ${posts.map((post, i) => PostArticle({ locale, post, permalink: null, eager: i === 0 })).join(divider)}
        </div>`,
    });
};

export const NotFoundPage = () => {
    const head: Head = {
        lang: 'en',
        title: 'Not found · Robot Rabbit',
        description: 'This page does not exist.',
        canonical: null,
        alternates: [],
        og_type: 'website',
        og_title: 'Robot Rabbit',
        image: { ...DEFAULT_IMAGE, alt: LOCALES.en.image_alt },
        video: null,
        published: null,
        feed: null,
        robots: 'noindex',
        json_ld: [],
    };

    return Page({
        head,
        header: Header({ lang: 'en', title: '404', home: '/', links: { en: '/', ru: '/ru/' } }),
        body: html`
            <script>
                if (location.pathname === '/ru.html') location.replace('/ru/' + location.hash);
            </script>
            <div class="post-body">
                <p>Page not found. <a href="/">All posts</a></p>
                <p lang="ru">Страница не найдена. <a href="/ru/">Все посты</a></p>
            </div>
        `,
    });
};

const LIGHTBOX = `
    import PhotoSwipeLightbox from '/vendor/photoswipe/photoswipe-lightbox.esm.min.js';
    import PhotoSwipeVideoPlugin from '/vendor/photoswipe/photoswipe-video-plugin.esm.min.js';

    const lightbox = new PhotoSwipeLightbox({
        gallery: '.post-media',
        children: 'a.media-item',
        pswpModule: () => import('/vendor/photoswipe/photoswipe.esm.min.js'),
        bgOpacity: 0.95,
        showHideAnimationType: 'fade',
        wheelToZoom: true,
        preload: [1, 1],
    });

    lightbox.addFilter('itemData', (data) => {
        const img = data.element?.querySelector('img');
        return img != null ? { ...data, msrc: img.currentSrc || img.src, alt: img.alt } : data;
    });

    new PhotoSwipeVideoPlugin(lightbox, { videoAttributes: { controls: '', playsinline: '', preload: 'metadata' } });
    lightbox.init();
`;

const STYLE = `
    :root {
        --color-black: #000;
        --color-white: #fff;
        --color-gray: #6b6b6b;
        --color-blue: #0062cc;
        --color-green: #41ff00;
    }

    * {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }

    html {
        -webkit-text-size-adjust: 100%;
        text-size-adjust: 100%;
    }

    body {
        font-family: 'Fira Code', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 16px;
        line-height: 1.4;
        color: var(--color-black);
        background: var(--color-white);
        padding: 20px 16px;
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

    h1 a {
        color: inherit;
        text-decoration: none;
    }

    header img {
        height: 36px;
        width: auto;
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

    .post-body img {
        max-width: 100%;
        height: auto;
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
        min-width: 0;
        overflow: hidden;
        position: relative;
        max-height: 512px;
        border-radius: 4px;
    }

    .media-item img {
        display: block;
        width: 100%;
        height: 100%;
        object-fit: cover;
        cursor: pointer;
    }

    .pswp video {
        background: var(--color-black);
    }

    .media-item .video-overlay {
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        background: rgba(0, 0, 0, 0.7);
        color: var(--color-white);
        font-size: 16px;
        z-index: 1;
    }

    a {
        color: var(--color-blue);
        text-decoration: underline;
        text-underline-offset: 0.2rem;
        overflow-wrap: anywhere;
    }

    u {
        text-decoration: none;
        border-bottom: 1px solid var(--color-black);
    }

    p {
        margin-bottom: 16px;
    }

    strong {
        font-weight: 600;
    }

    ul,
    ol {
        margin-left: 20px;
        margin-bottom: 16px;
    }

    li > p {
        margin-bottom: 0;
    }

    li {
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
        margin: 8px 0 16px;
        overflow-x: auto;
    }

    pre code {
        padding: 0;
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
        gap: 8px;
    }

    .translated nav a {
        margin-left: 4px;
    }

    .translated a[aria-current] {
        color: var(--color-black);
        text-decoration: none;
    }

    .post-nav {
        display: flex;
        justify-content: space-between;
        gap: 8px;
        margin-top: 32px;
        font-size: 14px;
    }

    .post-nav > span {
        flex: 1;
    }

    .post-nav > span:last-child {
        text-align: right;
    }

    @media (max-width: 480px) {
        body {
            font-size: 15px;
        }

        h1 {
            font-size: 20px;
        }
    }
`;
