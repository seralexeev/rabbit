import { AUTHOR, LOCALES, SITE, absolute, esc, published_at, type Lang } from './site.ts';
import { poster, type Post } from './template.ts';

const FEED_SIZE = 50;

const absolute_html = (post: Post) =>
    post.html +
    post.media
        .map((media) => {
            const frame = poster(media);
            const alt = media.kind === 'video' ? 'video' : '';
            return `<p><a href="${absolute(media.src)}"><img src="${absolute(frame.src)}" width="${frame.width}" height="${frame.height}" alt="${alt}" /></a></p>`;
        })
        .join('');

export const atom_feed = (lang: Lang, posts: Post[]) => {
    const locale = LOCALES[lang];
    const latest = posts[0];
    if (latest == null) {
        throw new Error(`No posts for the ${lang} feed`);
    }

    const entries = posts.slice(0, FEED_SIZE).map((post) => {
        const url = absolute(locale.post_path(post.id));
        const published = published_at(post.date);
        return `
  <entry>
    <title>${esc(`#${post.id} · ${post.headline}`)}</title>
    <link rel="alternate" type="text/html" href="${url}"/>
    <id>${url}</id>
    <published>${published}</published>
    <updated>${published}</updated>
    <summary>${esc(post.description)}</summary>
    <content type="html">${esc(absolute_html(post))}</content>
  </entry>`;
    });

    return `<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="${lang}">
  <title>${esc(locale.name)}</title>
  <subtitle>${esc(locale.description)}</subtitle>
  <link rel="self" type="application/atom+xml" href="${absolute(locale.feed)}"/>
  <link rel="alternate" type="text/html" href="${absolute(locale.home)}"/>
  <id>${absolute(locale.home)}</id>
  <updated>${published_at(latest.date)}</updated>
  <author>
    <name>${esc(AUTHOR.name)}</name>
    <uri>${AUTHOR.url}</uri>
  </author>
  <icon>${SITE}/icon-192.png</icon>
  <logo>${SITE}/media/og.jpg</logo>
${entries.join('')}
</feed>
`;
};

type Entry = { loc: string; lastmod: string; alternates: Array<{ hreflang: string; href: string }> };

const pair = (en: string, ru: string) => [
    { hreflang: 'en', href: absolute(en) },
    { hreflang: 'ru', href: absolute(ru) },
    { hreflang: 'x-default', href: absolute(en) },
];

export const sitemap = ({ en, ru, archive }: { en: Post[]; ru: Post[]; archive: Post[] }) => {
    const entries: Entry[] = [];
    const newest = (posts: Post[]) => published_at(posts[0]!.date).slice(0, 10);

    const home = pair(LOCALES.en.home, LOCALES.ru.home);
    entries.push({ loc: absolute(LOCALES.en.home), lastmod: newest(en), alternates: home });
    entries.push({ loc: absolute(LOCALES.ru.home), lastmod: newest(ru), alternates: home });

    const ru_ids = new Set(ru.map((x) => x.id));
    for (const lang of ['en', 'ru'] as const) {
        for (const post of lang === 'en' ? en : ru) {
            const both = ru_ids.has(post.id);
            entries.push({
                loc: absolute(LOCALES[lang].post_path(post.id)),
                lastmod: published_at(post.date).slice(0, 10),
                alternates: both ? pair(LOCALES.en.post_path(post.id), LOCALES.ru.post_path(post.id)) : [],
            });
        }
    }

    entries.push({ loc: absolute('/bunnyfleet'), lastmod: newest(archive), alternates: [] });

    const urls = entries.map(
        (entry) => `  <url>
    <loc>${esc(entry.loc)}</loc>
    <lastmod>${entry.lastmod}</lastmod>
${entry.alternates.map((x) => `    <xhtml:link rel="alternate" hreflang="${x.hreflang}" href="${esc(x.href)}"/>\n`).join('')}  </url>`,
    );

    return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">
${urls.join('\n')}
</urlset>
`;
};
