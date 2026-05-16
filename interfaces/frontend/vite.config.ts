import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

// Doit matcher `paths.base` dans svelte.config.js (même env var `BASE_PATH`).
// En dev, vite strip ce préfixe avant de proxyfier vers le backend
// (qui tourne sans `--root-path` en dev local).
const basePath = process.env.BASE_PATH ?? '/bibliometrie';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		proxy: {
			[`${basePath}/api`]: {
				target: process.env.API_TARGET || 'http://127.0.0.1:8003',
				rewrite: (path: string) => path.replace(new RegExp(`^${basePath}`), '')
			}
		}
	},
	test: {
		include: ['src/**/*.test.ts'],
	}
});
