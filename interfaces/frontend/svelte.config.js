import adapter from '@sveltejs/adapter-static';
import { loadProjectEnv } from './project-env.js';

// Source unique de configuration : les fichiers d'environnement du projet (cf.
// project-env.js), déjà lus par le backend et docker-compose. `BASE_PATH` pilote
// ainsi le préfixe en dev (`npm run dev`) sans variable de shell ni argument.
// Les fichiers font autorité, même si l'environnement injecte déjà `BASE_PATH`
// (cas de l'extension Python `useEnvFile`, dont la valeur est par ailleurs
// corrompue par la conversion de chemin POSIX→Windows de Git Bash).
const fileEnv = loadProjectEnv();

// `BASE_PATH` : préfixe de déploiement (cf. ROOT_PATH côté backend).
// Vide par défaut → app servie à la racine (cas du dépôt cloné lancé via
// `docker compose`). Définir un sous-chemin (ex. `/bibliometrie`) pour un
// déploiement derrière un reverse-proxy. Lu au build ; à exporter avant
// `npm run build` ou `npm run dev`.
const basePathBrut = fileEnv.BASE_PATH ?? process.env.BASE_PATH ?? '';
if (basePathBrut !== '' && !basePathBrut.startsWith('/')) {
	throw new Error(`BASE_PATH est vide ou commence par « / » ; reçu : « ${basePathBrut} »`);
}
// Le contrôle ci-dessus établit la forme que le typage de SvelteKit exige du préfixe.
/** @type {'' | `/${string}`} */
const basePath = /** @type {'' | `/${string}`} */ (basePathBrut);

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
