import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		proxy: {
			'/bibliometrie/api': {
				target: process.env.API_TARGET || 'http://127.0.0.1:8003',
				rewrite: (path: string) => path.replace(/^\/bibliometrie/, '')
			}
		}
	},
	test: {
		include: ['src/**/*.test.ts'],
	}
});
