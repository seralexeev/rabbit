import babel from '@rolldown/plugin-babel';
import react, { reactCompilerPreset } from '@vitejs/plugin-react';
import autoprefixer from 'autoprefixer';
import dns from 'node:dns';
import fs from 'node:fs/promises';
import path from 'path';
import { defineConfig } from 'vite';

dns.setDefaultResultOrder('verbatim');

// https://vitejs.dev/config/
export default defineConfig({
    cacheDir: '../../node_modules/.vite',
    plugins: [react(), babel({ presets: [reactCompilerPreset()] })],
    css: {
        postcss: {
            plugins: [autoprefixer({})],
        },
    },
    server: {
        port: 3005,
        allowedHosts: ['dev.rabbit'],
        https: {
            key: await fs.readFile(path.resolve(import.meta.dirname, '../../cert/key.pem')),
            cert: await fs.readFile(path.resolve(import.meta.dirname, '../../cert/cert.pem')),
        },
    },
});
