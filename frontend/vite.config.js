import { defineConfig } from 'vite';

export default defineConfig({
    root: '.',
    publicDir: 'public',
    server: {
        port: 5173,
        open: true,
        proxy: {
            '/api': { target: 'http://localhost:8000', changeOrigin: true },
            '/auth': { target: 'http://localhost:8000', changeOrigin: true },
            '/ws': { target: 'ws://localhost:8000', ws: true },
        },
    },
    build: {
        outDir: 'dist',
        sourcemap: true,
    },
});
