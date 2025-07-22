import react from '@vitejs/plugin-react';
import autoprefixer from 'autoprefixer';
import dns from 'node:dns';
import fs from 'node:fs/promises';
import path from 'path';
import { defineConfig } from 'vite';
import svgr from 'vite-plugin-svgr';

dns.setDefaultResultOrder('verbatim');

// https://vitejs.dev/config/
export default defineConfig({
    cacheDir: '../../node_modules/.vite',
    plugins: [react(), svgr()],
    css: {
        postcss: {
            plugins: [autoprefixer({})],
        },
    },
    server: {
        port: 3005,
        allowedHosts: ['jetson.rabbit', 'dev.rabbit'],
        https: {
            key: await fs.readFile(path.resolve(__dirname, '../../cert/key.pem')),
            cert: await fs.readFile(path.resolve(__dirname, '../../cert/cert.pem')),
        },
    },
});
