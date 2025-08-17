import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		port: 5173,
		proxy: {
			'/api': {
				target: 'https://carverjobs-mono-production.up.railway.app',
				changeOrigin: true,
				secure: true
			}
		}
	}
});
