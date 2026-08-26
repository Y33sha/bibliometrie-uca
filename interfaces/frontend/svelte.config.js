import adapter from '@sveltejs/adapter-static';
import { config as loadEnv } from 'dotenv';
import { fileURLToPath } from 'node:url';

// Source unique de configuration : le `.env` racine, déjà lu par le backend
// (python-dotenv) et docker-compose. On le charge ici aussi pour que `BASE_PATH`
// pilote le préfixe en dev (`npm run dev`) sans variable de shell ni argument.
// `override: true` : le `.env` fait autorité, même si l'environnement injecte
// déjà `BASE_PATH` (cas de l'extension Python `useEnvFile`, dont la valeur est
// par ailleurs corrompue par la conversion de chemin POSIX→Windows de Git Bash).
loadEnv({ path: fileURLToPath(new URL('../../.env', import.meta.url)), override: true });

// `BASE_PATH` : préfixe de déploiement (cf. ROOT_PATH côté backend).
// Vide par défaut → app servie à la racine (cas du dépôt cloné lancé via
// `docker compose`). Définir un sous-chemin (ex. `/bibliometrie`) pour un
// déploiement derrière un reverse-proxy. Lu au build ; à exporter avant
// `npm run build` ou `npm run dev`.
const basePath = process.env.BASE_PATH ?? '';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	kit: {
		// adapter-static : la SPA (ssr=false) est servie en fichiers statiques par
		// FastAPI (cf. interfaces/api/spa.py).
		// `fallback` : les routes non prérendues retombent sur index.html (routage
		// client-side).
		adapter: adapter({ fallback: 'index.html' }),
		paths: {
			base: basePath
		},
		// Content-Security-Policy injectée en `<meta>` dans chaque page. Le mode `hash`
		// calcule l'empreinte des scripts inline de SvelteKit (bootstrap par page) et les
		// autorise nommément, sans `unsafe-inline` : un script injecté (XSS) reste refusé.
		// `style-src` garde `unsafe-inline` : les styles sont injectés au runtime par les
		// libs de visualisation (chart.js, katex, vis-network), non hachables.
		csp: {
			mode: 'hash',
			directives: {
				'default-src': ['self'],
				'script-src': ['self'],
				'style-src': ['self', 'unsafe-inline'],
				'img-src': ['self', 'data:'],
				'font-src': ['self', 'data:'],
				'connect-src': ['self'],
				'object-src': ['none'],
				'base-uri': ['self'],
				'form-action': ['self']
			}
		}
	}
};

export default config;
