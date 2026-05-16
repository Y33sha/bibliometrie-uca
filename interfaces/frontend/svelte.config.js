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
		}
	}
};

export default config;
