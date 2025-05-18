import react from '@vitejs/plugin-react';
import autoprefixer from 'autoprefixer';
import dns from 'node:dns';
import { defineConfig } from 'vite';
import svgr from 'vite-plugin-svgr';

import { mixins } from './src/styles/mixins.ts';
import { extractCssTagPlugin } from './vite/extract-css-tag-plugin.ts';

dns.setDefaultResultOrder('verbatim');

// https://vitejs.dev/config/
export default defineConfig({
    cacheDir: '../../node_modules/.vite',
    plugins: [
        extractCssTagPlugin({
            include: 'src/**/*.{ts,tsx}',
            mixins,
        }),
        react(),
        svgr(),
    ],
    css: {
        postcss: {
            plugins: [autoprefixer({})],
        },
    },
    server: {
        port: 3002,
        proxy: {
            '/api': {
                target: 'http://localhost:3000',
            },
            '/realtime': {
                target: 'http://localhost:3000',
                ws: true,
            },
        },
    },
});
