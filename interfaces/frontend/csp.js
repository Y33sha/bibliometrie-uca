// Content-Security-Policy injectée en `<meta>` dans chaque page. Le mode `hash`
// calcule l'empreinte des scripts inline de SvelteKit (bootstrap par page) et les
// autorise nommément, sans `unsafe-inline` : un script injecté (XSS) reste refusé.
// `style-src` garde `unsafe-inline` : les styles sont injectés au runtime par les
// libs de visualisation (chart.js, katex, vis-network), non hachables.
/** @type {import('@sveltejs/kit/vite').Config['csp']} */
export const csp = {
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
};
