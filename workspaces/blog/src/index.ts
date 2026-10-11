import * as yaml from 'js-yaml';
import { marked } from 'marked';
import * as fs from 'node:fs/promises';
import * as path from 'path';
import { atom_feed, sitemap } from './feeds.ts';
import { clip, headline_of, plain_text, type Lang } from './site.ts';
import { ArchivePage, IndexPage, NotFoundPage, PostPage, type Media, type Post } from './template.ts';
import { translate } from './translate.ts';
import { PostMeta, ensure_previews, image_size, root, static_dir, video_size } from './utils.ts';

type Source = { meta: PostMeta; content: string };

const GENERATED = ['index.html', 'ru.html', 'bunnyfleet.html', '404.html', 'feed.xml', 'sitemap.xml', 'ru', 'p', 'vendor'];

const VENDOR = [
    'photoswipe/dist/photoswipe.css',
    'photoswipe/dist/photoswipe.esm.min.js',
    'photoswipe/dist/photoswipe-lightbox.esm.min.js',
    'photoswipe-video-plugin/dist/photoswipe-video-plugin.esm.min.js',
];

const read_markdown_file = async (file_path: string) => {
    const file_content = await fs.readFile(file_path, 'utf-8');
    const sections = file_content
        .split('---')
        .map((x) => x.trim() || null)
        .filter((x) => x != null);

    const items: Source[] = [];

    for (const section of sections) {
        const yaml_match = section.match(/^```yaml\n([\s\S]*?)\n```/);
        if (!yaml_match) {
            throw new Error('YAML meta not found');
        }

        const yaml_content = yaml_match[1];
        if (yaml_content == null) {
            throw new Error('YAML content not found');
        }

        const content = section.slice(yaml_match[0].length).trim();
        const raw_meta = yaml.load(yaml_content);
        const meta = PostMeta.parse(raw_meta);

        items.push({ meta, content });
    }

    return new Map(items.map((item) => [item.meta.id, item]));
};

const dump_posts = async (file_path: string, posts: Source[]) => {
    const content = posts
        .map((post) => '```yaml\n' + yaml.dump(post.meta) + '```\n\n' + post.content)
        .join('\n\n---\n\n');

    await fs.writeFile(file_path, content + '\n', 'utf-8');
};

const media_of = async (file: string): Promise<Media> => {
    const parsed = path.parse(file);
    const kind = parsed.ext === '.mp4' ? 'video' : 'image';
    const full = path.join(static_dir, 'media', parsed.base);
    const size = kind === 'video' ? await video_size(full) : await image_size(full);
    return { kind, src: `/media/${parsed.base}`, size, previews: await ensure_previews(parsed, size) };
};

const prepare = async (sources: Iterable<Source>): Promise<Post[]> => {
    const posts: Post[] = [];
    for (const { meta, content } of sources) {
        const html = (await marked.parse(content)).replace(/[ \t]+$/gm, '');
        const text = plain_text(html);
        const media: Media[] = [];
        for (const file of meta.media ?? []) {
            media.push(await media_of(file));
        }

        posts.push({
            id: meta.id,
            date: meta.date,
            html,
            text,
            headline: headline_of(text),
            description: clip(text, 160),
            media,
        });
    }

    return posts.sort((a, b) => b.id - a.id);
};

const write = async (relative: string, content: string) => {
    const file = path.join(static_dir, relative);
    await fs.mkdir(path.dirname(file), { recursive: true });
    await fs.writeFile(file, content, 'utf-8');
};

const write_blog = async (lang: Lang, posts: Post[]) => {
    const base = lang === 'en' ? '' : 'ru/';
    await write(`${base}index.html`, IndexPage({ lang, posts }));
    await write(`${base}feed.xml`, atom_feed(lang, posts));
    for (const [i, post] of posts.entries()) {
        await write(
            `${base}p/${post.id}/index.html`,
            PostPage({ lang, post, newer: posts[i - 1] ?? null, older: posts[i + 1] ?? null }),
        );
    }
};

(async () => {
    const ru_sources = await read_markdown_file(path.join(root, 'README.ru.md'));
    const en_sources = await read_markdown_file(path.join(root, 'README.md'));
    const archive_sources = await read_markdown_file(path.join(root, 'README.bunnyfleet.md'));

    for (const [id, post] of ru_sources) {
        const en_post = en_sources.get(id);
        if (en_post != null) {
            console.log(`⚪ ${id} - already exists in English`);
            en_post.meta = post.meta;
            continue;
        }

        console.log(`🟢 ${id} - translating to English`);
        en_sources.set(id, {
            meta: post.meta,
            content: await translate(post.content),
        });
    }

    await dump_posts(
        path.join(root, 'README.md'),
        Array.from(en_sources.values()).sort((a, b) => a.meta.id - b.meta.id),
    );

    const en = await prepare(en_sources.values());
    const ru = await prepare(ru_sources.values());
    const archive = await prepare(archive_sources.values());

    for (const name of GENERATED) {
        await fs.rm(path.join(static_dir, name), { recursive: true, force: true });
    }

    for (const file of VENDOR) {
        await write(`vendor/photoswipe/${path.basename(file)}`, await fs.readFile(path.join(root, 'node_modules', file), 'utf-8'));
    }

    await write_blog('en', en);
    await write_blog('ru', ru);
    await write('bunnyfleet.html', ArchivePage({ posts: archive }));
    await write('404.html', NotFoundPage());
    await write('sitemap.xml', sitemap({ en, ru, archive }));

    console.log(`pages: en ${en.length}, ru ${ru.length}, bunnyfleet ${archive.length}`);
})();
