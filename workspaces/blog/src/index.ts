import * as yaml from 'js-yaml';
import * as fs from 'node:fs/promises';
import * as path from 'path';
import { Blog } from './template.ts';
import { translate } from './translate.ts';
import { PostMeta, root } from './utils.ts';

const read_markdown_file = async (file_path: string) => {
    const file_content = await fs.readFile(file_path, 'utf-8');
    const sections = file_content
        .split('---')
        .map((x) => x.trim() || null)
        .filter((x) => x != null);

    const items: Array<{
        meta: PostMeta;
        content: string;
    }> = [];

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

const dump_posts = async (file_path: string, posts: { meta: PostMeta; content: string }[]) => {
    const content = posts
        .map((post) => '```yaml\n' + yaml.dump(post.meta) + '```\n\n' + post.content)
        .join('\n\n---\n\n');

    await fs.writeFile(file_path, content + '\n', 'utf-8');
};

const render_html = async (posts: Array<{ meta: PostMeta; content: string }>, file_name: string) => {
    const result = await Blog({ posts });
    const output_path = path.join(root, 'static', file_name);
    await fs.writeFile(output_path, result, 'utf-8');
};

(async () => {
    const ru_posts = await read_markdown_file(path.join(root, 'README.ru.md'));
    const en_posts = await read_markdown_file(path.join(root, 'README.md'));
    const bunnyfleet_posts = await read_markdown_file(path.join(root, 'README.bunnyfleet.md'));

    for (const [id, post] of ru_posts) {
        const en_post = en_posts.get(id);
        if (en_post != null) {
            console.log(`⚪ ${id} - already exists in English`);
            en_post.meta = post.meta; // Update metadata if needed
            continue;
        }

        console.log(`🟢 ${id} - translating to English`);
        en_posts.set(id, {
            meta: post.meta,
            content: await translate(post.content),
        });
    }

    const en_items = Array.from(en_posts.values());
    const ru_items = Array.from(ru_posts.values());

    await dump_posts(
        path.join(root, 'README.md'),
        en_items.sort((a, b) => a.meta.id - b.meta.id),
    );

    await render_html(
        en_items.sort((a, b) => b.meta.id - a.meta.id),
        'index.html',
    );

    await render_html(
        ru_items.sort((a, b) => b.meta.id - a.meta.id),
        'ru.html',
    );

    await render_html(
        Array.from(bunnyfleet_posts.values()).sort((a, b) => b.meta.id - a.meta.id),
        'bunnyfleet.html',
    );
})();
export { PostMeta };
