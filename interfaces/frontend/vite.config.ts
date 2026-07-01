import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';
import { config as loadEnv } from 'dotenv';
import { fileURLToPath } from 'node:url';

// Lit le `.env` racine (cf. svelte.config.js) sans polluer `process.env` : les
// deux variables consommées ici demandent des précédences opposées.
const fileEnv =
	loadEnv({ path: fileURLToPath(new URL('../../.env', import.meta.url)) }).parsed ?? {};

// `BASE_PATH` : préfixe de déploiement, le `.env` fait autorité (cf. svelte.config.js).
// Doit matcher `paths.base` dans svelte.config.js. Vide par défaut (app à la racine) ;
// en dev, vite strip ce préfixe avant de proxyfier vers le backend.
const basePath = fileEnv.BASE_PATH ?? process.env.BASE_PATH ?? '';

// `API_TARGET` : cible du proxy. L'environnement injecté prime (docker-compose passe
// `http://backend:8000` au conteneur frontend) ; le `.env` sert de repli hors docker
// (`http://127.0.0.1:8003`, backend uvicorn local).
const apiTarget = process.env.API_TARGET || fileEnv.API_TARGET || 'http://127.0.0.1:8003';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		proxy: {
			[`${basePath}/api`]: {
				target: apiTarget,
				rewrite: (path: string) => path.replace(new RegExp(`^${basePath}`), '')
			}
		}
	},
	test: {
		include: ['src/**/*.test.ts'],
	}
});
