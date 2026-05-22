/**
 * Résout un href de markdown vers une URL finale.
 *
 * - Liens externes (http(s), mailto:, protocol-relative) : inchangés
 * - Liens absolus (/...) : inchangés
 * - Ancres pures (#section) : inchangées (la page courante)
 * - Sinon : lien interne vers une page de doc, résolu par rapport au
 *   slug courant (comme GitHub résout les liens relatifs d'un .md).
 *   `.md` final éventuellement strippé.
 */
export function resolveDocLink(href: string, base: string, currentSlug: string): string {
	if (/^(https?:|mailto:|\/\/|\/|#)/.test(href)) return href;

	const hashIdx = href.indexOf('#');
	const pathPart = hashIdx >= 0 ? href.slice(0, hashIdx) : href;
	const hash = hashIdx >= 0 ? href.slice(hashIdx) : '';
	const cleanPath = pathPart.replace(/\.md$/, '');

	// Le "dossier" du slug courant : tout sauf le dernier segment.
	const dirSegments = currentSlug.split('/').slice(0, -1);
	for (const segment of cleanPath.split('/')) {
		if (segment === '..') dirSegments.pop();
		else if (segment === '.' || segment === '') continue;
		else dirSegments.push(segment);
	}
	return `${base}/docs/${dirSegments.join('/')}${hash}`;
}
