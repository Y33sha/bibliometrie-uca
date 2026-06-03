import adapter from '@sveltejs/adapter-node';

// `BASE_PATH` : préfixe de déploiement (cf. ROOT_PATH côté backend).
// Lu au build ; à exporter avant `npm run build` ou `npm run dev`.
// Vide = déploiement à la racine.
const basePath = process.env.BASE_PATH ?? '/bibliometrie';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	kit: {
		adapter: adapter(),
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
