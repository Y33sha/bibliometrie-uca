import adapter from '@sveltejs/adapter-static';

// `BASE_PATH` : préfixe de déploiement (cf. ROOT_PATH côté backend).
// Vide par défaut → app servie à la racine (cas du dépôt cloné lancé via
// `docker compose`). Définir un sous-chemin (ex. `/bibliometrie`) pour un
// déploiement derrière un reverse-proxy. Lu au build ; à exporter avant
// `npm run build` ou `npm run dev`.
const basePath = process.env.BASE_PATH ?? '';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	kit: {
		// adapter-static : la SPA (ssr=false) et les docs prérendues sont servies
		// en fichiers statiques par FastAPI (cf. interfaces/api/deps SPAStaticFiles).
		// `fallback` : les routes non prérendues retombent sur index.html (routage
		// client-side).
		adapter: adapter({ fallback: 'index.html' }),
		paths: {
			base: basePath
		},
		prerender: {
			// Les liens doc→code source sont réécrits vers GitHub (cf.
			// `resolveDocLink`) ; un lien interne cassé reste une erreur de build.
			// `handleMissingId` en `warn` : une ancre écrite à la main et non
			// résolue (ex. accents) n'avorte pas le build (à fiabiliser côté
			// `makeAnchor` ultérieurement).
			handleMissingId: 'warn'
		}
	}
};

export default config;
