import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';
import { config as loadEnv } from 'dotenv';
import { fileURLToPath } from 'node:url';

// Charge le `.env` racine (cf. svelte.config.js) pour que `BASE_PATH` pilote le
// préfixe du proxy en dev. `dotenv` n'écrase pas une variable déjà exportée.
loadEnv({ path: fileURLToPath(new URL('../../.env', import.meta.url)) });

// Doit matcher `paths.base` dans svelte.config.js (même env var `BASE_PATH`).
// Vide par défaut (app à la racine) ; en dev, vite strip ce préfixe avant de
// proxyfier vers le backend (qui tourne sans `--root-path` en dev local).
const basePath = process.env.BASE_PATH ?? '';

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
