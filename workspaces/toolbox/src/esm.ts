import { createRequire } from 'module';
import path from 'path';
import process from 'process';
import { fileURLToPath } from 'url';

const stripExt = (name: string) => {
    const extension = path.extname(name);
    if (!extension) {
        return name;
    }

    return name.slice(0, -extension.length);
};

export const isMain = (meta: ImportMeta) => {
    if (!meta || !process.argv[1]) {
        return false;
    }

    const require = createRequire(meta.url);
    const scriptPath = require.resolve(process.argv[1]);

    const modulePath = fileURLToPath(meta.url);

    const extension = path.extname(scriptPath);
    if (extension) {
        return modulePath === scriptPath;
    }

    return stripExt(modulePath) === scriptPath;
};

export const run = async (meta: ImportMeta, fn: () => Promise<void> | void) => {
    if (isMain(meta)) {
        try {
            await fn();
        } catch (error) {
            console.error(error);
            process.exit(1);
        }
    }
};
