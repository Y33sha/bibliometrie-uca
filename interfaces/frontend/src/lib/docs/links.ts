/**
 * Résout un href de markdown vers une URL finale.
 *
 * - Liens externes (http(s), mailto:, protocol-relative) : inchangés
 * - Liens absolus (/...) : inchangés
 * - Ancres pures (#section) : inchangées (la page courante)
 * - Liens relatifs qui **sortent** de `docs/` (vers le code source du dépôt,
 *   ex. `../../domain/foo.py`) : réécrits vers GitHub. Lus sur GitHub ces
 *   liens fonctionnent en relatif ; dans le visualiseur, ils pointaient vers
 *   des routes de doc inexistantes (404 au prérendu). Le chemin est conservé
 *   verbatim (préfixes `NN-`, extensions).
 * - Sinon : lien interne vers une page de doc, résolu par rapport au slug
 *   courant (comme GitHub résout les liens relatifs d'un .md). `.md` final et
 *   préfixes numériques `NN-` strippés sur chaque segment pour matcher la
 *   convention de slug (cf. `filesystem.server.ts::pathToSlug`).
 */
const NUMERIC_PREFIX_REGEX = /^\d+-/;

// Dépôt source : cible des liens markdown qui sortent de `docs/` vers le code.
// `blob/master` car la branche par défaut du dépôt est `master`.
const REPO_BLOB_URL = 'https://github.com/Y33sha/bibliometrie-uca/blob/master';

export function resolveDocLink(href: string, base: string, currentSlug: string): string {
	if (/^(https?:|mailto:|\/\/|\/|#)/.test(href)) return href;

	const hashIdx = href.indexOf('#');
	const pathPart = hashIdx >= 0 ? href.slice(0, hashIdx) : href;
	const hash = hashIdx >= 0 ? href.slice(hashIdx) : '';

	// Pile partant de la racine `docs/` + le dossier du fichier .md courant
	// (un lien markdown est relatif au fichier qui le contient).
	const segments = ['docs', ...currentSlug.split('/').slice(0, -1)];
	let escaped = false;
	for (const segment of pathPart.split('/')) {
		if (segment === '..') {
			segments.pop();
			// Remonté au-dessus de `docs/` : le lien vise le code source.
			if (segments[0] !== 'docs') escaped = true;
		} else if (segment === '.' || segment === '') {
			continue;
		} else {
			segments.push(segment);
		}
	}

	if (escaped) {
		return `${REPO_BLOB_URL}/${segments.join('/')}${hash}`;
	}

	// Lien interne de doc : retire le `docs` de tête, strippe `.md` et `NN-`.
	const slug = segments
		.slice(1)
		.map((segment) => segment.replace(NUMERIC_PREFIX_REGEX, '').replace(/\.md$/, ''))
		.join('/');
	return `${base}/docs/${slug}${hash}`;
}
