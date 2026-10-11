import { exec } from 'node:child_process';
import * as fs from 'node:fs/promises';
import * as path from 'path';
import { promisify } from 'util';
import z from 'zod';

const exec_async = promisify(exec);
export const root = path.join(path.dirname(new URL(import.meta.url).pathname), '..');
export const static_dir = path.join(root, 'static');

export type PostMeta = z.infer<typeof PostMeta>;
export const PostMeta = z.object({
    id: z.number(),
    date: z.string().regex(/^\d{2}-\d{2}-\d{4}$/),
    media: z.array(z.string()).optional(),
});

export type Size = { width: number; height: number };

export const PREVIEW_WIDTHS = [640, 1280];

export type Preview = Size & { src: string };

const exists = (file: string) =>
    fs.access(file, fs.constants.F_OK).then(
        () => true,
        () => false,
    );

export const video_size = async (file_path: string): Promise<Size> => {
    const out = await $`ffprobe -v error -select_streams v:0 -show_entries stream=width,height:stream_side_data=rotation -of json ${file_path}`;
    const stream = JSON.parse(out).streams[0];
    const rotated = Math.abs(stream.side_data_list?.[0]?.rotation ?? 0) === 90;
    return rotated ? { width: stream.height, height: stream.width } : { width: stream.width, height: stream.height };
};

export const ensure_previews = async (media: path.ParsedPath, size: Size): Promise<Preview[]> => {
    const media_path = path.join(static_dir, 'media', media.base);
    await fs.access(media_path, fs.constants.F_OK);
    await fs.mkdir(path.join(static_dir, 'media/preview'), { recursive: true });

    const widths = PREVIEW_WIDTHS.filter((_, i) => i === 0 || size.width > PREVIEW_WIDTHS[i - 1]! * 1.2);
    const previews: Preview[] = [];
    let frame: string | null = null;
    for (const target of widths) {
        const width = Math.min(target, size.width);
        const height = Math.round((size.height * width) / size.width);
        const name = `media/preview/${media.name}-${target}.webp`;
        const preview_path = path.join(static_dir, name);
        previews.push({ src: `/${name}`, width, height });
        if (await exists(preview_path)) {
            continue;
        }

        console.log(`Generating ${name}...`);
        let source = media_path;
        if (media.ext === '.mp4') {
            frame ??= path.join(static_dir, 'media/preview', `${media.name}-frame.png`);
            if (!(await exists(frame))) {
                await $`ffmpeg -v error -y -i ${media_path} -vf thumbnail -frames:v 1 ${frame}`;
            }

            source = frame;
        }

        await $`cwebp -quiet -q 80 -m 5 -resize ${width} ${height} ${source} -o ${preview_path}`;
    }

    if (frame != null) {
        await fs.rm(frame, { force: true });
    }

    return previews;
};

export const image_size = async (file_path: string): Promise<Size> => {
    const buf = await fs.readFile(file_path);
    const size = buf.toString('ascii', 0, 4) === 'RIFF' ? webp_size(buf) : jpeg_size(buf);
    if (size == null) {
        throw new Error(`Cannot read image size of ${file_path}`);
    }

    return size;
};

const webp_size = (buf: Buffer): Size | null => {
    const chunk = buf.toString('ascii', 12, 16);
    if (chunk === 'VP8 ') {
        return { width: buf.readUInt16LE(26) & 0x3fff, height: buf.readUInt16LE(28) & 0x3fff };
    }

    if (chunk === 'VP8L') {
        const bits = buf.readUInt32LE(21);
        return { width: (bits & 0x3fff) + 1, height: ((bits >> 14) & 0x3fff) + 1 };
    }

    if (chunk === 'VP8X') {
        return { width: buf.readUIntLE(24, 3) + 1, height: buf.readUIntLE(27, 3) + 1 };
    }

    return null;
};

const jpeg_size = (buf: Buffer): Size | null => {
    let offset = 2;
    while (offset + 9 < buf.length) {
        if (buf[offset] !== 0xff) {
            return null;
        }

        const marker = buf[offset + 1]!;
        const is_frame = marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc;
        if (is_frame) {
            return { height: buf.readUInt16BE(offset + 5), width: buf.readUInt16BE(offset + 7) };
        }

        offset += 2 + buf.readUInt16BE(offset + 2);
    }

    return null;
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
