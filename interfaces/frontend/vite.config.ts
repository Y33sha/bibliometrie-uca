import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';
import { config as loadEnv } from 'dotenv';
import { fileURLToPath } from 'node:url';

// Lit le `.env` racine (cf. svelte.config.js) sans polluer `process.env` : le fichier
// fait autorité sur les deux variables consommées ici, sans que leur valeur fuite vers
// les processus enfants.
const fileEnv =
	loadEnv({ path: fileURLToPath(new URL('../../.env', import.meta.url)), quiet: true }).parsed ?? {};

// `BASE_PATH` : préfixe de déploiement, le `.env` fait autorité (cf. svelte.config.js).
// Doit matcher `paths.base` dans svelte.config.js. Vide par défaut (app à la racine) ;
// en dev, vite strip ce préfixe avant de proxyfier vers le backend.
const basePath = fileEnv.BASE_PATH ?? process.env.BASE_PATH ?? '';

// `API_TARGET` : cible du proxy, le `.env` fait autorité comme pour `BASE_PATH`. Un
// environnement peut en porter une valeur périmée — VSCode injecte le `.env` dans ses
// terminaux et un terminal ouvert avant une modification du fichier en garde l'état
// antérieur —, qui masquerait en silence la valeur du fichier et dirigerait le proxy
// vers un backend qui n'est pas celui du projet.
// Le conteneur frontend ne reçoit que `interfaces/frontend` : le `.env` racine y est
// absent, et la variable que docker-compose injecte (`http://backend:8000`) s'applique.
const apiTarget = fileEnv.API_TARGET || process.env.API_TARGET || 'http://127.0.0.1:8000';

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
