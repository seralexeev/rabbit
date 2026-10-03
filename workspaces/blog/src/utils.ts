import { exec } from 'node:child_process';
import * as fs from 'node:fs/promises';
import * as path from 'path';
import { promisify } from 'util';
import z from 'zod';

const exec_async = promisify(exec);
export const root = path.join(path.dirname(new URL(import.meta.url).pathname), '..');

export type PostMeta = z.infer<typeof PostMeta>;
export const PostMeta = z.object({
    id: z.number(),
    date: z.string(),
    media: z.array(z.string()).optional(),
});

export const ensure_thumbnail = async (media: path.ParsedPath) => {
    const media_path = path.join(root, 'static/media', media.base);
    await fs.access(media_path, fs.constants.F_OK);

    const preview_path = path.join(root, 'static/media/thumbnails', `${media.name}.webp`);
    const preview_exists = await fs.access(preview_path, fs.constants.F_OK).then(
        () => true,
        () => false,
    );

    if (preview_exists) {
        return;
    }

    console.log(`Generating thumbnail for ${media.base}...`);
    if (media.ext === '.jpg') {
        await $`cwebp -q 50 -m 6 -resize 640 0 ${media_path} -o ${preview_path}`;
    } else if (media.ext === '.mp4') {
        const temp_jpeg = path.join(root, 'static/media/thumbnails', `${media.name}.jpg`);
        await $`ffmpeg -i ${media_path} -vf "thumbnail,scale=640:-1" -frames:v 1 ${temp_jpeg}`;
        await $`cwebp -q 50 -m 6 ${temp_jpeg} -o ${preview_path}`;
        await $`rm ${temp_jpeg}`;
    }
};

const $ = async (strings: TemplateStringsArray, ...values: Array<string | number>): Promise<string> => {
    const cmd = String.raw(strings, ...values);

    try {
        const { stdout, stderr } = await exec_async(cmd);
        if (stderr) {
            process.stderr.write(stderr);
        }

        return stdout.trim();
    } catch (err: any) {
        if (err.stderr) {
            console.error(err.stderr.trim());
        }

        throw err;
    }
};
