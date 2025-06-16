import react from '@vitejs/plugin-react';
import autoprefixer from 'autoprefixer';
import dns from 'node:dns';
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
        proxy: {
            '/ws': {
                target: 'ws://localhost:3000',
                ws: true,
            },
        },
    },
});
